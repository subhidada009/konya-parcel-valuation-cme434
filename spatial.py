"""Read local vector/raster layers and generate reproducible spatial predictors."""
from collections import defaultdict
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
import rasterio as rio
from rasterio.transform import from_origin, rowcol, xy
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent
GEO = ROOT / 'data' / 'geo'
UTM = 'EPSG:32636'
FROM_WGS = Transformer.from_crs(4326, UTM, always_xy=True)
TO_WGS = Transformer.from_crs(UTM, 4326, always_xy=True)
GRID_M = 1000
RADIUS_M = 1000
OSM_CLASSES = ('city_centre','main_road','transit','school','hospital','park','waterway')
RS = ('ndvi_600m','ndbi_600m','mndwi_600m','elevation_600m','slope_600m','ndvi_sd_600m','elevation_sd_600m')
DISTANCES = tuple(f'dist_{key}_m' for key in OSM_CLASSES)
SPATIAL = (*RS, *DISTANCES, 'transit_count_1km')
NUMERIC = ('area_m2', *SPATIAL)
FEATURES = (*NUMERIC, 'imar_durumu')
PUBLIC = ('latitude', 'longitude', 'price_tl', 'area_m2', 'imar_durumu', 'ilan_tarihi')


def projected(geom):
    return shapely.transform(geom, FROM_WGS.transform, interleaved=False)


class SpatialLayers:
    def __init__(self, root=GEO):
        self.root = Path(root)
        self.boundary_feature = json.loads((self.root/'konya.geojson').read_text(encoding='utf8'))
        self.boundary = shape(self.boundary_feature['geometry'])
        self.boundary_xy = projected(self.boundary)
        with rio.open(self.root/'environment_200m.tif') as dataset:
            self.raster = dataset.read()
            self.raster_transform = dataset.transform
            if tuple(dataset.descriptions) != RS:
                raise ValueError('Unexpected raster band definitions')
        self.raster_nearest = []
        for band in self.raster:
            missing = ~np.isfinite(band)
            distances, nearest = distance_transform_edt(missing, return_indices=True)
            repaired = band[tuple(nearest)]
            repaired[distances*self.raster_transform.a > 5000] = np.nan
            self.raster_nearest.append(repaired)
        classes = defaultdict(list)
        with gzip.open(self.root/'osm_access.geojson.gz','rt',encoding='utf8') as file:
            for item in json.load(file)['features']:
                geom = projected(shape(item['geometry']))
                for key in item['properties']['classes']:
                    classes[key].append(geom)
        self.trees = {name:STRtree(classes[name]) for name in OSM_CLASSES}
        if any(len(t.geometries) == 0 for t in self.trees.values()):
            raise ValueError('OSM layers must have every feature class')
        transit = np.asarray(classes['transit'], dtype=object)
        transit = shapely.centroid(transit)
        self.transit = cKDTree(shapely.get_coordinates(transit))
        self.context_features = self._context(classes)

    def _context(self, classes):
        mask = self.boundary_xy.buffer(2500)
        results = []
        for key in ('main_road','waterway','city_centre'):
            within = [geom for geom in classes[key] if geom.intersects(mask)]
            geometries = shapely.simplify(within, 150)
            geometries = shapely.transform(geometries, TO_WGS.transform, interleaved=False)
            results.extend({'type':'Feature','geometry':json.loads(shapely.to_geojson(geom)),
                            'properties':{'layer':key}} for geom in geometries if not geom.is_empty)
        return {'type':'FeatureCollection','features':results}

    def contains(self, lon, lat):
        return shapely.covers(self.boundary, shapely.points(lon, lat))

    def features_xy(self, x, y):
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        args = np.column_stack((x,y))
        points = shapely.points(args)
        rows, cols = map(np.asarray, rowcol(self.raster_transform, x, y))
        covered = (rows >= 0) & (cols >= 0) & (rows < self.raster.shape[1]) & (cols < self.raster.shape[2])
        result = {}
        fill_count = np.zeros(len(points), dtype=int)
        for key, observed, band in zip(RS, self.raster, self.raster_nearest):
            values = np.full(len(points), np.nan)
            values[covered] = band[rows[covered], cols[covered]]
            fill_count[covered] += (~np.isfinite(observed[rows[covered], cols[covered]]) & np.isfinite(values[covered]))
            result[key] = values
        for name in OSM_CLASSES:
            indices, distance = self.trees[name].query_nearest(points, all_matches=False, return_distance=True)
            values = np.full(len(points), np.nan)
            values[indices[0]] = distance
            result[f'dist_{name}_m'] = values
        result['transit_count_1km'] = self.transit.query_ball_point(args, RADIUS_M, return_length=True)
        result['raster_gap_filled_n'] = fill_count
        return pd.DataFrame(result)

    def enrich(self, rows):
        rows = rows.reset_index(drop=True).copy()
        x, y = FROM_WGS.transform(rows.longitude.to_numpy(), rows.latitude.to_numpy())
        rows['x'] = x
        rows['y'] = y
        return pd.concat([rows.drop(columns=[c for c in (*SPATIAL,'raster_gap_filled_n') if c in rows]),
                          self.features_xy(x,y)],axis=1)

    def grid(self):
        left, bottom, right, top = self.boundary_xy.bounds
        left, bottom = np.floor(np.array([left,bottom])/GRID_M)*GRID_M
        right, top = np.ceil(np.array([right,top])/GRID_M)*GRID_M
        width, height = int((right-left)/GRID_M), int((top-bottom)/GRID_M)
        transform = from_origin(left, top, GRID_M, GRID_M)
        rr, cc = np.indices((height,width))
        x, y = map(np.asarray, xy(transform,rr.ravel(),cc.ravel()))
        inside = shapely.covers(self.boundary_xy, shapely.points(x,y))
        x, y = x[inside], y[inside]
        lon, lat = TO_WGS.transform(x,y)
        frame = pd.DataFrame({'grid_row':rr.ravel()[inside], 'grid_col':cc.ravel()[inside],
                              'longitude':lon,'latitude':lat,'x':x,'y':y})
        return pd.concat([frame,self.features_xy(x,y)],axis=1), transform, (height,width)


def apply_scenario(frame, scenario):
    if not scenario:
        return frame
    key, lon, lat = scenario
    x, y = FROM_WGS.transform(lon, lat)
    result = frame.copy()
    distances = np.hypot(result.x.to_numpy()-x, result.y.to_numpy()-y)
    field = f'dist_{key}_m'
    result[field] = np.minimum(result[field], distances)
    if key == 'transit':
        result['transit_count_1km'] += (distances <= RADIUS_M)
    return result


def apply_overrides(frame, patches):
    if patches is None or patches.empty:
        return frame
    result = frame.copy()
    for field in SPATIAL:
        if field not in patches or not patches[field].notna().any():
            continue
        data = patches.loc[patches[field].notna()]
        tree = cKDTree(data[['x','y']].to_numpy())
        distances, indexes = tree.query(result[['x','y']].to_numpy(), distance_upper_bound=150)
        applies = np.isfinite(distances)
        if applies.any():
            result.loc[applies, field] = data[field].to_numpy()[indexes[applies]]
    return result


def block_key(frame, size=20_000):
    blocks = np.floor(frame[['x','y']].to_numpy() / size).astype(int)
    return np.array([f'{x}:{y}' for x,y in blocks])
