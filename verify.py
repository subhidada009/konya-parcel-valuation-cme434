"""End-to-end local acceptance checks using synthetic upload rows."""
from io import BytesIO
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import rasterio

from app import create_app
from spatial import ROOT, FROM_WGS, block_key


def check():
    client=create_app().test_client()
    visited={}

    def get(name,path):
        response=client.get(path)
        assert response.status_code==200, (path,response.status_code,response.text[:120])
        visited[name]=True
        return response

    home=get('app_names_and_title','/')
    for text in ('SUBHI YASER SUBHI DDA','Magd Shalaby','Sohaib K. M. Abujayyab','A GIS and ML-Based Land Parcel Valuation System for Decision Support'):
        assert text in home.text
    health=get('ready','/health').json
    assert health['grid_cells']==40771
    meta=get('model_metadata','/api/meta').json
    source=pd.read_csv(ROOT/'data/training_points.csv')
    supplied=pd.read_csv(ROOT/'data/value_points.csv')
    assert len(source)==300 and len(supplied)==302
    assert all('ilan_no' not in frame and 'url' not in frame for frame in (source,supplied))
    row=source.iloc[0]
    params={'latitude':row.latitude,'longitude':row.longitude,'area_m2':row.area_m2,
            'zoning':row.imar_durumu}
    from urllib.parse import urlencode
    estimate=get('location_and_listing_estimate','/api/estimate?'+urlencode(params)).json
    assert len(estimate['features'])==15 and estimate['predicted_tl_m2']>0
    for scale,expected in [(.7,'Underpriced'),(1.0,'Fair'),(1.35,'Overpriced')]:
        response=get(f'fair_price_{expected.lower()}','/api/estimate?'+urlencode({**params,'asking_tl':estimate['predicted_total_tl']*scale}))
        assert response.json['assessment']==expected
    response=client.get('/api/estimate?latitude=0&longitude=0')
    assert response.status_code==400 and 'inside Konya' in response.json['error']
    visited['out_of_area_error']=True
    listings=get('budget_area_zoning_search','/api/listings?budget=4500000&min_area=200&max_area=2000&filter_zoning=Konut').json
    assert listings['count']>0 and all(r['price_tl']<=4500000 and 200<=r['area_m2']<=2000 and r['imar_durumu']=='Konut' for r in listings['listings'])
    assert np.all(np.diff([r['asking_gap_pct'] for r in listings['listings']])>=0)
    filtered=get('listing_value_class','/api/listings?filter_zoning=Tarla&listing_class=2').json
    assert all(r['value_class']==2 for r in filtered['listings'])
    grid=get('grid_download','/api/grid?zoning=Tarla&format=csv')
    frame=pd.read_csv(BytesIO(grid.data))
    assert len(frame)==40771 and abs(frame.price_index.median()-100)<1e-10
    assert get('value_surface_png','/api/grid?mode=index&format=png').data.startswith(b'\x89PNG')
    assert get('filtered_value_surface_png','/api/grid?mode=index&value_class=2&format=png').data.startswith(b'\x89PNG')
    scenario='/api/grid?zoning=Konut&mode=delta&scenario=park&scenario_latitude=37.70&scenario_longitude=32.20'
    park=get('park_scenario',scenario).json['scenario_changed_cells']
    transit=get('transit_scenario',scenario.replace('scenario=park','scenario=transit')).json['scenario_changed_cells']
    assert park>0 and transit>0
    for name in ('listings.csv','features.csv','listings.geojson','features.geojson'):
        get('template_'+name,'/api/template/'+name)
    get('listing_download','/api/listings?budget=5000000&filter_zoning=Tarla&download=csv')
    response=client.post('/api/retrain',data={'listings':(BytesIO(b'latitude,longitude\n37,32\n'),'bad.csv')})
    assert response.status_code==400 and 'Missing required columns' in response.json['error']
    visited['invalid_upload_validation']=True
    candidate=frame.iloc[17000:17020].copy()
    candidate['latitude']+=0.000079
    candidate['longitude']+=0.000057
    candidate['x'],candidate['y']=FROM_WGS.transform(candidate.longitude.to_numpy(),candidate.latitude.to_numpy())
    candidate=candidate.loc[~np.isin(block_key(candidate),meta['model']['fixed_holdout_metrics']['blocks'])].iloc[0]
    labels=f'latitude,longitude,price_tl,area_m2,imar_durumu,ilan_tarihi\n{candidate.latitude},{candidate.longitude},1700000,1000,Konut,2026-11-24\n'
    features={'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[candidate.longitude,candidate.latitude]},'properties':{'dist_park_m':125}}]}
    job=client.post('/api/retrain',data={'listings':(BytesIO(labels.encode()),'synthetic.csv'),
                                        'features':(BytesIO(json.dumps(features).encode()),'synthetic.geojson')})
    assert job.status_code==202, job.json
    for _ in range(80):
        update=client.get('/api/retrain/'+job.json['job'])
        assert update.status_code==200,update.json
        if update.json['state']=='complete':
            break
        time.sleep(.25)
    payload=update.json
    assert payload['state']=='complete' and payload['version']!=health['version']
    assert payload['comparison']['training_rows']==301 and payload['comparison']['fixed_test_n']==60
    endpoint='/api/grid?zoning=Tarla&format=csv&version='+payload['version']
    updated=pd.read_csv(BytesIO(get('updated_grid_and_index',endpoint).data))
    assert abs(updated.price_index.median()-100)<1e-10 and not np.allclose(frame.predicted_tl_m2,updated.predicted_tl_m2)
    validated=get('updated_version_metadata','/api/meta?version='+payload['version']).json
    assert validated['comparison']['before']['rmse']>0 and validated['comparison']['after']['rmse']>0
    assert get('base_remains_available','/api/meta').json['version']==health['version']
    with rasterio.open(ROOT/'artifacts/valuation_grid_1km.tif') as dataset:
        image=dataset.read()
        assert dataset.crs.to_epsg()==32636 and dataset.res==(1000,1000)
        assert int(np.isfinite(image[0]).sum())==40771 and np.median(image[1][np.isfinite(image[1])])==100
    visited['geotiff_grid_crs_and_index']=True
    return {'checks':visited,'synthetic_update':payload['comparison'],
            'scenario_changed_cells':{'park':park,'transit':transit}}


if __name__=='__main__':
    results=check()
    content=json.dumps(results,indent=2,ensure_ascii=False)
    print(content)
    if len(sys.argv)>1:
        Path(sys.argv[1]).write_text(content,encoding='utf8')
