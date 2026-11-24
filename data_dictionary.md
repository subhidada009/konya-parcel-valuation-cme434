# Konya data dictionary

CSV text is UTF-8. CSV and GeoJSON use longitude and latitude in WGS84 (EPSG:4326). In the enriched point files the feature geometry and `x`, `y` use WGS84 / UTM zone 36N (EPSG:32636). Blank listing values represent unavailable information. Case and Turkish spelling are preserved in zoning and deed descriptions.

## Listing and identity fields

`data/value_points.csv` and `.geojson` include the six public raw fields marked below. `data/training_points.csv` adds a project key and retains the 300 accepted rows. The complete raw, joined and source-reference files are in the private academic bundle. Advertisement source fields were supplied by the team from listings recorded on 24 November 2026. Their date resolution is one day; nominal coordinate precision in the CSV does not imply that level of positional accuracy.

| Column | Unit or type | Source and meaning | Scope |
|---|---|---|---|
| `parcel_id` | text | Source-order project key (`KNY-####`). Uploads use `UP-…` keys. | Public training key and private |
| `ilan_no` | text | Original marketplace listing reference | Private |
| `ilan_tarihi` | YYYY-MM-DD | Advertisement issue date | Public raw |
| `url` | URL | Original listing reference | Private |
| `collected_on` | YYYY-MM-DD | Collection date from source CSV | Private |
| `province` | text | Advertised il | Private |
| `district` | text | Advertised ilçe | Private |
| `neighborhood` | text | Advertised mahalle or locality name | Private |
| `ada_no` | text | Advertised cadastral block | Private |
| `parsel_no` | text | Advertised cadastral parcel | Private |
| `imar_durumu` | category | Advertised zoning, one-hot encoded during modelling | Public raw and predictor |
| `area_m2` | m² | Advertised area | Public raw and predictor |
| `price_tl` | TL | Advertised total asking price | Public raw |
| `emsal` | text | Advertised KAKS/FAR as supplied | Private |
| `emsal_ratio` | floor area / parcel area | Numeric parsing of the advertised emsal | Private candidate attribute |
| `gabari` | text | Advertised height code, including Serbest where reported | Private |
| `gabari_m` | m | Numeric advertised height where a number was reported | Private candidate attribute |
| `gabari_state` | category | Numeric height, Serbest, or unspecified | Private candidate attribute |
| `tapu_durumu` | category | Advertised deed status | Private candidate attribute |
| `kimden` | category | Seller type, e.g. Sahibinden or Emlak Ofisinden | Private |
| `coordinate_source` | text | Team source recorded as `listing_map_pin` | Private |
| `latitude` | °N | Map pin latitude | Public raw |
| `longitude` | °E | Map pin longitude | Public raw |
| `x` | m east | Projection of the listing pin or grid centre to UTM 36N | Derived |
| `y` | m north | Projection of the listing pin or grid centre to UTM 36N | Derived |
| `unit_tl_m2` | TL/m² | `price_tl / area_m2`, the target | Derived |
| `outside_aoi` | Boolean | Does the point fall outside the geoBoundaries Konya polygon? | Private audit |
| `cadastral_duplicate` | Boolean | Complete il/ilçe/mahalle/ada/parsel key appears more than once | Private audit |
| `model_inclusion` | Boolean | Eligibility after boundary and cadastral repeat checks | Private audit |
| `exclusion_reason` | text | Reason an input point was out of the training cohort | Private audit |
| `cv_block` | text | Floor of UTM easting and northing divided by 20,000 m | Derived |
| `fold` | 1–5 | Spatial holdout fold assigned by GroupKFold to a whole block | Derived |

## Spatial predictors and support flags

The model uses the following 15 spatial fields plus area and zoning. Copernicus and OSM data are static releases in this build. The imagery query was 20 October through 24 November 2026. `raster_provenance.json` contains individual acquisitions, native resolutions, assets and the amount of each used scene. The OSM extract is dated 23 November 2026. See [data sources](DATA_SOURCES.md) and both provenance JSON files in `data/geo/`.

