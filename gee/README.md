# Earth Engine workflow

Open the [executed Earth Engine snapshot](https://code.earthengine.google.com/9311d2e6c06bdaf77984c75cc689e4dd) or paste `konya_sentinel.js` into the Code Editor. Select an authorized project and run it. The map adds Sentinel-2 natural colour, the GAUL Konya outline and a date label derived from the source imagery. The verified run found 98 candidate scenes on 20 distinct dates, from 20 October to 23 November 2026 UTC.

The seven bands use a 200 m UTM 36N working grid with a 600 m circular neighbourhood. The script uses the Earth Engine GAUL boundary as cartographic context and as the input for the acquisition query. The geoBoundaries outline defines the downstream model area. Click **Prepare GIS GeoTIFF tiles**, download `Konya_GEE_NW.tif`, `Konya_GEE_NE.tif`, `Konya_GEE_SW.tif` and `Konya_GEE_SE.tif`, then assemble them from the repository root using:

```sh
python gee/assemble_tiles.py /path/to/downloaded/tiles
```

The rasters packaged in this release were produced by this workflow. Their SHA-256 values, export dimensions and timestamps are in `data/geo/raster_provenance.json`. The Earth Search code in `prepare_geo.py` provides an alternate offline reconstruction if Earth Engine is inaccessible. Its output can differ from the packaged GEE rasters.

The project runs online only when the Code Editor is used to repeat this upstream analysis. The Flask application works from the downloaded layers supplied in the release. See [Earth Engine access](https://developers.google.com/earth-engine/guides/access) for Cloud project requirements.
