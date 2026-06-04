import logging
import os
import uuid

from .config import get_settings

logger = logging.getLogger("docuguard.storage")

settings = get_settings()

# Local artifact directory used when no Blob configuration is present (dev mode).
LOCAL_ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "..", "artifacts")


class StorageService:
    """Stores raw uploads and generated artifacts.

    Uses Azure Blob Storage when configured (managed identity preferred,
    connection string as a dev fallback). Otherwise writes to a local folder
    so the app can run end-to-end without cloud dependencies.
    """

    def __init__(self) -> None:
        self._container_client = None
        self._mode = "local"
        self._init_blob()
        if self._mode == "local":
            os.makedirs(LOCAL_ARTIFACT_DIR, exist_ok=True)

    def _init_blob(self) -> None:
        try:
            if settings.blob_connection_string:
                from azure.storage.blob import BlobServiceClient

                svc = BlobServiceClient.from_connection_string(settings.blob_connection_string)
                self._container_client = svc.get_container_client(settings.blob_container)
                self._ensure_container()
                self._mode = "blob"
            elif settings.blob_account_url:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import BlobServiceClient

                cred = DefaultAzureCredential()
                svc = BlobServiceClient(account_url=settings.blob_account_url, credential=cred)
                self._container_client = svc.get_container_client(settings.blob_container)
                self._ensure_container()
                self._mode = "blob"
        except Exception:
            # Fall back to local storage on any Blob init failure (dev resilience).
            self._container_client = None
            self._mode = "local"

    def _ensure_container(self) -> None:
        try:
            self._container_client.create_container()
        except Exception:
            pass  # already exists

    @property
    def mode(self) -> str:
        return self._mode

    def save(self, data: bytes, suffix: str, content_type: str = "application/octet-stream") -> str:
        name = f"{uuid.uuid4()}{suffix}"
        if self._mode == "blob":
            try:
                from azure.storage.blob import ContentSettings

                blob = self._container_client.get_blob_client(name)
                blob.upload_blob(
                    data,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                )
                return blob.url
            except Exception:
                # A blob write can fail at request time even when init succeeded
                # (e.g. managed identity missing "Storage Blob Data Contributor",
                # or the role assignment has not propagated yet). Fall back to
                # local storage so the request still succeeds instead of 500-ing.
                logger.exception(
                    "Blob upload failed; falling back to local storage for this artifact."
                )
                os.makedirs(LOCAL_ARTIFACT_DIR, exist_ok=True)
        path = os.path.abspath(os.path.join(LOCAL_ARTIFACT_DIR, name))
        with open(path, "wb") as f:
            f.write(data)
        return f"file://{path}"

    def load(self, uri: str) -> bytes | None:
        """Read back bytes previously written by ``save``.

        Supports the ``file://`` local URIs and Azure Blob URLs this service
        produces. Returns ``None`` if the artifact can no longer be retrieved
        (e.g. ephemeral local storage wiped on redeploy).
        """
        if not uri:
            return None
        try:
            if uri.startswith("file://"):
                path = uri[len("file://"):]
                with open(path, "rb") as f:
                    return f.read()
            if self._mode == "blob" and self._container_client is not None:
                name = uri.rsplit("/", 1)[-1]
                blob = self._container_client.get_blob_client(name)
                return blob.download_blob().readall()
        except Exception:
            logger.exception("Failed to load artifact for URI: %s", uri)
        return None


storage_service = StorageService()
