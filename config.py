"""
SkillTrace Configuration Module
Loads settings from environment variables and provides sensible defaults for local development.
"""
import os
from pathlib import Path
from pydantic import BaseModel, Field

# Base directories
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TAXONOMY_DIR = BASE_DIR / "taxonomy"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

class Settings(BaseModel):
    # Ollama Local API Settings
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
    )

    ollama_api_key: str = Field(
        default_factory=lambda: os.getenv(
            "OLLAMA_API_KEY", "ollama"
        )
    )

    ollama_model: str = Field(
        default_factory=lambda: os.getenv(
            "OLLAMA_MODEL", "llama3.2:3b"
        )
    )
    # GitHub Settings
    github_token: str = Field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN", "").strip()
    )
    webhook_secret: str = Field(
        default_factory=lambda: os.getenv("WEBHOOK_SECRET", "").strip()
    )

    # Server & Port Settings
    api_host: str = Field(
        default_factory=lambda: os.getenv("API_HOST", "127.0.0.1")
    )
    api_port: int = Field(
        default_factory=lambda: int(os.getenv("API_PORT", "8000"))
    )
    dashboard_port: int = Field(
        default_factory=lambda: int(os.getenv("DASHBOARD_PORT", "8501"))
    )

    # Storage Settings
    database_path: str = Field(
        default_factory=lambda: os.getenv("DATABASE_PATH", str(DATA_DIR / "skilltrace.db"))
    )

    # Polling & Ingestion Settings
    polling_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("POLLING_INTERVAL_SECONDS", "60"))
    )
    request_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
    )
    max_file_size_bytes: int = Field(
        default_factory=lambda: int(os.getenv("MAX_FILE_SIZE_BYTES", "500000"))  # 500 KB limit
    )

    # Taxonomy Path
    taxonomy_file: str = Field(
        default_factory=lambda: str(TAXONOMY_DIR / "skills.yaml")
    )

    # Exclusions for authorship & originality (SRS Section 4.3 FR-15)
    vendor_directories: list[str] = [
        "node_modules", "vendor", "venv", ".venv", "env", ".env",
        "dist", "build", "target", "out", ".git", ".github",
        ".cache", "__pycache__", "site-packages", "pods", "bower_components"
    ]

    generated_file_patterns: list[str] = [
        "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
        "Cargo.lock", "pnpm-lock.yaml", "composer.lock", "go.sum",
        ".min.js", ".min.css", ".bundle.js", ".map"
    ]

# Global singleton
settings = Settings()
