from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "DocuGuard AI TamperLens"
    environment: str = "development"
    cors_origins: str = "*"
    max_upload_mb: int = 15

    # Database
    database_url: str = "sqlite+pysqlite:///./docuguard.db"

    # Azure Blob Storage
    blob_account_url: str = ""  # e.g. https://<account>.blob.core.windows.net
    blob_container: str = "documents"
    blob_connection_string: str = ""  # local dev fallback (Azurite)

    # Azure Document Intelligence
    docintel_endpoint: str = ""
    docintel_key: str = ""  # optional; prefer managed identity in cloud
    docintel_model_id: str = "prebuilt-layout"

    # Azure AI Foundry / OpenAI-compatible endpoint
    foundry_endpoint: str = ""
    foundry_api_key: str = ""  # optional; prefer managed identity
    foundry_deployment: str = "gpt-4o-mini"
    foundry_api_version: str = "2024-10-21"

    # Tier 4: multimodal LLM judge (vision reasoning over the rendered page).
    enable_vision_judge: bool = False

    # Scoring thresholds
    tamper_threshold_review: float = 0.4
    tamper_threshold_reject: float = 0.7

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
