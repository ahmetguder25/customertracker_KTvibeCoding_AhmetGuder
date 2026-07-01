from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List

from microservices.reference_rates_service.database import get_db
from microservices.reference_rates_service.models import ReferenceRateJournal
from microservices.reference_rates_service.schemas import (
    LatestRatesResponse,
    RateHistoryResponse,
    ReferenceRateResponse,
    IngestionResultResponse
)
from microservices.reference_rates_service.fetchers import run_all_fetchers

router = APIRouter(prefix="/api/v1/rates", tags=["Reference Rates"])


@router.get("/latest", response_model=LatestRatesResponse, status_code=status.HTTP_200_OK)
def get_latest_rates(db: Session = Depends(get_db)):
    """
    Returns the most recent official SOFR and EURIBOR reference rates from the ledger.
    """
    latest_sofr = db.query(ReferenceRateJournal).filter(
        ReferenceRateJournal.rate_type == "SOFR_ON"
    ).order_by(desc(ReferenceRateJournal.effective_date)).first()

    latest_euribor = db.query(ReferenceRateJournal).filter(
        ReferenceRateJournal.rate_type == "EURIBOR_3M"
    ).order_by(desc(ReferenceRateJournal.effective_date)).first()

    return LatestRatesResponse(
        sofr=latest_sofr,
        euribor=latest_euribor
    )


@router.get("/history", response_model=RateHistoryResponse, status_code=status.HTTP_200_OK)
def get_rate_history(
    type: str = Query("ALL", description="Rate type identifier (e.g., 'ALL', 'SOFR_ON', 'EURIBOR_3M', etc.)", alias="type"),
    limit: int = Query(500, ge=1, le=5000, description="Number of historical records to return (max 5000)"),
    db: Session = Depends(get_db)
):
    """
    Returns a descending, ordered list of historical rates for UI tables and charts.
    """
    rate_type_upper = type.strip().upper()
    
    # Map common shortcuts
    if rate_type_upper == "SOFR":
        rate_type_upper = "SOFR_ON"
    elif rate_type_upper == "EURIBOR":
        rate_type_upper = "EURIBOR_3M"

    if rate_type_upper == "ALL":
        records = db.query(ReferenceRateJournal).order_by(
            desc(ReferenceRateJournal.effective_date), desc(ReferenceRateJournal.id)
        ).limit(limit).all()
    else:
        records = db.query(ReferenceRateJournal).filter(
            ReferenceRateJournal.rate_type == rate_type_upper
        ).order_by(desc(ReferenceRateJournal.effective_date)).limit(limit).all()

    return RateHistoryResponse(
        rate_type=rate_type_upper,
        count=len(records),
        rates=records
    )


@router.post("/fetch", response_model=IngestionResultResponse, status_code=status.HTTP_200_OK)
def trigger_manual_fetch(db: Session = Depends(get_db)):
    """
    Manually triggers an immediate data ingestion cycle from official New York Fed and ECB SDMX APIs.
    Safe against duplicate insertions due to immutable ledger unique constraints.
    """
    summary = run_all_fetchers(db)
    return IngestionResultResponse(
        success=summary["success"],
        message="Reference rates ingestion cycle completed.",
        records_inserted=summary["records_inserted"],
        records_ignored=summary["records_ignored"],
        errors=summary["errors"]
    )


@router.get("/health", status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for container monitoring and orchestration.
    """
    count = db.query(ReferenceRateJournal).count()
    return {
        "status": "healthy",
        "service": "reference_rates_service",
        "ledger_records_count": count
    }
