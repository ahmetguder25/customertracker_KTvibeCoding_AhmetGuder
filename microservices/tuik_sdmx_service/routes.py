import os
import json
from fastapi import APIRouter, Depends, Query, HTTPException, status, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List

from microservices.tuik_sdmx_service.database import get_db
from microservices.tuik_sdmx_service.models import TuikDataJournal
from microservices.tuik_sdmx_service.schemas import (
    TuikLatestResponse,
    TuikHistoryResponse,
    TuikRecordResponse,
    IngestionResultResponse,
    ApiKeyStatusResponse
)
from microservices.tuik_sdmx_service.fetchers import run_tuik_sdmx_fetcher
from microservices.tuik_sdmx_service.config import get_tuik_api_key, API_KEY_FILES

router = APIRouter(prefix="/api/v1/tuik", tags=["TUIK SDMX Data"])


@router.get("/latest", response_model=TuikLatestResponse, status_code=status.HTTP_200_OK)
def get_latest_indicators(db: Session = Depends(get_db)):
    """
    Returns the most recent official TUİK statistical indicators (e.g., Monthly/Yearly TÜFE).
    """
    latest_monthly = db.query(TuikDataJournal).filter(
        TuikDataJournal.indicator_code == "TUFE_MONTHLY"
    ).order_by(desc(TuikDataJournal.period)).first()

    latest_yearly = db.query(TuikDataJournal).filter(
        TuikDataJournal.indicator_code == "TUFE_YEARLY"
    ).order_by(desc(TuikDataJournal.period)).first()

    latest_index = db.query(TuikDataJournal).filter(
        TuikDataJournal.indicator_code == "TUFE_INDEX"
    ).order_by(desc(TuikDataJournal.period)).first()

    return TuikLatestResponse(
        monthly_tufe=latest_monthly,
        yearly_tufe=latest_yearly,
        index_tufe=latest_index
    )


@router.get("/history", response_model=TuikHistoryResponse, status_code=status.HTTP_200_OK)
def get_indicator_history(
    indicator: str = Query("TUFE_MONTHLY", description="Indicator code (e.g., 'TUFE_MONTHLY', 'TUFE_YEARLY', 'TUFE_INDEX')", alias="indicator"),
    limit: int = Query(36, ge=1, le=120, description="Number of historical records to return"),
    db: Session = Depends(get_db)
):
    """
    Returns descending, ordered list of historical statistical indicators for tables and charts.
    """
    code_upper = indicator.strip().upper()
    valid_codes = ["TUFE_MONTHLY", "TUFE_YEARLY", "TUFE_INDEX"]
    
    if code_upper not in valid_codes:
        code_upper = "TUFE_MONTHLY"

    records = db.query(TuikDataJournal).filter(
        TuikDataJournal.indicator_code == code_upper
    ).order_by(desc(TuikDataJournal.period)).limit(limit).all()

    return TuikHistoryResponse(
        indicator_code=code_upper,
        count=len(records),
        records=records
    )


@router.post("/fetch", response_model=IngestionResultResponse, status_code=status.HTTP_200_OK)
def trigger_manual_fetch(db: Session = Depends(get_db)):
    """
    Manually triggers an immediate statistical data ingestion cycle from TUİK SDMX / EVDS.
    Safe against duplicate insertions due to immutable ledger unique constraints.
    """
    summary = run_tuik_sdmx_fetcher(db)
    return IngestionResultResponse(
        success=summary["success"],
        message="TÜİK enflasyon verileri başarıyla güncellendi." if summary["success"] else "Veri güncelleme sırasında hata oluştu.",
        records_inserted=summary["records_inserted"],
        records_ignored=summary["records_ignored"],
        errors=summary["errors"],
        api_key_used=summary["api_key_used"]
    )


@router.get("/api-key", response_model=ApiKeyStatusResponse, status_code=status.HTTP_200_OK)
def check_api_key_status():
    """
    Checks if a TUİK API key has been provided in the gitignored config file.
    """
    key = get_tuik_api_key()
    if key:
        masked = key[:4] + "*" * (len(key) - 6) + key[-2:] if len(key) > 6 else "****"
        return ApiKeyStatusResponse(
            configured=True,
            key_masked=masked,
            message="API anahtarı (tuik_api_key.json) yapılandırılmış durumda."
        )
    return ApiKeyStatusResponse(
        configured=False,
        key_masked="",
        message="API anahtarı henüz tuik_api_key.json dosyasına girilmedi."
    )


@router.post("/api-key", response_model=ApiKeyStatusResponse, status_code=status.HTTP_200_OK)
def update_api_key(payload: dict = Body(...)):
    """
    Saves the user's API key into the gitignored tuik_api_key.json file.
    """
    api_key = payload.get("api_key", "").strip()
    target_file = API_KEY_FILES[0]  # Microservice local tuik_api_key.json
    try:
        data = {
            "api_key": api_key,
            "client_id": payload.get("client_id", ""),
            "note": "TUIK SDMX API anahtarı (gitignored)"
        }
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        key = get_tuik_api_key()
        masked = key[:4] + "*" * (len(key) - 6) + key[-2:] if len(key) > 6 else "****"
        return ApiKeyStatusResponse(
            configured=bool(key),
            key_masked=masked,
            message="API anahtarı başarıyla tuik_api_key.json dosyasına kaydedildi."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"API anahtarı kaydedilemedi: {str(e)}")


@router.get("/health", status_code=status.HTTP_200_OK)
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for container monitoring and orchestration.
    """
    count = db.query(TuikDataJournal).count()
    return {
        "status": "healthy",
        "service": "tuik_sdmx_service",
        "ledger_records_count": count
    }
