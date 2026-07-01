from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from microservices.reference_rates_service.config import DATABASE_URL

# Create database engine
# check_same_thread=False is required for SQLite when used with FastAPI / multi-threading
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()

def get_db():
    """
    FastAPI dependency generator for database sessions.
    Ensures sessions are cleanly closed after request handling.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
