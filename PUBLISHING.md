# Publishing and operation

The GitHub repository and Render service are independent of the private submission bundle. Upload only the contents tracked by this repository. Keep listing source identifiers, source URLs, private ad fields and private GIS exports out of the Git history and release assets.

1. Push `main` to the team-owned public GitHub repository. Use the supplied Dockerfile and `render.yaml` to deploy on Render Free. Check `/health`, a listed point, and the grid on the public service. The container includes the model and all map inputs.
2. In Zenodo's GitHub settings, sync and enable the repository. Create a tagged GitHub release from the verified source. `.zenodo.json` supplies the two creators, affiliation, and the supervisor description.
3. Open the resulting DOI record and verify both creators and the supervisor. Add the version DOI badge to the README and the DOI to the final report. Zenodo reserves and assigns the DOI upon ingest, so this documentation edit can follow the archived source release.
4. Each student can add an authenticated contribution commit documenting the part they performed. The collection commit records the work reported by both students without attributing an account or individual rows that the team has not verified.

Render Free services can cold-start after idle periods. The health check is `GET /health`. The baseline is a packaged joblib file. User session models are available in memory and expire after service restart or eviction.

References: [Render Blueprint specification](https://render.com/docs/blueprint-spec), [Zenodo GitHub integration](https://help.zenodo.org/docs/github/).
