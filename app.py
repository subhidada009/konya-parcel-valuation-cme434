"""Offline Flask + Leaflet valuation service. Start with python app.py."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
import math
import os
import secrets
from threading import Lock
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
from PIL import Image
from affine import Affine
from flask import Flask, Response, jsonify, render_template, request, send_file
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.transform import array_bounds, from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
import shapely

from modeling import predict, score, train_model
from spatial import ROOT, FROM_WGS, UTM, PUBLIC, SPATIAL, SpatialLayers, apply_overrides, apply_scenario, block_key

TITLE = 'A GIS and ML-Based Land Parcel Valuation System for Decision Support'
SUPERVISOR = 'Dr. Öğr. Üyesi Sohaib K. M. Abujayyab'
STUDENTS = (('SUBHI YASER SUBHI DDA','2310213583'),('Magd Shalaby','2210213583'))
DATA = ROOT/'data'
OUT = ROOT/'artifacts'
BREAKS = np.array([50,80,120,180],dtype=float)
COLORS = ['#1f4e65','#357b85','#71a594','#e4b96a','#b85c40']
DIFF_BREAKS = np.array([-100,-10,10,100],dtype=float)
DIFF_COLORS = ['#a23841','#dc846f','#e5e9df','#6ba98c','#176954']
CLASS_NAMES = ['Very low','Low','Middle','High','Very high']
MAX_ROWS = 600


@dataclass
class Version:
    id: str
    date: str
    model: object
    listings: pd.DataFrame
    patches: object = None
    comparison: object = None


def round_floats(frame):
    return json.loads(frame.to_json(orient='records',double_precision=8,force_ascii=False))


def numeric(p, key, min_value, max_value, default=None):
    raw = p.get(key)
    if raw is None or raw == '':
        if default is not None:
            return default
        raise ValueError(f'{key} is required.')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be a finite number.') from None
    if not math.isfinite(value) or not min_value <= value <= max_value:
        raise ValueError(f'{key} must be between {min_value:g} and {max_value:g}.')
    return value


def download_csv(frame, name):
    return send_file(BytesIO(frame.to_csv(index=False).encode('utf-8-sig')),mimetype='text/csv',
                     as_attachment=True,download_name=name)


def read_upload(file):
    name = file.filename.lower()
    payload = file.read()
    try:
        if name.endswith('.csv'):
            return pd.read_csv(BytesIO(payload),encoding='utf-8-sig',nrows=MAX_ROWS+1)
        if name.endswith(('.geojson','.json')):
            content = json.loads(payload)
            if not isinstance(content,dict) or content.get('type') != 'FeatureCollection' or not isinstance(content.get('features'),list):
                raise ValueError('GeoJSON must be a FeatureCollection of WGS84 Point features.')
            if 'crs' in content:
                raise ValueError('Use standard GeoJSON WGS84 longitude/latitude without a crs member.')
            rows = []
            for i, feature in enumerate(content['features'][:MAX_ROWS+1],1):
                if not isinstance(feature,dict):
                    raise ValueError(f'Feature {i} must be a GeoJSON Feature.')
                geom,props = feature.get('geometry'),feature.get('properties')
                if feature.get('type') != 'Feature' or not isinstance(geom,dict) or geom.get('type')!='Point' or not isinstance(props,dict):
                    raise ValueError(f'Feature {i} must be a Point with properties.')
                coords = geom.get('coordinates')
                if not isinstance(coords,list) or len(coords)!=2:
                    raise ValueError(f'Feature {i} requires [longitude, latitude].')
                if {'longitude','latitude'} & props.keys():
                    raise ValueError(f'Feature {i} must place coordinates in geometry only.')
                rows.append({**props,'longitude':coords[0],'latitude':coords[1]})
            return pd.DataFrame(rows)
    except (UnicodeError,pd.errors.ParserError,pd.errors.EmptyDataError,json.JSONDecodeError):
        raise ValueError('Could not read file. Use a UTF-8 CSV or standard GeoJSON template.') from None
    raise ValueError('Use a file with a .csv or .geojson extension.')


class ValuationService:
    def __init__(self):
        self.card = json.loads((OUT/'model_card.json').read_text(encoding='utf8'))
        self.layers = SpatialLayers()
        self.model = joblib.load(OUT/'valuation_model.joblib')
        rows = pd.read_csv(DATA/'training_points.csv')
        self.base = self.layers.enrich(rows)
        self.base['unit_tl_m2'] = self.base.price_tl/self.base.area_m2
        self.grid = pd.read_csv(DATA/'grid_features.csv.gz')
        spec = json.loads((DATA/'grid_geometry.json').read_text())
        self.grid_shape = tuple(spec['size'])
        self.grid_transform = Affine(*spec['transform'])
        dest, self.width,self.height = calculate_default_transform(UTM,'EPSG:3857',self.grid_shape[1],
                                                                   self.grid_shape[0],*spec['bounds'])
        self.web_transform = dest
        west,south,east,north = array_bounds(self.height,self.width,dest)
        to_wgs = Transformer.from_crs(3857,4326,always_xy=True)
        lon1,lat1 = to_wgs.transform(west,south)
        lon2,lat2 = to_wgs.transform(east,north)
        self.map_bounds = [[lat1,lon1],[lat2,lon2]]
        web_projector = Transformer.from_crs(4326,3857,always_xy=True)
        geom = shapely.transform(self.layers.boundary,web_projector.transform,interleaved=False)
        self.web_mask = geometry_mask([geom],(self.height,self.width),dest,invert=True)
        self.reference = self.card['reference_area_by_zoning']
        self.versions = OrderedDict()
        self.jobs = {}
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.lock = Lock()
        self.cache = OrderedDict()
        self.baseline = Version(self.card['version'],self.card['date'],self.model,self.base)

    def version(self, token):
        if not token or token == self.baseline.id:
            return self.baseline
        with self.lock:
            version = self.versions.get(token)
            if version is None:
                raise ValueError('This update has expired. Select the base model and upload the files again.')
            self.versions.move_to_end(token)
        return version

    def site(self, p, prefix=''):
        lat = numeric(p,prefix+'latitude',-90,90)
        lon = numeric(p,prefix+'longitude',-180,180)
        if not self.layers.contains(lon,lat):
            raise ValueError('Select a WGS84 coordinate inside Konya Province.')
        return lon,lat

    def scenario(self,p):
        if not p.get('scenario'):
            return None
        kind = p.get('scenario')
        if kind not in ('park','transit'):
            raise ValueError('Scenario type must be park or transit.')
        lon,lat = self.site(p,'scenario_')
        return kind,lon,lat

    def zoning(self,p,default='Tarla'):
        zoning = p.get('zoning') or default
        if zoning not in self.reference:
            raise ValueError('Select a supported imar durumu.')
        return zoning

    def gridded(self,version,zoning,scenario):
        key = (version.id,zoning,scenario)
        with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                return cached
        area = float(self.reference[zoning])
        frame = apply_overrides(self.grid,version.patches).assign(area_m2=area,imar_durumu=zoning)
        base = predict(version.model,frame)
        predicted = base if scenario is None else predict(version.model,apply_scenario(frame,scenario))
        med = float(np.median(predicted))
        result = (predicted,predicted/max(med,1e-9)*100,predicted-base,med,area)
        with self.lock:
            self.cache[key] = result
            while len(self.cache)>12:
                self.cache.popitem(last=False)
        return result

    def listing_results(self,version,params,scenario):
        frame = version.listings.copy()
        budget = numeric(params,'budget',0,1e13,1e13)
        size_min = numeric(params,'min_area',0,1e8,0)
        size_max = numeric(params,'max_area',0,1e8,1e8)
        if size_max < size_min:
            raise ValueError('Maximum area must be at least the minimum area.')
        zoning = params.get('filter_zoning')
        mask = (frame.price_tl<=budget) & frame.area_m2.between(size_min,size_max)
        if zoning:
            self.zoning({'zoning':zoning})
            mask &= frame.imar_durumu.eq(zoning)
        fields = ['parcel_id',*PUBLIC,'unit_tl_m2']
        frame = frame.loc[mask].copy()
        if frame.empty:
            return frame.loc[:,fields]
        modeled = apply_scenario(apply_overrides(frame,version.patches),scenario)
        frame['predicted_tl_m2'] = predict(version.model,modeled)
        frame['asking_gap_pct'] = (frame.unit_tl_m2/np.maximum(frame.predicted_tl_m2,1e-9)-1)*100
        frame['assessment'] = [assessment(g) for g in frame.asking_gap_pct]
        zoning_medians = {item:self.gridded(version,item,scenario)[3] for item in frame.imar_durumu.unique()}
        frame['price_index'] = frame.predicted_tl_m2/frame.imar_durumu.map(zoning_medians).clip(lower=1e-9)*100
        frame['value_class'] = np.searchsorted(BREAKS,frame.price_index,side='right')
        if params.get('listing_class') not in ('',None):
            i = int(numeric(params,'listing_class',0,4))
            frame = frame.loc[frame.value_class.eq(i)]
        cols = ['predicted_tl_m2','asking_gap_pct','assessment','price_index','value_class']
        return frame.sort_values(['asking_gap_pct','price_tl']).loc[:,fields+cols]

    def estimate(self,version,p):
        lon,lat = self.site(p)
        zoning = self.zoning(p)
        area = numeric(p,'area_m2',1,1e8,float(self.reference[zoning]))
        asking = numeric(p,'asking_tl',0,1e13,0)
        frame = self.layers.enrich(pd.DataFrame([{'latitude':lat,'longitude':lon,'area_m2':area,'imar_durumu':zoning}]))
        frame = apply_overrides(frame,version.patches)
        scenario = self.scenario(p)
        base = float(predict(version.model,frame)[0])
        estimate = base if scenario is None else float(predict(version.model,apply_scenario(frame,scenario))[0])
        med = self.gridded(version,zoning,scenario)[3]
        gap = (asking/area/max(estimate,1e-9)-1)*100 if asking else None
        return {'latitude':lat,'longitude':lon,'zoning':zoning,'area_m2':area,'predicted_tl_m2':estimate,
                'predicted_total_tl':estimate*area,'price_index':estimate/max(med,1e-9)*100,
                'asking_tl_m2':asking/area if asking else None,'asking_gap_pct':gap,
                'assessment':assessment(gap) if gap is not None else None,'scenario_delta_tl_m2':estimate-base,
                'baseline_tl_m2':base,'version':version.id,'date':version.date,
                'features':round_floats(frame.loc[:,list(SPATIAL)])[0]}

    def validate_upload(self, frame, label, version):
        if not 1<=len(frame)<=MAX_ROWS:
            raise ValueError(f'Each upload must contain 1 to {MAX_ROWS} rows.')
        columns = set(frame.columns)
        required = set(PUBLIC) if label else {'latitude','longitude'}
        allowed = required if label else required | set(SPATIAL)
        missing,extra = required-columns, columns-allowed
        if missing:
            raise ValueError('Missing required columns: '+', '.join(sorted(missing)))
        if extra:
            raise ValueError('Unsupported columns: '+', '.join(sorted(extra)))
        for field,lo,hi in [('latitude',-90,90),('longitude',-180,180)]:
            validate_numbers(frame,field,lo,hi)
        inside = self.layers.contains(frame.longitude,frame.latitude)
        if not inside.all():
            raise ValueError('Coordinates outside Konya Province on rows '+row_labels(~inside)+'.')
        if frame[['latitude','longitude']].duplicated().any():
            raise ValueError('Repeated coordinates within the file.')
        if label:
            validate_numbers(frame,'area_m2',1,1e8)
            validate_numbers(frame,'price_tl',1,1e13)
            if not frame.imar_durumu.isin(self.reference).all():
                raise ValueError('Unrecognized imar_durumu on rows '+row_labels(~frame.imar_durumu.isin(self.reference))+'.')
            dates = frame.ilan_tarihi.astype(str)
            valid = dates.str.fullmatch(r'\d{4}-\d{2}-\d{2}') & pd.to_datetime(dates,format='%Y-%m-%d',errors='coerce').notna()
            if not valid.all():
                raise ValueError('Use a real YYYY-MM-DD date on rows '+row_labels(~valid)+'.')
            frame = self.layers.enrich(frame.loc[:,list(PUBLIC)])
            pinned = set(self.card['fixed_holdout_metrics']['blocks'])
            overlap = np.isin(block_key(frame),list(pinned))
            if overlap.any():
                raise ValueError('Labels in locked evaluation blocks on rows '+row_labels(overlap)+'.')
            all_coords = pd.concat([version.listings[['x','y']],frame[['x','y']]],ignore_index=True).round(2)
            if all_coords.duplicated().any():
                raise ValueError('An uploaded coordinate duplicates an existing listing.')
            frame['unit_tl_m2'] = frame.price_tl/frame.area_m2
        else:
            features = sorted(columns & set(SPATIAL))
            if not features:
                raise ValueError('Include at least one spatial field from the feature template.')
            for key in features:
                lo,hi = range_for(key)
                validate_numbers(frame,key,lo,hi,optional=True)
                if key=='transit_count_1km' and (frame[key].dropna()%1!=0).any():
                    raise ValueError('transit_count_1km must be an integer.')
            if not frame[features].notna().any(axis=1).all():
                raise ValueError('Each row must specify at least one feature value.')
            frame['x'],frame['y'] = FROM_WGS.transform(frame.longitude.to_numpy(),frame.latitude.to_numpy())
        return frame

    def update(self, version, labels, patches, token):
        joined = version.listings.copy()
        if labels is not None:
            labels['parcel_id'] = [f'UP-{token[:8]}-{i:03d}' for i in range(1,len(labels)+1)]
            joined = pd.concat([joined,labels],ignore_index=True)
        changes = version.patches
        if patches is not None:
            changes = patches if changes is None else pd.concat([patches,changes],ignore_index=True)
            changes = changes.drop_duplicates(['longitude','latitude'],keep='first')
        audit = self.card['fixed_holdout_metrics']
        # Baseline and candidate evaluate the same untouched features and labels.
        held = self.base.loc[np.isin(block_key(self.base),audit['blocks'])]
        dev = joined.loc[~np.isin(block_key(joined),audit['blocks'])]
        family = self.card['best_model']
        candidate = train_model(family,audit['config'],apply_overrides(dev,changes))
        after = score(held.unit_tl_m2,predict(candidate,held))
        configuration = json.loads((OUT/'model_evaluation.json').read_text(encoding='utf8'))['models'][family]['selected']
        production = train_model(family,configuration,apply_overrides(joined,changes))
        date = datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(timespec='seconds')
        comparison = {'before':{k:audit[k] for k in ('r2','rmse','mae')},'after':after,
                      'fixed_test_n':len(held),'training_rows':len(joined),
                      'new_listing_rows':0 if labels is None else len(labels),
                      'new_feature_rows':0 if patches is None else len(patches)}
        return Version(token,date,production,joined,changes,comparison)


def row_labels(mask):
    return ', '.join(map(str,np.flatnonzero(mask)[:8]+2))


def validate_numbers(frame,key,lo,hi,optional=False):
    raw = frame[key]
    converted = pd.to_numeric(raw,errors='coerce')
    valid = converted.between(lo,hi) | (optional & raw.isna())
    if not valid.all():
        raise ValueError(f'{key} must be between {lo:g} and {hi:g} on rows {row_labels(~valid)}.')
    frame[key] = converted


def range_for(key):
    if key in ('ndvi_600m','ndbi_600m','mndwi_600m'):
        return -1,1
    if key=='ndvi_sd_600m':
        return 0,1
    if key=='elevation_600m':
        return -500,6500
    if key=='slope_600m':
        return 0,90
    if key=='elevation_sd_600m':
        return 0,3000
    if key=='transit_count_1km':
        return 0,10000
    return 0,500000


def assessment(percent):
    if percent < -15:
        return 'Underpriced'
    if percent > 15:
        return 'Overpriced'
    return 'Fair'


def create_app():
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
    service = ValuationService()

    @app.errorhandler(ValueError)
    def value_error(error):
        return jsonify(error=str(error)),400

    @app.errorhandler(413)
    def too_big(_):
        return jsonify(error='Upload limit is 2 MB for the combined request.'),413

    @app.get('/')
    def index():
        return render_template('index.html',title=TITLE,students=STUDENTS,supervisor=SUPERVISOR)

    @app.get('/health')
    def health():
        return jsonify(status='ready',version=service.baseline.id,grid_cells=len(service.grid))

    @app.get('/api/meta')
    def meta():
        version=service.version(request.args.get('version'))
        return jsonify(model=service.card,version=version.id,date=version.date,boundary=service.layers.boundary_feature,
                       map_bounds=service.map_bounds,comparison=version.comparison,class_names=CLASS_NAMES,
                       palette=COLORS,delta_palette=DIFF_COLORS)

    @app.get('/api/context')
    def context():
        return jsonify(service.layers.context_features)

    @app.get('/api/listings')
    def listings():
        args = request.args
        version = service.version(args.get('version'))
        result = service.listing_results(version,args,service.scenario(args))
        if args.get('download') == 'csv':
            return download_csv(result,'listing_valuations.csv')
        return jsonify(count=len(result),listings=round_floats(result))

    @app.get('/api/estimate')
    def estimate():
        args=request.args
        return jsonify(service.estimate(service.version(args.get('version')),args))

    @app.get('/api/grid')
    def grid():
        args=request.args
        version=service.version(args.get('version'))
        zoning,scenario=service.zoning(args),service.scenario(args)
        pred,index,delta,median,area=service.gridded(version,zoning,scenario)
        mode=args.get('mode','price')
        if mode not in ('price','index','delta'):
            raise ValueError('Surface must be price, index, or delta.')
        breaks,palette=(DIFF_BREAKS,DIFF_COLORS) if mode=='delta' else (BREAKS,COLORS)
        if args.get('format')=='csv':
            result=service.grid[['grid_row','grid_col','latitude','longitude','x','y']].assign(
                imar_durumu=zoning,area_m2=area,predicted_tl_m2=pred,price_index=index,scenario_delta_tl_m2=delta,
                version=version.id,model_date=version.date)
            return download_csv(result,'konya_valuation_grid.csv')
        if args.get('format')=='png':
            bins=np.searchsorted(breaks,delta if mode=='delta' else index,side='right')
            mask=np.ones(len(index),dtype=bool)
            if args.get('value_class') not in ('',None):
                mask &= bins==int(numeric(args,'value_class',0,4))
            image=np.zeros(service.grid_shape,dtype='uint8')
            cells=service.grid.loc[mask,['grid_row','grid_col']].to_numpy(dtype=int)
            image[cells[:,0],cells[:,1]]=bins[mask]+1
            web=np.zeros((service.height,service.width),dtype='uint8')
            reproject(image,web,src_transform=service.grid_transform,src_crs=UTM,nodata=0,
                      dst_transform=service.web_transform,dst_crs='EPSG:3857',resampling=Resampling.nearest)
            web[~service.web_mask]=0
            colors=np.array([(0,0,0,0)]+[tuple(bytes.fromhex(c[1:]))+(225,) for c in palette],dtype='uint8')
            data=BytesIO()
            Image.fromarray(colors[web]).save(data,format='PNG')
            data.seek(0)
            return send_file(data,mimetype='image/png',max_age=120)
        cls = BREAKS/100*median if mode=='price' else breaks
        return jsonify(median_tl_m2=median,reference_area_m2=area,cells=len(index),breaks=cls.tolist(),
                       palette=palette,delta_min=float(delta.min()),delta_max=float(delta.max()),
                       scenario_changed_cells=int(np.count_nonzero(abs(delta)>1e-6)))

    @app.get('/api/template/<name>')
    def template(name):
        valid={'listings.csv','features.csv','listings.geojson','features.geojson'}
        if name not in valid:
            return jsonify(error='Unknown template.'),404
        return send_file(DATA/'templates'/name,as_attachment=True)

    @app.post('/api/retrain')
    def retrain():
        version=service.version(request.form.get('version'))
        labels=request.files.get('listings')
        features=request.files.get('features')
        if not labels and not features:
            raise ValueError('Select a listings file, a feature file, or both.')
        label_data=service.validate_upload(read_upload(labels),True,version) if labels else None
        feature_data=service.validate_upload(read_upload(features),False,version) if features else None
        if label_data is not None and len(version.listings)+len(label_data)>1500:
            raise ValueError('This browser model is limited to 1,500 training rows.')
        token='v1.1-'+secrets.token_urlsafe(12)
        with service.lock:
            if any(not job.done() for job in service.jobs.values()):
                return jsonify(error='A model update is running. Retry in a few seconds.'),429
            if len(service.jobs)>=12:
                service.jobs.pop(next(iter(service.jobs)))
            service.jobs[token]=service.executor.submit(service.update,version,label_data,feature_data,token)
        return jsonify(job=token,state='running'),202

    @app.get('/api/retrain/<token>')
    def update_status(token):
        with service.lock:
            future=service.jobs.get(token)
            if future is None:
                return jsonify(error='This update is unavailable or expired.'),404
            if not future.done():
                return jsonify(state='running')
            if future.exception() is not None:
                app.logger.error('Model update failed: %s',type(future.exception()).__name__)
                return jsonify(error='The update could not be completed. The prior model is still available.'),500
            version=future.result()
            service.versions[token]=version
            service.versions.move_to_end(token)
            while len(service.versions)>8:
                service.versions.popitem(last=False)
        return jsonify(state='complete',version=version.id,date=version.date,comparison=version.comparison)

    return app


if __name__=='__main__':
    from waitress import serve
    serve(create_app(),host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8000')),threads=4)
