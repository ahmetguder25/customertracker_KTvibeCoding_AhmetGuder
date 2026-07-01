from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Numeric, UniqueConstraint, Index, Text
from microservices.tuik_sdmx_service.database import Base

class TuikDataJournal(Base):
    """
    Immutable ledger / journal for storing Turkish statistical indicators (TUİK SDMX data).
    Records are never updated once inserted; duplicates are ignored by unique constraints.
    """
    __tablename__ = "tuik_data_journal"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    indicator_code = Column(String(50), nullable=False, index=True)  # e.g., 'TUFE_MONTHLY', 'TUFE_YEARLY'
    indicator_name = Column(String(200), nullable=False)             # e.g., 'Tüketici Fiyat Endeksi (TÜFE) Aylık Değişim Oranı (%)'
    period = Column(String(20), nullable=False, index=True)          # e.g., '2026-05', '2025-12'
    value = Column(Numeric(precision=14, scale=6), nullable=False)
    unit = Column(String(30), nullable=True)                         # e.g., '%', 'Index'
    category = Column(String(100), nullable=True)                    # e.g., 'Enflasyon & Fiyat Endeksleri'
    raw_sdmx_data = Column(Text, nullable=True)                      # Optional JSON/SDMX raw record
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Composite Unique Constraint to prevent duplicate logs for the same indicator and period
    __table_args__ = (
        UniqueConstraint("indicator_code", "period", name="uq_tuik_code_period"),
        Index("ix_tuik_code_period", "indicator_code", "period"),
    )

    def __repr__(self):
        return f"<TuikDataJournal(code='{self.indicator_code}', period='{self.period}', val={self.value})>"
