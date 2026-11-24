"""Build local GeoTIFFs from the four exported Konya Earth Engine tiles."""
from argparse import ArgumentParser
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.merge import merge
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from prepare_geo import RASTER_NAMES, save_raster
from spatial import projected

SHARE = 'https://code.earthengine.google.com/9311d2e6c06bdaf77984c75cc689e4dd'
TILES = ('NW','NE','SW','SE')
GEO = ROOT/'data'/'geo'


def assemble(directory):
    paths = [directory/f'Konya_GEE_{cardinal}.tif' for cardinal in TILES]
    hashes = []
    with ExitStack() as opened:
        sources = [opened.enter_context(rasterio.open(path)) for path in paths]
        for path, source in zip(paths,sources):
            if source.crs.to_epsg()!=32636 or source.res!=(200,200) or source.count!=10:
                raise ValueError(f'Unexpected bands, resolution or CRS in {path.name}')
            names = source.descriptions
            if names[0] and tuple(names[:7])!=RASTER_NAMES:
                raise ValueError(f'Unexpected field order in {path.name}: {names}')
            hashes.append({'tile':path.stem[-2:],'name':path.name,
                           'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                           'bounds':list(source.bounds),'size':[source.height,source.width]})
        stack,affine = merge(sources,nodata=-9999,dtype='float32',target_aligned_pixels=True)
    environmental = stack[:7].copy()
    environmental[environmental <= -9990]=np.nan
    rgb = np.nan_to_num(stack[7:10]).clip(0,255).astype('uint8')
    boundary=shape(json.loads((GEO/'konya.geojson').read_text(encoding='utf8'))['geometry'])
    mask=geometry_mask([mapping(projected(boundary))],environmental.shape[1:],affine,invert=True)
    completeness=np.isfinite(environmental[:,mask]).mean(axis=1)
    if np.any(completeness<0.95):
        raise ValueError(f'Earth Engine tiles fail the AOI completeness check: {completeness}')
    valid_rgb = (rgb>0).any(axis=0)
    rgb[:,~mask]=0
    save_raster(GEO/'environment_200m.tif',environmental,affine,RASTER_NAMES)
    save_raster(GEO/'sentinel_rgb_200m.tif',rgb,affine,('red','green','blue'))
    manifest={'platform':'Google Earth Engine','code_editor_snapshot':SHARE,
              'sentinel_collection':'COPERNICUS/S2_SR_HARMONIZED','dem_collection':'COPERNICUS/DEM/GLO30',
              'display_boundary':'FAO/GAUL/2015/level1','analysis_boundary':'geoBoundaries Konya TR-42 ADM1',
              'query_window_inclusive':['2026-10-20','2026-11-24'],
              'acquisition_range_utc':['2026-10-20','2026-11-23'],
              'number_of_acquisition_dates':20,'number_of_candidate_scenes':98,'projection':'EPSG:32636',
              'working_cell_m':200,'focal_radius_m':600,'accepted_scl_classes':[2,4,5,6],
              'raw_valid_share':dict(zip(RASTER_NAMES,map(float,completeness))),
              'rgb_valid_share':float(valid_rgb[mask].mean()),'export_tiles':hashes}
    (GEO/'raster_provenance.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8',newline='\n')
    print('Earth Engine coverage',manifest['raw_valid_share'],'RGB',manifest['rgb_valid_share'])


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('tiles',type=Path)
    assemble(parser.parse_args().tiles)
