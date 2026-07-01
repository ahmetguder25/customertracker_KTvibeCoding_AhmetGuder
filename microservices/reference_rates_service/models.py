from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, UniqueConstraint, Index
from microservices.reference_rates_service.database import Base

class ReferenceRateJournal(Base):
    """
    Immutable ledger / journal for storing official financial reference rates.
    Records are never updated once inserted; duplicates are ignored by unique constraints.
    """
    __tablename__ = "reference_rate_journal"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    effective_date = Column(Date, nullable=False, index=True)
    rate_type = Column(String(50), nullable=False, index=True)  # e.g., 'SOFR_ON', 'EURIBOR_3M'
    rate_value = Column(Numeric(precision=12, scale=6), nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Composite Unique Constraint to prevent duplicate logs for the same rate type on the same day
    __table_args__ = (
        UniqueConstraint("effective_date", "rate_type", name="uq_rate_date_type"),
        Index("ix_rate_date_type", "effective_date", "rate_type"),
    )

    def __repr__(self):
        return f"<ReferenceRateJournal(date={self.effective_date}, type='{self.rate_type}', val={self.rate_value})>"
