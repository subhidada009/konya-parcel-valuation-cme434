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
- **Zenodo DOI:** [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24509348.svg)](https://doi.org/10.5281/zenodo.24509348)

## Results

The source has 302 advertisements dated 23–24 November 2026 and recorded on 24 November 2026. After a boundary check and one repeated cadastral key, 300 records remain for modelling. LightGBM had the lowest pooled out-of-fold RMSE across five spatial folds. The 1 km grid covers 40,771 Konya cells. The default surface uses a 5,305.5 m² Tarla reference parcel. Change zoning to see the surface for a different median-sized reference parcel.

| Model | Spatial CV R² | RMSE (TL/m²) | MAE (TL/m²) |
|---|---:|---:|---:|
| Random Forest | 0.0769 | 13,115.64 | 3,152.16 |
| XGBoost | 0.0930 | 13,000.87 | 2,795.44 |
| LightGBM | 0.0935 | 12,996.77 | 2,686.84 |

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

`train.py` loads the reduced, screened public points, recomputes point-level features from local layers, repeats nested model selection, produces Moran/LISA and SHAP results, and regenerates the model and grid. A separate private mode validates the three supplied input files and exports `regression_dataset.csv`, a GeoPackage, a shapefile and the private appendix. See [the notebooks](notebooks) and [the data dictionary](data_dictionary.md). `prepare_geo.py` rebuilds the GIS layers from Earth Search COGs and an archived Geofabrik PBF. [Earth Engine Code Editor script](gee/konya_sentinel.js) provides the separate upstream Earth Engine workflow. [Data licences and attributions](DATA_SOURCES.md) document the shared layers.

Run `python verify.py` for the local feature checks. The synthetic update is an application test, with its results saved in `artifacts/acceptance_tests.json`.

## Submission and publication

The individual listing numbers, URLs, nonpublic ad terms, and enriched private point exports are in the private academic submission. The public and Zenodo release includes the six permitted listing fields, project-generated record keys, derived outputs, and the open covariate layers.

See [team contributions](CONTRIBUTIONS.md), [release instructions](PUBLISHING.md), and [source-code license](LICENSE).
