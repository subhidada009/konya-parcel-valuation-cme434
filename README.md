# A GIS and ML-Based Land Parcel Valuation System for Decision Support

- **Study area:** Konya Province, Türkiye
- **Course:** CME434 Geographic Information Systems, Karabük University
- **Department:** Computer Engineering
- **Supervisor:** Dr. Öğr. Üyesi Sohaib K. M. Abujayyab

| Student | Student number | Contribution |
|---|---|---|
| SUBHI YASER SUBHI DDA | 2310213583 | Collected 150 records and handled the remaining programming work. |
| Magd Shalaby | 2210213583 | Collected 150 records. |

- **Public Web GIS:** [Konya Land Valuation on Render](https://konya-parcel-valuation-cme434.onrender.com/).
- **Zenodo DOI:** [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24509184.svg)](https://doi.org/10.5281/zenodo.24509184)
- **Archived version v1.1.0:** [10.5281/zenodo.24509778](https://doi.org/10.5281/zenodo.24509778).
- **Dated Sentinel-2 RGB:** [Executed Earth Engine Code Editor snapshot](https://code.earthengine.google.com/9311d2e6c06bdaf77984c75cc689e4dd).

## Results

The source has 302 advertisements dated 23–24 November 2026 and recorded on 24 November 2026. After a boundary check and one repeated cadastral key, 300 records remain for modelling. XGBoost had the lowest pooled out-of-fold RMSE across five spatial folds using the features exported from Google Earth Engine. The 1 km grid covers 40,771 Konya cells. The default surface uses a 5,305.5 m² Tarla reference parcel. Change zoning to see the surface for a different median-sized reference parcel.

| Model | Spatial CV R² | RMSE (TL/m²) | MAE (TL/m²) |
|---|---:|---:|---:|
| Random Forest | 0.0794 | 13,097.68 | 2,930.27 |
| XGBoost | 0.0922 | 13,006.54 | 2,769.64 |
| LightGBM | 0.0889 | 13,030.05 | 2,719.86 |

The Global Moran's I of raw advertised unit prices is 0.1482 (999 permutations, two-sided p = 0.001). LISA reports raw and Benjamini–Hochberg-adjusted p-values. The model predicts advertised asking prices. Its spatial R² is low, so rely on it only for screening. An official appraisal requires a licensed valuation expert.

## Run the Web GIS

Use Python 3.12 on Windows, macOS or Linux, or run the Docker image. The server reads the checked-in data and model. The browser downloads Leaflet and the map layers from this server. The application uses no satellite, map-tile or geocoding API at runtime.

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`. The application supports location estimates, listing filters, fair-price comparison, index mapping, park and transit scenarios, CSV/GeoJSON upload, a fixed spatial evaluation set for retraining, and CSV downloads. Retrained models are isolated by their unguessable version keys and held in server memory. Restarting the server restores the persisted baseline release.

## Reproduce the analysis

```sh
python -m pip install -r requirements-research.txt
python train.py
```

`train.py` loads the reduced, screened public points, recomputes point-level features from local layers, repeats nested model selection, produces Moran/LISA and SHAP results, and regenerates the model and grid. A separate private mode validates the three supplied input files and exports `regression_dataset.csv`, a GeoPackage, a shapefile and the private appendix. See [the notebooks](notebooks) and [the data dictionary](data_dictionary.md). The [Earth Engine workflow](gee) produces the packaged RGB and seven environmental bands. `prepare_geo.py --osm-pbf` rebuilds the accessibility vector layer from the archived Geofabrik PBF. [Data licences and attributions](DATA_SOURCES.md) document the shared layers.

Run `python verify.py` for the local feature checks. The synthetic update is an application test, with its results saved in `artifacts/acceptance_tests.json`.

## Submission and publication

The individual listing numbers, URLs, nonpublic ad terms, and enriched private point exports are in the private academic submission. The public and Zenodo release includes the six permitted listing fields, project-generated record keys, derived outputs, and the open covariate layers.

See [team contributions](CONTRIBUTIONS.md), [release instructions](PUBLISHING.md), and [source-code license](LICENSE).
