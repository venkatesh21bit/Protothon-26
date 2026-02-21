"""
Storage Service
Handles local filesystem storage for audio files (no cloud credentials required).
Falls back to in-memory storage if the upload directory cannot be created.
"""
import os
import uuid
import shutil
from pathlib import Path
from typing import Optional, Dict
import logging
from app.core.config import settings
from app.core.exceptions import StorageException

logger = logging.getLogger(__name__)


class LocalFileStorageService:
    """Storage service backed by the local filesystem.
    
    Stores uploaded audio inside STORAGE_PATH (default ./uploads).
    Works for local dev and Railway (mount a persistent volume at STORAGE_PATH).
    """

    def __init__(self):
        self.base_path = Path(settings.STORAGE_PATH).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Local file storage initialised at {self.base_path}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _full_path(self, object_key: str) -> Path:
        p = self.base_path / object_key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------
    # Public interface (mirrors the old S3StorageService API)
    # ------------------------------------------------------------------
    def generate_presigned_url(
        self,
        object_key: str,
        expiration: int = None,
        operation: str = "put_object",
    ) -> str:
        """Return a local upload marker (no real presigned URL needed for local storage)."""
        return f"LOCAL_UPLOAD:{object_key}"

    def generate_presigned_upload_url(
        self, patient_id: str, visit_id: str, file_extension: str = "webm"
    ) -> Dict[str, str]:
        object_key = f"audio/{patient_id}/{visit_id}/{uuid.uuid4()}.{file_extension}"
        return {"upload_url": f"LOCAL_UPLOAD:{object_key}", "object_key": object_key}

    def generate_presigned_download_url(
        self, object_key: str, expiration: int = None
    ) -> str:
        return f"LOCAL_DOWNLOAD:{object_key}"

    def upload_file(
        self, file_obj, object_key: str, content_type: str = "audio/webm"
    ) -> str:
        try:
            dest = self._full_path(object_key)
            with open(dest, "wb") as f:
                shutil.copyfileobj(file_obj, f)
            logger.info(f"Saved file locally: {dest}")
            return object_key
        except Exception as e:
            raise StorageException(
                message="Failed to save audio file locally",
                details={"object_key": object_key, "error": str(e)},
            )

    async def upload_audio(
        self,
        file_data: bytes,
        patient_id: str,
        visit_id: str,
        file_extension: str = "webm",
    ) -> str:
        object_key = f"audio/{patient_id}/{visit_id}/{uuid.uuid4()}.{file_extension}"
        dest = self._full_path(object_key)
        dest.write_bytes(file_data)
        logger.info(f"Saved audio locally: {dest} ({len(file_data)} bytes)")
        return object_key

    def download_file(self, object_key: str) -> bytes:
        dest = self._full_path(object_key)
        if not dest.exists():
            raise StorageException(
                message="File not found", details={"object_key": object_key}
            )
        return dest.read_bytes()

    async def download_audio(self, object_key: str) -> bytes:
        return self.download_file(object_key)

    def delete_file(self, object_key: str) -> bool:
        dest = self._full_path(object_key)
        if dest.exists():
            dest.unlink()
            logger.info(f"Deleted local file: {dest}")
            return True
        return False

    async def delete_audio(self, object_key: str) -> bool:
        return self.delete_file(object_key)

    def get_file_url(self, object_key: str) -> str:
        return f"LOCAL_FILE:{object_key}"


class InMemoryStorageService:
    """In-memory storage service for development without S3/LocalStack"""
    
    def __init__(self):
        self._files: Dict[str, bytes] = {}
        logger.info("Using in-memory storage (no S3 connection)")
    
    async def upload_audio(self, file_data: bytes, patient_id: str, visit_id: str, 
                          file_extension: str = "webm") -> str:
        """Store audio file in memory"""
        import uuid
        object_key = f"audio/{patient_id}/{visit_id}/{uuid.uuid4()}.{file_extension}"
        self._files[object_key] = file_data
        logger.info(f"Stored file in memory: {object_key} ({len(file_data)} bytes)")
        return object_key
    
    async def download_audio(self, object_key: str) -> bytes:
        """Retrieve audio file from memory"""
        if object_key in self._files:
            return self._files[object_key]
        raise StorageException(message="File not found", details={"object_key": object_key})
    
    def generate_presigned_upload_url(self, patient_id: str, visit_id: str, 
                                      file_extension: str = "webm") -> Dict[str, str]:
        """Generate mock upload URL for demo mode"""
        import uuid
        object_key = f"audio/{patient_id}/{visit_id}/{uuid.uuid4()}.{file_extension}"
        return {
            "upload_url": f"MOCK_UPLOAD:{object_key}",
            "object_key": object_key
        }
    
    def generate_presigned_url(self, object_key: str, expiration: int = None, operation: str = 'put_object') -> str:
        """Generate mock presigned URL for development - compatible with S3StorageService interface"""
        # For deployed environments, we'll skip the actual upload and just simulate it
        # The URL will be to our own mock endpoint
        # We use a special marker that the frontend will detect
        return f"MOCK_UPLOAD:{object_key}"
    
    def generate_presigned_download_url(self, object_key: str, expiration: int = None) -> str:
        """Generate mock download URL"""
        return f"MOCK_DOWNLOAD:{object_key}"
    
    async def delete_audio(self, object_key: str) -> bool:
        """Delete file from memory"""
        if object_key in self._files:
            del self._files[object_key]
            return True
        return False
    
    def get_file_url(self, object_key: str) -> str:
        """Get mock file URL - returns marker for demo mode"""
        return f"MOCK_FILE:{object_key}"


# Union type for both storage services
StorageService = LocalFileStorageService | InMemoryStorageService

# Lazy-initialized global instance
_storage_service: Optional[StorageService] = None

def get_storage_service() -> StorageService:
    """Get or create the storage service (lazy initialization)"""
    global _storage_service
    if _storage_service is None:
        try:
            _storage_service = LocalFileStorageService()
        except Exception as e:
            logger.warning(f"Could not init local storage: {e}. Using in-memory storage.")
            _storage_service = InMemoryStorageService()
    return _storage_service

# Lazy wrapper for backwards compatibility
class LazyStorageService:
    """Lazy wrapper that defers service creation until first use"""
    _instance: Optional[StorageService] = None

    def __getattr__(self, name):
        if LazyStorageService._instance is None:
            try:
                LazyStorageService._instance = LocalFileStorageService()
            except Exception as e:
                logger.warning(f"Could not init local storage: {e}. Using in-memory storage.")
                LazyStorageService._instance = InMemoryStorageService()
        return getattr(LazyStorageService._instance, name)

storage_service = LazyStorageService()
