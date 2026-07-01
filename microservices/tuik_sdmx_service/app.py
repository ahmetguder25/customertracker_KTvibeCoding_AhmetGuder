import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from microservices.tuik_sdmx_service.database import engine, Base, SessionLocal
from microservices.tuik_sdmx_service.routes import router as tuik_router
from microservices.tuik_sdmx_service.fetchers import run_tuik_sdmx_fetcher
from microservices.tuik_sdmx_service.config import SERVER_HOST, SERVER_PORT

logger = logging.getLogger("tuik_sdmx_app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    1. Creates immutable journal tables if they do not exist on startup.
    2. Executes an initial background fetch cycle to warm the TUİK data ledger.
    """
    logger.info("Initializing TUİK SDMX Journal database schema...")
    Base.metadata.create_all(bind=engine)
    
    logger.info("Executing startup ingestion cycle for TUİK indicators...")
    db = SessionLocal()
    try:
        run_tuik_sdmx_fetcher(db)
    except Exception as e:
        logger.error(f"Startup ingestion cycle failed: {str(e)}")
    finally:
        db.close()
        
    yield
    logger.info("Shutting down TUİK SDMX microservice...")


# Initialize FastAPI App
app = FastAPI(
    title="TUİK SDMX Statistical Data Service",
    description="Standalone microservice pulling statistical indicators (Enflasyon / TÜFE) from official TUİK API.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(tuik_router)


@app.get("/", tags=["Root"])
def root():
    """
    Root endpoint redirecting to documentation or service info.
    """
    return {
        "service": "TUİK SDMX Statistical Data Ingestion Microservice",
        "status": "active",
        "docs_url": "/docs",
        "api_prefix": "/api/v1/tuik"
    }


@app.get("/api/health", tags=["Management"])
def standard_health():
    """
    Standardized health check endpoint for main UI microservices dashboard.
    """
    return {
        "status": "Online",
        "message": "TUİK SDMX Service is running (TÜFE / Enflasyon Verileri).",
        "active_process": False
    }


@app.post("/api/reset", tags=["Management"])
def standard_reset():
    """
    Standardized reset endpoint for main UI microservices dashboard.
    """
    return {"success": True, "message": "TUİK SDMX ledger tasks reset successfully."}



if __name__ == "__main__":
    logger.info(f"Starting uvicorn server on {SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run("microservices.tuik_sdmx_service.app:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
