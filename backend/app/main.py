from backend.app.api.routes.repositories import router as repositories_router
from backend.app.api.routes.projects import router as projects_router
from backend.app.api.routes.spec_versions import router as spec_versions_router
from backend.app.api.routes.runs import router as runs_router
from backend.app.api.routes.design_runs import router as design_runs_router

from fastapi import FastAPI

from backend.app.core.config import settings
from backend.app.core.logging_config import setup_logging

# Initialize logging
logger = setup_logging()

# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION
)


@app.get("/")
def home():
    logger.info("Home endpoint accessed")
    

    return {
        "message": f"Welcome to {settings.APP_NAME}"
    }


@app.get("/health")
def health_check():
    logger.info("Health check requested")

    return {
        "status": "healthy",
        "version": settings.APP_VERSION
    }

app.include_router(projects_router)
app.include_router(spec_versions_router)

app.include_router(repositories_router)

app.include_router(runs_router)
app.include_router(design_runs_router)
