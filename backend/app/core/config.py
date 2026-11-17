import os
from pathlib import Path


class Settings:
    APP_NAME = os.getenv("APP_NAME", "AgentForge Backend")
    APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    ARTIFACTS_DIR = Path(
        os.getenv(
            "ARTIFACTS_DIR",
            str(Path(__file__).resolve().parents[2] / "artifacts"),
        )
    )


settings = Settings()