| Column | Unit | Source, resolution and transformation |
|---|---|---|
| `ndvi_600m` | ratio, −1…1 | Sentinel-2 B08 and B04, 10 m native, 200 m working cell. Mean `(NIR−Red)/(NIR+Red)` within 600 m. |
| `ndbi_600m` | ratio, −1…1 | Sentinel-2 B11 at 20 m and B08 at 10 m, 200 m working cell. Mean `(SWIR−NIR)/(SWIR+NIR)` within 600 m. |
| `mndwi_600m` | ratio, −1…1 | Sentinel-2 B03 at 10 m and B11 at 20 m, 200 m working cell. Mean `(Green−SWIR)/(Green+SWIR)` within 600 m. |
| `elevation_600m` | m | Copernicus DEM GLO-30 digital surface model, STAC tiles dated 22 April 2021, ~30 m native, 200 m working cell. Mean within 600 m. |
| `slope_600m` | degrees | Derived from DEM gradients at 200 m, then mean within 600 m. |
| `ndvi_sd_600m` | ratio | Population standard deviation of accepted NDVI cells within 600 m. Same source dates and pixel sizes as NDVI. |
| `elevation_sd_600m` | m | Population standard deviation of DEM cells within 600 m; same dates and pixel sizes as elevation. |
| `dist_city_centre_m` | m | OSM Konya `place=city` point, Euclidean UTM distance. Source vector. |
| `dist_main_road_m` | m | OSM motorway, trunk, primary or secondary way, nearest geometry distance. Source vector. |
| `dist_transit_m` | m | OSM bus stop, platform or rail/tram station or halt, nearest geometry distance. Source vector. |
| `dist_school_m` | m | OSM `amenity=school`, nearest mapped node or way/polygon. Source vector. |
| `dist_hospital_m` | m | OSM `amenity=hospital`, nearest mapped node or way/polygon. Source vector. |
| `dist_park_m` | m | OSM `leisure=park`, nearest mapped node or way/polygon. Source vector. |
| `dist_waterway_m` | m | OSM river or canal centreline, nearest geometry distance. Source vector. |
| `transit_count_1km` | count | OSM transit geometry centroids within Euclidean 1,000 m. Counts mapped features. Source vector. |
| `raster_gap_filled_n` | count | Number of missing raster samples replaced by their nearest available working cell up to 5,000 m |

## Evaluation, mapping and downloads

| Column | Unit or type | Source and meaning |
|---|---|---|
| `block` | text | Alias of `cv_block` in the out-of-fold prediction table |
| `observed_tl_m2` | TL/m² | Alias of `unit_tl_m2` in out-of-fold predictions |
| `Train mean baseline`, `Random Forest`, `XGBoost`, `LightGBM` | TL/m² | Held-out prediction from each model or the training-fold mean |
| `local_moran_i` | unitless | Standardized price times its spatial lag (symmetric 8-NN, row-standardized) |
| `p_local` | probability | Two-sided conditional randomization p-value, 999 permutations |
| `q_bh` | probability | Benjamini–Hochberg adjustment across 300 local tests |
| `quadrant` | text | Moran scatterplot class (HH, LL, HL or LH) |
| `lisa_fdr_05` | text | Quadrant where q ≤ 0.05, or Not significant |
| `lisa_nominal_05` | text | Exploratory quadrant where unadjusted p ≤ 0.05 |
| `feature`, `mean_abs_shap`, `mean_signed_shap` | text, model-scale values | Feature name and mean absolute / signed group TreeSHAP contributions on the `log1p(TL/m²)` scale |
| `base` | log(1 + TL/m²) | TreeSHAP reference prediction on the transformed scale |
| SHAP feature-name columns | log(1 + TL/m²) | Per-record SHAP contributions, with zoning dummies summed before export |
| `grid_row`, `grid_col` | integer | Zero-based row and column in the 1 km UTM raster |
| `predicted_tl_m2` | TL/m² | Estimated asking price from the selected model and zoning/area scenario |
| `predicted_total_tl` | TL | Location estimate × submitted area |
| `price_index` | unitless | `100 × predicted unit price / study-area median grid prediction`, for the chosen zoning and version |
| `scenario_delta_tl_m2` | TL/m² | Scenario minus baseline estimate at the same location and parcel attributes |
| `baseline_tl_m2` | TL/m² | Location estimate before adding the scenario facility |
| `asking_tl_m2` | TL/m² | User-entered total asking price divided by area |
| `asking_gap_pct` | percent | `100 × (asking unit price / predicted unit price − 1)` |
| `assessment` | category | Underpriced below −15%, Fair from −15% to +15%, Overpriced above +15% |
| `value_class` | integer 0…4 | Very low through very high using index boundaries 50, 80, 120, 180 |
| `zoning` | text | Location-download alias for `imar_durumu` |
| `version` | text | Current model version identifier |
| `model_date`, `date` | ISO date/time | Baseline model date or retraining date in Europe/Istanbul time |

In exported shapefiles, use `shapefile_field_map.json` to resolve short DBF column names. The GeoPackage and CSV retain full names. The GeoTIFF ships with bands `predicted_tl_m2` and `price_index`; pixels without a modelled grid cell carry NoData.
