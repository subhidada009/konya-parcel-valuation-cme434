"""Build submission data, spatial evaluation, trained model and valuation grid."""
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import urlsplit
import json

import joblib
import numpy as np
import pandas as pd
import pyogrio.raw
import rasterio as rio
import shapely
from rasterio.transform import array_bounds

from spatial import ROOT, UTM, PUBLIC, FEATURES, SPATIAL, GRID_M, SpatialLayers, block_key
from modeling import compare, explain, moran_statistics, predict

DATA = ROOT/'data'
OUT = ROOT/'artifacts'
CREATED_ON = '2026-11-24'
MODEL_VERSION = 'v1.1.0'
CADASTRAL = ['province','district','neighborhood','ada_no','parsel_no']
PRIVATE_DTYPES = dict.fromkeys(['ilan_no','ada_no','parsel_no','emsal','gabari'],str)


def save_json(file, info):
    file.write_text(json.dumps(info,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def parcel_keys(n):
    return [f'KNY-{i+1:04d}' for i in range(n)]


def export_points(path, frame, driver='GeoJSON', fields=None, crs='EPSG:4326'):
    xy = ('x','y') if crs==UTM else ('longitude','latitude')
    geometry = shapely.to_wkb(shapely.points(frame.loc[:,list(xy)].to_numpy()))
    fields = fields or {col:col for col in frame.columns}
    values = []
    for key in fields:
        series = frame[key]
        if pd.api.types.is_numeric_dtype(series):
            values.append(series.to_numpy(dtype='float64',na_value=np.nan))
        else:
            values.append(series.astype(object).where(series.notna(),None).to_numpy())
    pyogrio.raw.write(path,geometry,values,list(fields.values()),layer=path.stem,driver=driver,
                      geometry_type='Point',crs=crs,encoding='UTF-8')


def shapefile_fields(columns):
    aliases = {
        'price_tl':'price_tl','imar_durumu':'imar','ilan_tarihi':'ilan_date','unit_tl_m2':'tl_m2',
        'coordinate_source':'coord_src','collected_on':'collect_dt','neighborhood':'mahalle',
        'emsal_ratio':'emsal_num','gabari_m':'gabari_m','gabari_state':'gab_state','raster_gap_filled_n':'gap_n',
        'dist_city_centre_m':'d_city_m','dist_main_road_m':'d_road_m','dist_transit_m':'d_trans_m',
        'dist_school_m':'d_school_m','dist_hospital_m':'d_hosp_m','dist_park_m':'d_park_m',
        'dist_waterway_m':'d_water_m','transit_count_1km':'trans_1km','elevation_600m':'elev600_m',
        'elevation_sd_600m':'elev600_sd','ndvi_sd_600m':'ndvi600sd','unit_tl_m2':'unit_tl_m2',
        'outside_aoi':'out_aoi','model_inclusion':'in_model','exclusion_reason':'exclusion',
        'cadastral_duplicate':'cad_repeat','fold':'cv_fold',
    }
    fields = {c:aliases.get(c,c[:10]) for c in columns}
    if len(set(fields.values())) != len(fields):
        raise ValueError(f'Field aliases collide: {fields}')
    return fields


def prepare_private(source, output, layers):
    raw = pd.read_csv(source/'value_points_private .csv',dtype=PRIVATE_DTYPES)
    public = pd.read_csv(source/'value_points.csv')
    geo = json.loads((source/'value_points_private.geojson').read_text(encoding='utf-8-sig'))
    assert raw[list(PUBLIC)].equals(public[list(PUBLIC)]) and len(geo['features']) == len(raw)
    for row, feature in zip(raw.itertuples(),geo['features']):
        assert [row.longitude,row.latitude] == feature['geometry']['coordinates']
        assert row.ilan_no == str(feature['properties']['ilan_no'])
    assert raw.ilan_no.is_unique and raw.url.is_unique
    assert (raw.area_m2.gt(0) & raw.price_tl.gt(0)).all()
    price = raw.price_tl/raw.area_m2
    assert np.allclose(raw.unit_tl_m2,price,rtol=1e-8,atol=1e-8)
    raw['unit_tl_m2'] = price
    raw['parcel_id'] = parcel_keys(len(raw))
    raw['outside_aoi'] = ~layers.contains(raw.longitude,raw.latitude)
    raw['emsal_ratio'] = pd.to_numeric(raw.emsal,errors='coerce')
    raw['gabari_m'] = pd.to_numeric(raw.gabari,errors='coerce')
    raw['gabari_state'] = np.select([raw.gabari_m.notna(),raw.gabari.eq('Serbest')],
                                   ['Numeric height','Serbest'],default='Unspecified')
    complete = raw[CADASTRAL].notna().all(axis=1)
    raw['cadastral_duplicate'] = complete & raw.duplicated(CADASTRAL,keep=False)
    ordered = raw.loc[complete & ~raw.outside_aoi].sort_values(['ilan_tarihi','parcel_id'],ascending=[False,True])
    duplicate = ordered.index[ordered.duplicated(CADASTRAL,keep='first')]
    raw['exclusion_reason'] = np.where(raw.outside_aoi,'Outside Konya boundary','')
    raw.loc[duplicate,'exclusion_reason'] = 'Repeat cadastral key'
    raw['model_inclusion'] = raw.exclusion_reason.eq('')
    output.mkdir(exist_ok=True,parents=True)
    links = raw[['parcel_id','ilan_no','ilan_tarihi','url','collected_on','district','neighborhood',
                 'ada_no','parsel_no','model_inclusion','exclusion_reason']]
    links.to_csv(output/'appendix_A_listing_references_PRIVATE.csv',index=False,encoding='utf-8-sig')
    raw.to_csv(output/'value_points.csv',index=False,encoding='utf-8-sig')
    export_points(output/'value_points.geojson',raw)
    accepted = raw.loc[raw.model_inclusion].copy()
    summary = {'input_records':len(raw),'model_records':len(accepted),
               'ad_dates':sorted(raw.ilan_tarihi.unique()),'collection_dates':sorted(raw.collected_on.unique()),
               'source_domains':raw.url.map(lambda value:urlsplit(value).hostname).value_counts().to_dict(),
               'districts_raw':int(raw.district.nunique()),'districts_modeled':int(accepted.district.nunique()),
               'district_counts':accepted.district.value_counts().to_dict(),
               'zoning_counts':accepted.imar_durumu.value_counts().to_dict(),
               'missing_emsal_raw':int(raw.emsal.isna().sum()),'missing_gabari_raw':int(raw.gabari.isna().sum()),
               'non_numeric_gabari_raw':int((raw.gabari.notna() & raw.gabari_m.isna()).sum()),
               'outside_aoi':int(raw.outside_aoi.sum()),'duplicate_records_flagged':int(raw.cadastral_duplicate.sum()),
               'duplicate_records_excluded':len(duplicate),'collection_date_source':'supplied listing CSV'}
    for col in ['unit_tl_m2','area_m2','price_tl']:
        stats = accepted[col].quantile([0,.25,.5,.75,.95,1])
        summary[f'{col}_quantiles'] = {str(k):float(v) for k,v in stats.items()}
    save_json(OUT/'data_audit.json',summary)
    raw[list(PUBLIC)].to_csv(DATA/'value_points.csv',index=False)
    export_points(DATA/'value_points.geojson',raw.loc[:,list(PUBLIC)])
    # Row identifiers are generated from source order and contain no marketplace identifier.
    accepted[['parcel_id',*PUBLIC]].to_csv(DATA/'training_points.csv',index=False)
    return accepted


def persist_grid(grid, transform, size, matches, target, reference_area, root=OUT):
    retained = ['grid_row','grid_col','latitude','longitude','x','y','raster_gap_filled_n',*SPATIAL]
    grid.loc[:,retained].to_csv(DATA/'grid_features.csv.gz',index=False,float_format='%.8g',
                                compression={'method':'gzip','mtime':0})
    save_json(DATA/'grid_geometry.json',{'crs':UTM,'size':list(size),'transform':list(transform)[:6],
                                        'bounds':array_bounds(*size,transform),'cell_m':GRID_M})
    median = float(np.median(matches))
    index = matches/median*100 if median > 0 else np.zeros_like(matches)
    result = grid.loc[:,retained[:7]].assign(imar_durumu=target,area_m2=reference_area,
                                           predicted_tl_m2=matches,price_index=index)
    result.to_csv(root/'valuation_grid_1km.csv.gz',index=False,float_format='%.9g',
                  compression={'method':'gzip','mtime':0})
    image = np.full((2,*size),np.nan,dtype='float32')
    image[0,result.grid_row,result.grid_col] = matches
    image[1,result.grid_row,result.grid_col] = index
    with rio.open(root/'valuation_grid_1km.tif','w',driver='GTiff',height=size[0],width=size[1],
                  count=2,dtype='float32',nodata=np.nan,crs=UTM,transform=transform,compress='deflate') as ds:
        ds.write(image)
        ds.set_band_description(1,'predicted_tl_m2')
        ds.set_band_description(2,'price_index')
    return {'cells':len(result),'reference_area_m2':reference_area,'reference_zoning':target,
            'index_median_tl_m2':median,'cell_m':GRID_M,
            'predicted_tl_m2_quantiles':{str(q):float(np.quantile(matches,q)) for q in (0,.05,.25,.5,.75,.95,1)},
            'spectral_gaps_remaining':int(result.shape[0] - grid.loc[:,list(SPATIAL)].notna().all(axis=1).sum())}


def run(private_source=None, private_output=None):
    OUT.mkdir(exist_ok=True)
    layers = SpatialLayers()
    if private_source:
        base = prepare_private(private_source,private_output,layers)
    else:
        base = pd.read_csv(DATA/'training_points.csv')
    rows = layers.enrich(base)
    rows['unit_tl_m2'] = rows.price_tl/rows.area_m2
    rows['cv_block'] = block_key(rows)
    assert len(rows) >= 300 and len(FEATURES) >= 15
    assert layers.contains(rows.longitude,rows.latitude).all()
    model,metrics,estimates = compare(rows)
    rows['fold'] = estimates.fold.astype(int)
    distribution,detail,shap_meta = explain(model,rows,metrics['best_model'])
    results,lisa = moran_statistics(rows,{'unit_tl_m2':rows.unit_tl_m2.to_numpy(),
                                         'log_unit_tl_m2':np.log1p(rows.unit_tl_m2.to_numpy()),
                                         'oof_residual':estimates[metrics['best_model']].to_numpy()-rows.unit_tl_m2.to_numpy()})
    analysis = pd.concat([rows[['parcel_id','longitude','latitude','x','y','unit_tl_m2','fold']],lisa],axis=1)
    analysis.to_csv(OUT/'lisa_points.csv',index=False)
    export_points(OUT/'lisa_points.geojson',analysis)
    save_json(OUT/'moran_results.json',results)
    distribution.to_csv(OUT/'shap_summary.csv',index=False)
    detail.to_csv(OUT/'shap_values.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    estimates.to_csv(OUT/'spatial_cv_predictions.csv',index=False)
    save_json(OUT/'model_evaluation.json',metrics)
    grid,aff,size = layers.grid()
    reference = rows.groupby('imar_durumu').area_m2.median().to_dict()
    zoning = rows.imar_durumu.mode().iat[0]
    ref_area = float(reference[zoning])
    predicted = predict(model,grid.assign(area_m2=ref_area,imar_durumu=zoning))
    grid_meta = persist_grid(grid,aff,size,predicted,zoning,ref_area)
    meta = {'version':MODEL_VERSION,'date':CREATED_ON,'best_model':metrics['best_model'],'reference_area_by_zoning':reference,
            'grid':grid_meta,'features':list(FEATURES),'shap':shap_meta,
            'training_missing_count':rows[list(FEATURES)].isna().sum().astype(int).to_dict(),
            'training_gap_filled_n':int((rows.raster_gap_filled_n>0).sum()),
            'training_rows':len(rows),'cv_metrics':metrics['models'][metrics['best_model']]['metrics'],
            'fixed_holdout_metrics':metrics['update_holdout']}
    save_json(OUT/'model_card.json',meta)
    joblib.dump(model,OUT/'valuation_model.joblib',compress=3)
    if private_source:
        columns = ['ilan_no','latitude','longitude','x','y','unit_tl_m2']
        field_order = columns + [c for c in rows if c not in columns]
        rows = rows.loc[:,field_order].copy()
        rows.to_csv(private_output/'regression_dataset.csv', index=False,encoding='utf-8-sig')
        export_points(private_output/'value_points.gpkg',rows,'GPKG',crs=UTM)
        fields = shapefile_fields(rows.columns)
        export_points(private_output/'value_points.shp',rows,'ESRI Shapefile',fields,UTM)
        save_json(private_output/'shapefile_field_map.json',fields)
    print('Grid',grid_meta,'metadata and exports generated',flush=True)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--private-source',type=Path)
    parser.add_argument('--private-output',type=Path)
    args = parser.parse_args()
    if bool(args.private_source) != bool(args.private_output):
        parser.error('--private-source and --private-output must be used together')
    run(args.private_source,args.private_output)
