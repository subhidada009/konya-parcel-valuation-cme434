// CME434. Execute in the Earth Engine Code Editor using an authorized Cloud project.
// Upstream only. The deployed application never contacts Earth Engine.
var start = '2026-10-20';
var end = '2026-11-25';            // exclusive
var konya = ee.FeatureCollection('FAO/GAUL/2015/level1')
  .filter(ee.Filter.eq('ADM0_NAME', 'Turkey'))
  .filter(ee.Filter.eq('ADM1_NAME', 'Konya'));
var area = konya.geometry();
var bands = ['B2','B3','B4','B8','B11'];
var images = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
  .filterBounds(area).filterDate(start,end)
  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE',65));
var dates = ee.List(images.aggregate_array('system:time_start')).map(function(t) {
  return ee.Date(t).format('YYYY-MM-dd');
}).distinct().sort();
var clear = images.map(function(image) {
  var scl = image.select('SCL');
  var mask = scl.eq(2).or(scl.eq(4)).or(scl.eq(5)).or(scl.eq(6));
  return image.select(bands).multiply(0.0001).updateMask(mask)
    .copyProperties(image,['system:time_start','CLOUDY_PIXEL_PERCENTAGE']);
});
var composite = clear.sort('CLOUDY_PIXEL_PERCENTAGE',false).mosaic().clip(area);
var rgbStyle = {bands:['B4','B3','B2'],min:0,max:0.31,gamma:1.28};
Map.centerObject(konya,8);
Map.addLayer(composite,rgbStyle,'Sentinel-2 RGB · 20 Oct–24 Nov 2026');
Map.addLayer(konya.style({color:'FCE9AA',width:2,fillColor:'00000000'}),{},'Konya Province');
var stamp = ui.Label('Konya · Sentinel-2 image dates loading…');
Map.add(ui.Panel({widgets:[stamp],style:{position:'bottom-left',backgroundColor:'ffffffcc',padding:'6px'}}));
dates.evaluate(function(values,error) {
  if (error || !values || !values.length) { stamp.setValue('Sentinel-2 acquisition dates unavailable'); return; }
  stamp.setValue('Konya · Sentinel-2 acquisitions: '+values[0]+' to '+values[values.length-1]);
});
print('Sentinel-2 scene acquisition dates (UTC)',dates);
print('Sentinel-2 scene count',images.size());
print('Konya boundary count',konya.size());
var ndvi = composite.normalizedDifference(['B8','B4']).rename('ndvi');
var ndbi = composite.normalizedDifference(['B11','B8']).rename('ndbi');
var mndwi = composite.normalizedDifference(['B3','B11']).rename('mndwi');
var dem = ee.ImageCollection('COPERNICUS/DEM/GLO30').select('DEM').mosaic()
  .setDefaultProjection('EPSG:32636',null,30).rename('elevation');
var slope = ee.Terrain.slope(dem).rename('slope');
var kernel = ee.Kernel.circle({radius:600,units:'meters'});
var features = ndvi.addBands([ndbi,mndwi,dem,slope])
  .reduceNeighborhood({reducer:ee.Reducer.mean(),kernel:kernel}).clip(area);
Export.image.toDrive({image:composite.visualize(rgbStyle),description:'Konya_Sentinel2_RGB_20261020_20261124',
  region:area,scale:200,crs:'EPSG:32636',maxPixels:1e9});
Export.image.toDrive({image:features.toFloat(),description:'Konya_GEE_Features_600m',
  region:area,scale:200,crs:'EPSG:32636',maxPixels:1e9});
