# Luotea Reliability Risk Engine — REST API

A minimal FastAPI service that exposes the pre-built prediction artifacts as a typed, documented API. This makes the demo production-minded: the jury sees a real API contract, not a script.

## Quick start

```bash
# from claude-shenanigans/
pip install -r creative-extensions/api/requirements.txt

# run the server
uvicorn creative-extensions.api.main:app --reload --port 8000
```

Then open:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check — reports sites available |
| `GET` | `/sites` | All sites: `site_id`, `last_seen`, `reliability_risk_index`, `band` |
| `GET` | `/sites/{site_id}/reliability?days=30` | Daily RRI for one site, last N days |
| `GET` | `/sites/{site_id}/dispatch` | Risk-ranked work-order queue (Valmet sites only) |

## Example calls

```bash
# list all sites
curl http://localhost:8000/sites | python -m json.tool

# last 7 days of reliability for Aurora
curl "http://localhost:8000/sites/site_aurora/reliability?days=7" | python -m json.tool

# today's dispatch queue for Valmet L11
curl http://localhost:8000/sites/site_valmet_l11/dispatch | python -m json.tool
```

## Configuration

Set `LUOTEA_PREDICTIONS` env var to override the path to the predictions directory:

```bash
LUOTEA_PREDICTIONS=/path/to/outputs/predictions uvicorn creative-extensions.api.main:app --port 8000
```

## Architecture

```
main.py      FastAPI app — routes + Pydantic response models
loader.py    Single-responsibility data loader — reads Parquet, returns Polars DataFrames
```

No database, no pipeline re-run. The API serves the Gold-derived Parquet artifacts that `make demo` already built.
