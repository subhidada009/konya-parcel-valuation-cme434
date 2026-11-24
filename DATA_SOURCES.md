# Data sources and licensing

| Layer | Source, date and resolution | Terms and attribution |
|---|---|---|
| Province boundary | geoBoundaries TUR ADM1 gbOpen, 2021 geometry, Konya TR-42, pinned simplified file | Boundary metadata identifies OpenStreetMap as the source and CC BY-SA 2.0. [Pinned file](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/TUR/ADM1/geoBoundaries-TUR-ADM1_simplified.geojson) |
| Sentinel-2 RGB and indices | Google Earth Engine `COPERNICUS/S2_SR_HARMONIZED`, 98 candidate scenes across 20 dates. The 20 Oct–24 Nov 2026 query returned acquisitions from 20 Oct–23 Nov 2026 UTC. The manifest lists the exported tile checksums. Native 10 m RGB/B08 and 20 m SWIR/SCL. Working grid 200 m and focal radius 600 m. | Contains modified Copernicus Sentinel data 2026. [Earth Engine catalog](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED), [executed snapshot](https://code.earthengine.google.com/9311d2e6c06bdaf77984c75cc689e4dd) |
| Elevation and slope | Earth Engine `COPERNICUS/DEM/GLO30`. Original TanDEM-X data were acquired from 2011–2015, with older fill where needed. Native 1 arcsecond (~30 m), 200 m working grid. | [Copernicus DEM source and terms](https://doi.org/10.5270/esa-c5d3d65), [Earth Engine catalog](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_DEM_GLO30) |
| Road and amenity vectors | Geofabrik Türkiye OSM extract `turkey-261123.osm.pbf`, 23 November 2026, source vector resolution | © OpenStreetMap contributors. `osm_access.geojson.gz` is the local reusable extract under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). [OpenStreetMap attribution](https://www.openstreetmap.org/copyright), [source extract](https://download.geofabrik.de/europe/turkey/turkey-261123.osm.pbf) |
| Listing snapshot | Student-supplied publicly visible listings, collected 24 November 2026. Points are listing map pins. | Official market references and enriched ad details are in the private report appendix and data. Public data are confined to the course brief's reduced schema. Source publisher rights remain with their respective holders. |
| Browser mapping library | Vendored Leaflet 1.9.4 | [Leaflet BSD-2-Clause license](static/vendor/LEAFLET-LICENSE.txt) |

The project MIT license applies to original source code. It does not replace the separate data and library terms above. The app uses a local vector context and does not include an external map tileset.

Produced using Copernicus WorldDEM-30. © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under Copernicus by the European Union and ESA. All rights reserved.
