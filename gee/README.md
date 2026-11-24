# Earth Engine workflow

Open `konya_sentinel.js` in the [Earth Engine Code Editor](https://code.earthengine.google.com/) under your authorized project and run it. The map adds Sentinel-2 natural colour, the GAUL Konya outline and a date label derived from the filtered Sentinel acquisition timestamps. The console lists the scene dates and the number of intersecting scenes. The RGB and seven-band focal feature exports are available under **Tasks**.

The seven bands use a 200 m UTM 36N working grid with a 600 m circular neighbourhood. The script uses the Earth Engine public GAUL boundary, which can differ from the geoBoundaries outline used to screen and model the main course dataset. The model and released GeoTIFFs are reproducible from the Earth Search imagery and DEM assets listed in `data/geo/raster_provenance.json`.

The project runs online only when the Code Editor is used to repeat this upstream analysis. The Flask application works from the downloaded layers supplied in the release. See [Earth Engine access](https://developers.google.com/earth-engine/guides/access) for Cloud project requirements.
