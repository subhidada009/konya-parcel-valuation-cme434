"""Offline application layer preparation. Network access is required only for this CLI."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import rasterio as rio
from affine import Affine
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy.ndimage import convolve
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import transform

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'geo'
CRS = 'EPSG:32636'
PROJ = Transformer.from_crs('EPSG:4326', CRS, always_xy=True)
STEP = 200
STAC = 'https://earth-search.aws.element84.com/v1/search'
BOUNDARY_META = 'https://www.geoboundaries.org/api/current/gbOpen/TUR/ADM1/'
BOUNDARY = 'https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/TUR/ADM1/geoBoundaries-TUR-ADM1_simplified.geojson'
OSM_PBF = 'https://download.geofabrik.de/europe/turkey/turkey-261123.osm.pbf'
BOX = (31.10, 36.70, 34.65, 39.55)
S2_BANDS = ('red', 'green', 'blue', 'nir08', 'swir16', 'scl')
RASTER_NAMES = ('ndvi_600m', 'ndbi_600m', 'mndwi_600m', 'elevation_600m', 'slope_600m',
                'ndvi_sd_600m', 'elevation_sd_600m')


def read_json(url):
    with urlopen(Request(url, headers={'User-Agent': 'CME434-Research/1.0'}), timeout=90) as response:
        return json.load(response)


def get_boundary():
    cached = DATA / 'konya.geojson'
    if not cached.exists():
        features = read_json(BOUNDARY)['features']
        konya = next(item for item in features if item['properties']['shapeISO'] == 'TR-42')
        cached.write_text(json.dumps(konya, separators=(',', ':')), encoding='utf8')
    return shape(json.loads(cached.read_text(encoding='utf8'))['geometry'])


def stac_items(collection, cache, date=None):
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding='utf8'))['features']
    query = {'collections':collection, 'bbox':','.join(map(str, BOX)), 'limit':100}
    if date:
        query['datetime'] = date
    if date:
        query['query'] = json.dumps({'eo:cloud_cover': {'lt': 65}})
    next_url = f'{STAC}?{urlencode(query)}'
    items = []
    while next_url:
        data = read_json(next_url)
        items.extend(data['features'])
        next_url = next((a['href'] for a in data.get('links', []) if a['rel']=='next'), None)
    return items


def layout(aoi):
    left, bottom, right, top = transform(PROJ.transform, aoi).bounds
    left, bottom = (np.floor(np.array([left, bottom]) / STEP) - 8) * STEP
    right, top = (np.ceil(np.array([right, top]) / STEP) + 8) * STEP
    return from_origin(left, top, STEP, STEP), (int((top-bottom)/STEP), int((right-left)/STEP))


def resample(asset, aff, size, method):
    url = asset['href']
    if url.startswith('s3://'):
        bucket, key = url[5:].split('/', 1)
        url = f'https://{bucket}.s3.amazonaws.com/{key}'
    with rio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_MAX_RETRY='2',
                 GDAL_HTTP_TIMEOUT='30', CPL_VSIL_CURL_CHUNK_SIZE='65536'):
        with rio.open(url) as src:
            resolution = abs(src.res[0]) if src.crs.is_projected else abs(src.res[0]) * 100_000
            factor = max(1, 2 ** int(np.floor(np.log2(STEP / resolution))))
            if factor == 1:
                values = src.read(1)
            else:
                values = src.read(1, out_shape=(int(np.ceil(src.height/factor)), int(np.ceil(src.width/factor))),
                                  resampling=Resampling.nearest)
            src_transform = src.transform * Affine.scale(src.width/values.shape[1], src.height/values.shape[0])
            result = np.full(size, np.nan, dtype='float32')
            reproject(values, result, src_transform=src_transform, src_crs=src.crs,
                      src_nodata=0 if asset.get('title','').startswith('Scene') else src.nodata,
                      dst_transform=aff, dst_crs=CRS, dst_nodata=np.nan, resampling=method)
    return result


def sentinel_candidates(items, aoi):
    tiled = defaultdict(list)
    for item in items:
        if shape(item['geometry']).intersects(aoi):
            tiled[item['properties']['grid:code']].append(item)
    ordered = []
    for _, scenes in sorted(tiled.items()):
        candidates = sorted(scenes, key=lambda item: (item['properties'].get('eo:cloud_cover', 100),
                                                      item['id']), reverse=False)
        ordered.extend(candidates[:4])
    return sorted(ordered, key=lambda item: (item['properties'].get('eo:cloud_cover', 100), item['id']))


def scene_arrays(item, aff, size):
    bands = item['assets']
    out = []
    for key in S2_BANDS:
        band = resample(bands[key], aff, size, Resampling.nearest if key == 'scl' else Resampling.bilinear)
        info = bands[key].get('raster:bands', [{}])[0]
        if key != 'scl':
            band = band * info.get('scale', 0.0001) + info.get('offset', -0.1)
        out.append(band)
    print('Sentinel', item['id'], flush=True)
    return np.stack(out)


def ratio(a, b):
    return np.divide(a-b, a+b, out=np.full_like(a, np.nan), where=(a+b) > 0.01).clip(-1, 1)


def mean_buffer(array, kernel):
    valid = np.isfinite(array)
    count = convolve(valid.astype('float32'), kernel, mode='constant')
    total = convolve(np.where(valid, array, 0), kernel, mode='constant')
    return np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)


def save_raster(path, array, aff, names):
    with rio.open(path, 'w', driver='GTiff', height=array.shape[1], width=array.shape[2],
                  count=array.shape[0], dtype=array.dtype, crs=CRS, transform=aff, compress='deflate',
                  predictor=3 if array.dtype.kind == 'f' else 2,
                  nodata=np.nan if array.dtype.kind == 'f' else 0, tiled=True) as dst:
        dst.write(array)
        for i, name in enumerate(names, 1):
            dst.set_band_description(i, name)


def prepare_rasters(aoi, cache):
    aff, size = layout(aoi)
    mask = geometry_mask([mapping(transform(PROJ.transform, aoi))], size, aff, invert=True)
    items = stac_items('sentinel-2-c1-l2a', cache / 'sentinel_wide.json' if cache else None,
                       '2026-10-20T00:00:00Z/2026-11-24T23:59:59Z')
    if cache:
        (cache / 'sentinel_wide.json').write_text(json.dumps({'features':items}), encoding='utf8')
    scenes = sentinel_candidates(items, aoi.buffer(0.01))
    dem = stac_items('cop-dem-glo-30', cache / 'dem.json' if cache else None)
    dem = [d for d in dem if shape(d['geometry']).intersects(aoi.buffer(0.04))]
    mosaic = np.full((5, *size), np.nan, 'float32')
    dem_z = np.full(size, np.nan, 'float32')
    scene_log = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks = [pool.submit(resample, item['assets']['data'], aff, size, Resampling.bilinear) for item in dem]
        for item, task in zip(dem, tasks):
            fresh = task.result()
            np.copyto(dem_z, fresh, where=np.isnan(dem_z) & np.isfinite(fresh))
            print('DEM', item['id'], flush=True)
        for batch in range(0, len(scenes), 5):
            group = scenes[batch:batch+5]
            scene_tasks = [pool.submit(scene_arrays, item, aff, size) for item in group]
            for item, task in zip(group, scene_tasks):
                values = task.result()
                clear = np.isin(values[-1], [2, 4, 5, 6]) & np.isfinite(values[:-1]).all(axis=0)
                replace = clear & np.isnan(mosaic[0])
                mosaic[:, replace] = values[:-1, replace]
                scene_log.append({'id':item['id'], 'tile':item['properties']['grid:code'],
                                  'datetime':item['properties']['datetime'],
                                  'cloud_cover_pct':item['properties'].get('eo:cloud_cover'),
                                  'used_cells_in_study_area':int(np.count_nonzero(replace & mask)),
                                  'assets':{key:item['assets'][key]['href'] for key in S2_BANDS}})
    red, green, blue, nir, swir = mosaic
    grad_y, grad_x = np.gradient(dem_z, STEP)
    slope = np.degrees(np.arctan(np.hypot(grad_x, grad_y)))
    yy, xx = np.ogrid[-3:4, -3:4]
    kernel = (xx**2 + yy**2 <= 9).astype('float32')
    raw = (ratio(nir, red), ratio(swir, nir), ratio(green, swir), dem_z, slope)
    means = [mean_buffer(a, kernel) for a in raw]
    deviations = [np.sqrt(np.maximum(0, mean_buffer(raw[i]**2, kernel) - means[i]**2)) for i in [0,3]]
    features = np.stack(means + deviations).astype('float32')
    cov = np.isfinite(features[:, mask]).mean(axis=1)
    if np.any(cov < 0.82):
        raise ValueError(f'Insufficient raster coverage: {cov}')
    # Expose genuine cloud gaps in RGB. Fill small feature gaps from the nearest valid cell
    # at sampling time only, and retain the original NoData mask in the delivered rasters.
    save_raster(DATA / 'environment_200m.tif', features, aff, RASTER_NAMES)
    rgb = np.nan_to_num((np.maximum(mosaic[:3], 0) / 0.31).clip(0, 1) ** 0.78)
    rgb = np.where(np.isfinite(mosaic[:3]), np.maximum(1, np.round(rgb * 255)), 0).astype('uint8')
    save_raster(DATA / 'sentinel_rgb_200m.tif', rgb, aff, ('red', 'green', 'blue'))
    meta = {'sentinel_collection':'sentinel-2-c1-l2a', 'stac':STAC, 'projection':CRS, 'cell_m':STEP,
            'buffer_m':600, 'sentinel_scenes':scene_log, 'boundary':BOUNDARY,
            'dem_tiles':[{'id':i['id'], 'datetime':i['properties']['datetime'],
                          'source':i['assets']['data']['href']} for i in dem],
            'raw_valid_share':dict(zip(RASTER_NAMES, map(float, cov))),
            'rgb_valid_share':float(np.isfinite(red[mask]).mean())}
    (DATA/'raster_provenance.json').write_text(json.dumps(meta, indent=2), encoding='utf8')
    print('Raster coverage', cov, 'RGB', meta['rgb_valid_share'], flush=True)


def osm_categories(tags):
    matches = []
    if tags.get('highway') in ('motorway', 'trunk', 'primary', 'secondary'):
        matches.append('main_road')
    if tags.get('highway') == 'bus_stop' or tags.get('public_transport') in ('platform', 'station') or tags.get('railway') in ('station', 'tram_stop', 'halt'):
        matches.append('transit')
    if tags.get('amenity') in ('school', 'hospital'):
        matches.append(tags.get('amenity'))
    if tags.get('leisure') == 'park':
        matches.append('park')
    if tags.get('waterway') in ('river', 'canal'):
        matches.append('waterway')
    if tags.get('place') == 'city' and tags.get('name', '').casefold() == 'konya':
        matches.append('city_centre')
    return matches


def prepare_osm(path, aoi):
    import osmium
    aoi = aoi.buffer(0.3)
    tags = [('highway', value) for value in ['motorway', 'trunk', 'primary', 'secondary', 'bus_stop']]
    tags += [('public_transport', value) for value in ['platform','station']]
    tags += [('railway', value) for value in ['station','tram_stop','halt']]
    tags += [('amenity','school'), ('amenity','hospital'), ('leisure','park'), ('waterway','river'),
             ('waterway','canal'), ('place','city')]
    features = []
    reader = osmium.FileProcessor(str(path), entities=osmium.osm.NODE | osmium.osm.WAY).with_locations('flex_mem')
    reader = reader.with_filter(osmium.filter.TagFilter(*tags))
    bounds = aoi.bounds
    for item in reader:
        groups = osm_categories(item.tags)
        if not groups:
            continue
        is_node = item.is_node()
        if is_node:
            lon, lat = item.location.lon, item.location.lat
            if not (bounds[0]<=lon<=bounds[2] and bounds[1]<=lat<=bounds[3]):
                continue
            geom = Point(lon, lat)
            if groups == ['main_road'] or groups == ['waterway']:
                continue
        else:
            coords = [(node.location.lon, node.location.lat) for node in item.nodes if node.location.valid()]
            if len(coords) < 2 or not any(bounds[0]<=x<=bounds[2] and bounds[1]<=y<=bounds[3] for x,y in coords):
                continue
            geom = LineString(coords)
            if len(coords) >= 4 and coords[0] == coords[-1] and not set(groups).intersection({'main_road','waterway'}):
                geom = Polygon(coords).buffer(0)
        if not geom.is_empty and geom.intersects(aoi):
            features.append({'type':'Feature', 'geometry':mapping(geom),
                             'properties':{'classes':groups,'osm_id':f'{"n" if is_node else "w"}{item.id}'}})
    counts = {key:sum(key in f['properties']['classes'] for f in features)
              for key in ('city_centre','main_road','transit','school','hospital','park','waterway')}
    if not all(counts.values()):
        raise ValueError(f'Missing an OSM class: {counts}')
    with gzip.open(DATA/'osm_access.geojson.gz','wt',encoding='utf8') as handle:
        json.dump({'type':'FeatureCollection','features':features},handle,separators=(',',':'))
    meta = {'source':OSM_PBF, 'snapshot_label':'2026-11-23', 'buffer_degrees':0.3,
            'counts':counts, 'license':'ODbL 1.0', 'attribution':'OpenStreetMap contributors',
            'prepared_utc':datetime.now(timezone.utc).isoformat()}
    (DATA/'osm_provenance.json').write_text(json.dumps(meta,indent=2), encoding='utf8')
    print('OSM extract', counts, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raster', action='store_true')
    parser.add_argument('--osm-pbf', type=Path)
    parser.add_argument('--stac-cache', type=Path)
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    boundary = get_boundary()
    if args.raster:
        prepare_rasters(boundary, args.stac_cache)
    if args.osm_pbf:
        prepare_osm(args.osm_pbf, boundary)
