# Data sources and licensing

| Layer | Source, date and resolution | Terms and attribution |
|---|---|---|
| Province boundary | geoBoundaries TUR ADM1 gbOpen, 2021 geometry, Konya TR-42, pinned simplified file | Boundary metadata identifies OpenStreetMap as the source and CC BY-SA 2.0. [Pinned file](https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/TUR/ADM1/geoBoundaries-TUR-ADM1_simplified.geojson) |
| Sentinel-2 RGB and indices | Sentinel-2 Level-2A Collection 1 via Element 84 Earth Search, 20 Oct–24 Nov 2026 query window. Asset times actually used are in `data/geo/raster_provenance.json`. Native 10 m RGB/B08 and 20 m SWIR/SCL. Processing grid 200 m; focal statistics 600 m. | Contains modified Copernicus Sentinel data 2026. [AWS Open Data registry](https://registry.opendata.aws/sentinel-2-l2a-cogs/) |
| Elevation and slope | Copernicus DEM GLO-30 via Earth Search, tiles dated in the provenance manifest, 1 arcsecond (~30 m) input, 200 m working grid | European Union, Copernicus DEM. [AWS data registry and license](https://registry.opendata.aws/copernicus-dem/) |
| Road and amenity vectors | Geofabrik Türkiye OSM extract `turkey-261123.osm.pbf`, 23 November 2026, source vector resolution | © OpenStreetMap contributors. `osm_access.geojson.gz` is the local reusable extract under [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/). [OpenStreetMap attribution](https://www.openstreetmap.org/copyright), [source extract](https://download.geofabrik.de/europe/turkey/turkey-261123.osm.pbf) |
| Listing snapshot | Student-supplied publicly visible listings, collected 24 November 2026. Points are listing map pins. | Official market references and enriched ad details are in the private report appendix and data. Public data are confined to the course brief's reduced schema. Source publisher rights remain with their respective holders. |
| Browser mapping library | Vendored Leaflet 1.9.4 | [Leaflet BSD-2-Clause license](static/vendor/LEAFLET-LICENSE.txt) |

The project MIT license applies to original source code. It does not replace the separate data and library terms above. The app uses a local vector context and does not include an external map tileset.
