from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

class ReferenceRateResponse(BaseModel):
    """
    Schema representing a single financial reference rate entry in the journal.
    """
    id: int
    effective_date: date
    rate_type: str
    rate_value: float
    fetched_at: datetime

    model_config = ConfigDict(from_attributes=True)

class LatestRatesResponse(BaseModel):
    """
    Response schema for GET /api/v1/rates/latest
    Returns the most recent available SOFR and EURIBOR reference rates.
    """
    sofr: Optional[ReferenceRateResponse] = Field(default=None, description="Latest SOFR Overnight rate")
    euribor: Optional[ReferenceRateResponse] = Field(default=None, description="Latest 3-Month EURIBOR rate")
    server_time_utc: datetime = Field(default_factory=datetime.utcnow, description="UTC timestamp of the query")

class RateHistoryResponse(BaseModel):
    """
    Response schema for GET /api/v1/rates/history
    """
    rate_type: str
    count: int
    rates: List[ReferenceRateResponse]

class IngestionResultResponse(BaseModel):
    """
    Response schema for trigger / manual fetch operations.
    """
    success: bool
    message: str
    records_inserted: int
    records_ignored: int
    errors: List[str] = []
