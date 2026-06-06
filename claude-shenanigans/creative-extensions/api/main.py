"""
Luotea Reliability Risk Engine — REST API

Serves pre-built prediction artifacts as a typed API contract.
No pipeline re-run; reads Gold-derived Parquet from outputs/predictions/.

Run:
    cd creative-extensions
    uvicorn api.main:app --reload --port 8000

Docs:
    http://localhost:8000/docs          (Swagger UI)
    http://localhost:8000/redoc         (ReDoc)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import loader

app = FastAPI(
    title="Luotea Reliability Risk Engine",
    description=(
        "Predictive maintenance API: SLA-breach risk scores, daily Reliability Index, "
        "and risk-ranked dispatch queues — served from the Luotea Gold pipeline."
    ),
    version="0.1.0",
    contact={"name": "Luotea Hackathon 2026"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- models

class SiteInfo(BaseModel):
    site_id: str
    last_seen: date
    reliability_risk_index: float
    band: str  # CALM | NORMAL | ELEVATED


class ReliabilityPoint(BaseModel):
    signal_date: date
    reliability_risk_index: float
    maintenance_risk: Optional[float]
    alarm_pressure: Optional[float]
    energy_anomaly: Optional[float]
    incident_pressure: Optional[float]


class WorkOrder(BaseModel):
    wo_no: int
    work_type_eng: str
    priority_id_str: str
    breach_risk_pct: float
    risk_band: str  # HIGH | MEDIUM | LOW


class HealthResponse(BaseModel):
    status: str
    sites_available: int
    predictions_dir: str


# --------------------------------------------------------------------------- routes

@app.get("/", include_in_schema=False)
def root():
    """Swagger UI is the entry point — no separate landing page."""
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthResponse, tags=["Meta"])
def health():
    """Liveness check — also reports how many sites have prediction artifacts."""
    sites = loader.known_sites()
    return {
        "status": "ok",
        "sites_available": len(sites),
        "predictions_dir": str(loader.PREDICTIONS_DIR),
    }


@app.get("/sites", response_model=list[SiteInfo], tags=["Sites"])
def list_sites():
    """All sites in the portfolio, with their latest Reliability Risk Index and date."""
    df = loader.sites()
    return df.to_dicts()


@app.get(
    "/sites/{site_id}/reliability",
    response_model=list[ReliabilityPoint],
    tags=["Reliability"],
)
def get_reliability(site_id: str, days: int = 30):
    """
    Daily Reliability Risk Index for one site.

    - **site_id**: e.g. `site_valmet_l11`, `site_aurora`
    - **days**: number of most-recent days to return (default 30)
    """
    df = loader.reliability(site_id, days=days)
    if df.is_empty():
        raise HTTPException(
            status_code=404,
            detail=f"No reliability data for '{site_id}'. "
                   f"Known sites: {loader.known_sites()}",
        )
    return df.to_dicts()


@app.get(
    "/sites/{site_id}/dispatch",
    response_model=list[WorkOrder],
    tags=["Dispatch"],
)
def get_dispatch(site_id: str):
    """
    Today's risk-ranked work-order queue for one site.

    Returns work orders sorted by `breach_risk_pct` descending — do the top ones first.
    Only available for sites with ERP work-order data (Valmet sites).
    """
    df = loader.dispatch(site_id)
    if df.is_empty():
        raise HTTPException(
            status_code=404,
            detail=f"No dispatch data for '{site_id}'. "
                   f"Dispatch is only available for Valmet sites with work-order history.",
        )
    return df.to_dicts()
