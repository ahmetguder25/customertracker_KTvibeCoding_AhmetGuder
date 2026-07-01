from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from decimal import Decimal

class TuikRecordResponse(BaseModel):
    id: int
    indicator_code: str
    indicator_name: str
    period: str
    value: Decimal
    unit: Optional[str] = None
    category: Optional[str] = None
    fetched_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TuikLatestResponse(BaseModel):
    monthly_tufe: Optional[TuikRecordResponse] = None
    yearly_tufe: Optional[TuikRecordResponse] = None
    index_tufe: Optional[TuikRecordResponse] = None

class TuikHistoryResponse(BaseModel):
    indicator_code: str
    count: int
    records: List[TuikRecordResponse]

class IngestionResultResponse(BaseModel):
    success: bool
    message: str
    records_inserted: int
    records_ignored: int
    errors: List[str]
    api_key_used: bool

class ApiKeyStatusResponse(BaseModel):
    configured: bool
    key_masked: str
    message: str
