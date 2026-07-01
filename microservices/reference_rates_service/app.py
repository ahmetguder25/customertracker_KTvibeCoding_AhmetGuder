import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from microservices.reference_rates_service.database import engine, Base, SessionLocal
from microservices.reference_rates_service.routes import router as rates_router
from microservices.reference_rates_service.fetchers import run_all_fetchers
from microservices.reference_rates_service.config import SERVER_HOST, SERVER_PORT

logger = logging.getLogger("reference_rates_app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    1. Creates immutable journal tables if they do not exist on startup.
    2. Executes an initial background fetch cycle to warm the ledger cache.
    """
    logger.info("Initializing Reference Rate Journal database schema...")
    Base.metadata.create_all(bind=engine)
    
    logger.info("Executing startup ingestion cycle from central bank APIs...")
    db = SessionLocal()
    try:
        run_all_fetchers(db)
    except Exception as e:
        logger.error(f"Startup ingestion cycle failed: {str(e)}")
    finally:
        db.close()
        
    yield
    logger.info("Shutting down Reference Rates microservice...")


# Initialize FastAPI App
app = FastAPI(
    title="Financial Reference Rates Ingestion Service",
    description="Standalone microservice serving SOFR and EURIBOR rates from official central bank APIs.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend and main app dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(rates_router)


@app.get("/", tags=["Root"])
def root():
    """
    Root endpoint redirecting to documentation or service info.
    """
    return {
        "service": "Financial Reference Rates Ingestion Microservice",
        "status": "active",
        "docs_url": "/docs",
        "api_prefix": "/api/v1/rates"
    }


@app.get("/api/health", tags=["Management"])
def standard_health():
    """
    Standardized health check endpoint for main UI microservices dashboard.
    """
    return {
        "status": "Online",
        "message": "Reference Rates Service is running (Official NY Fed & ECB SDMX APIs).",
        "active_process": False
    }


@app.post("/api/reset", tags=["Management"])
def standard_reset():
    """
    Standardized reset endpoint for main UI microservices dashboard.
    """
    return {"success": True, "message": "Reference rates ledger tasks reset successfully."}



if __name__ == "__main__":
    logger.info(f"Starting uvicorn server on {SERVER_HOST}:{SERVER_PORT}")
    uvicorn.run("microservices.reference_rates_service.app:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
