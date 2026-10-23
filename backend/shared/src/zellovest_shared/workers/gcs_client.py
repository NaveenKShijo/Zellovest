"""GCS client for direct-to-GCS manual uploads (sign + verify + fetch).

Wraps ``google-cloud-storage`` behind testable ``Protocol``s so the
Ingress API router and workers stay unit-testable without real GCP
credentials.

Flow:
    POST /uploads/init -> get_gcs_signer() -> generate_upload_url()
    -> frontend PUTs bytes directly to GCS
    -> POST /uploads/{id}/complete -> get_gcs_reader() -> get_object_info()
    -> stage_document_task -> download_bytes() -> triage/classify.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

from zellovest_shared.logging_conf import get_logger
from zellovest_shared.workers.gcs_writer import make_storage_client

logger = get_logger(__name__)


class StorageNotConfiguredError(RuntimeError):
    """Raised when GCS bucket/project settings are missing."""


class GcsSigningError(RuntimeError):
    """Raised when the GCS client fails to mint a signed URL."""


class GcsReadError(RuntimeError):
    """Raised when a GCS object cannot be read or deleted."""


@dataclass
class BlobInfo:
    """Observed GCS object metadata (None means the object is absent)."""

    size: int
    content_type: str
    updated_at: datetime | None = None


class GcsSigner(Protocol):
    """Test seam for GCS V4 PUT signing."""

    def generate_upload_url(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        expires_secs: int,
    ) -> tuple[str, datetime]:
        """Mint a V4 PUT signed URL for one object key.

        Args:
            bucket: GCS bucket name (tenant-isolated per deployment).
            key: Object key, e.g. ``raw/{tenant}/{type}/{uuid}/{file}``.
            content_type: MIME pinned into the signature (GCS enforces it).
            expires_secs: URL lifetime in seconds (must be positive).

        Returns:
            Tuple of (signed_url, expires_at_utc).
        """
        ...


class GcsStorageSigner:
    """Real signer backed by ``google-cloud-storage``.

    Attributes:
        project: GCP project id (``GOOGLE_CLOUD_PROJECT``).
    """

    def __init__(self, project: str = "") -> None:
        """Store project id; storage client is created lazily per call.

        Args:
            project: GCP project id, empty string uses default credentials.
        """
        self._project = project

    def generate_upload_url(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        expires_secs: int,
    ) -> tuple[str, datetime]:
        """Generate a V4 PUT signed URL with pinned content type.

        Args:
            bucket: GCS bucket name.
            key: Destination object key.
            content_type: MIME type enforced by GCS on PUT.
            expires_secs: Signed URL lifetime in seconds.

        Returns:
            Tuple of (signed_url, expires_at_utc).

        Raises:
            StorageNotConfiguredError: If bucket is empty.
            ValueError: If expires_secs is not positive.
            GcsSigningError: If signing fails or dependency is missing.
        """
        if not bucket:
            raise StorageNotConfiguredError("GCS_RAW_BUCKET is not configured")
        if expires_secs <= 0:
            raise ValueError("expires_secs must be positive")

        try:
            # Lazy import: keeps unit tests credential-free.
            from google.cloud import storage
        except ImportError as exc:
            raise GcsSigningError(
                "google-cloud-storage is not installed; add it to ingestion-api dependencies"
            ) from exc

        try:
            client = make_storage_client(self._project or None)
            blob = client.bucket(bucket).blob(key)
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_secs)
            url = blob.generate_signed_url(
                version="v4",
                method="PUT",
                content_type=content_type,
                expiration=expires_at,
            )
        except (StorageNotConfiguredError, ValueError):
            raise
        except Exception as exc:
            logger.error(
                "gcs_sign_failed",
                bucket=bucket,
                key=key,
                error_class=type(exc).__name__,
            )
            raise GcsSigningError(f"failed to sign GCS URL for key={key!r}") from exc

        logger.info(
            "gcs_sign_issued",
            bucket=bucket,
            key=key,
            expires_secs=expires_secs,
        )
        return url, expires_at


class FakeGcsSigner:
    """Deterministic fake for unit tests (no network, no credentials)."""

    def __init__(self, base_url: str = "https://fake-gcs.local") -> None:
        """Store fake URL prefix used in assertions.

        Args:
            base_url: Prefix for generated fake URLs.
        """
        self._base_url = base_url.rstrip("/")

    def generate_upload_url(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str,
        expires_secs: int,
    ) -> tuple[str, datetime]:
        """Return a predictable fake URL embedding bucket and key.

        Args:
            bucket: Fake bucket name echoed into the URL.
            key: Fake object key echoed into the URL.
            content_type: Ignored (fake does not enforce content-type).
            expires_secs: Lifetime echoed as ``exp`` query param.

        Returns:
            Tuple of (fake_url, expires_at_utc).
        """
        del content_type  # fake does not enforce content-type
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_secs)
        url = f"{self._base_url}/{bucket}/{quote(key, safe='/')}?sig=test&exp={expires_secs}"
        return url, expires_at


def get_gcs_signer(project: str = "", *, use_fake: bool = False) -> GcsSigner:
    """Create a GCS signer implementation.

    Args:
        project: GCP project id for the real signer.
        use_fake: Return :class:`FakeGcsSigner` when True (tests/local).

    Returns:
        A :class:`GcsSigner` implementation.
    """
    if use_fake:
        return FakeGcsSigner()
    return GcsStorageSigner(project=project)


class GcsObjectReader(Protocol):
    """Test seam for GCS object verification, fetch, and cleanup."""

    def get_object_info(self, *, bucket: str, key: str) -> BlobInfo | None:
        """Return object metadata, or None when the object is absent.

        Args:
            bucket: GCS bucket name.
            key: Object key.

        Returns:
            BlobInfo, or None if the blob does not exist.
        """
        ...

    def download_bytes(self, *, bucket: str, key: str) -> bytes | None:
        """Download full object bytes, or None when the object is absent.

        Args:
            bucket: GCS bucket name.
            key: Object key.

        Returns:
            Object bytes, or None if the blob does not exist.
        """
        ...

    def delete_object(self, *, bucket: str, key: str) -> bool:
        """Best-effort object delete.

        Args:
            bucket: GCS bucket name.
            key: Object key.

        Returns:
            True when an object was deleted, False when absent.
        """
        ...


class FakeGcsBucket:
    """Shared in-memory blob store backing the fake signer/reader.

    Tests PUT bytes here to simulate the browser→GCS upload; the fake
    reader then observes them exactly like ``complete`` would in prod.
    State is class-level so separately constructed fakes share one view.
    """

    _blobs: dict[tuple[str, str], dict] = {}

    @classmethod
    def put(
        cls, bucket: str, key: str, data: bytes, content_type: str = "application/pdf"
    ) -> None:
        """Store blob bytes as if a browser PUT succeeded.

        Args:
            bucket: Fake bucket name.
            key: Fake object key.
            data: Blob bytes.
            content_type: Stored content type.
        """
        cls._blobs[(bucket, key)] = {"data": data, "content_type": content_type}

    @classmethod
    def clear(cls) -> None:
        """Drop all stored blobs (test isolation)."""
        cls._blobs.clear()


class FakeGcsReader:
    """In-memory reader over :class:`FakeGcsBucket` (no network)."""

    def get_object_info(self, *, bucket: str, key: str) -> BlobInfo | None:
        """Return fake metadata, or None when nothing was PUT."""
        blob = FakeGcsBucket._blobs.get((bucket, key))
        if blob is None:
            return None
        return BlobInfo(size=len(blob["data"]), content_type=blob["content_type"])

    def download_bytes(self, *, bucket: str, key: str) -> bytes | None:
        """Return stored fake bytes, or None when absent."""
        blob = FakeGcsBucket._blobs.get((bucket, key))
        return blob["data"] if blob is not None else None

    def delete_object(self, *, bucket: str, key: str) -> bool:
        """Remove a fake blob; False when absent."""
        return FakeGcsBucket._blobs.pop((bucket, key), None) is not None


class GcsStorageReader:
    """Real reader backed by ``google-cloud-storage``."""

    def __init__(self, project: str = "") -> None:
        """Store project id; storage client is created lazily per call.

        Args:
            project: GCP project id, empty string uses default credentials.
        """
        self._project = project

    def _blob(self, bucket: str, key: str):  # type: ignore[no-untyped-def]
        """Return a Blob handle (lazy import keeps tests credential-free)."""
        client = make_storage_client(self._project or None)
        return client.bucket(bucket).blob(key)

    def get_object_info(self, *, bucket: str, key: str) -> BlobInfo | None:
        """Reload blob metadata; None when the object does not exist."""
        if not bucket:
            raise StorageNotConfiguredError("GCS_RAW_BUCKET is not configured")
        try:
            blob = self._blob(bucket, key)
            blob.reload()
        except Exception as exc:
            if type(exc).__name__ == "NotFound":
                return None
            logger.error(
                "gcs_stat_failed", bucket=bucket, key=key, error_class=type(exc).__name__
            )
            raise GcsReadError(f"failed to stat GCS object {key!r}") from exc
        return BlobInfo(
            size=blob.size or 0,
            content_type=blob.content_type or "application/octet-stream",
            updated_at=blob.updated,
        )

    def download_bytes(self, *, bucket: str, key: str) -> bytes | None:
        """Download blob bytes; None when the object does not exist."""
        if not bucket:
            raise StorageNotConfiguredError("GCS_RAW_BUCKET is not configured")
        try:
            return bytes(self._blob(bucket, key).download_as_bytes())
        except Exception as exc:
            if type(exc).__name__ == "NotFound":
                return None
            logger.error(
                "gcs_download_failed",
                bucket=bucket,
                key=key,
                error_class=type(exc).__name__,
            )
            raise GcsReadError(f"failed to download GCS object {key!r}") from exc

    def delete_object(self, *, bucket: str, key: str) -> bool:
        """Delete the blob; False when already absent (best-effort)."""
        if not bucket:
            raise StorageNotConfiguredError("GCS_RAW_BUCKET is not configured")
        try:
            self._blob(bucket, key).delete()
        except Exception as exc:
            if type(exc).__name__ == "NotFound":
                return False
            logger.error(
                "gcs_delete_failed",
                bucket=bucket,
                key=key,
                error_class=type(exc).__name__,
            )
            raise GcsReadError(f"failed to delete GCS object {key!r}") from exc
        return True


def get_gcs_reader(project: str = "", *, use_fake: bool = False) -> GcsObjectReader:
    """Create a GCS object-reader implementation.

    Args:
        project: GCP project id for the real reader.
        use_fake: Return :class:`FakeGcsReader` when True (tests/local).

    Returns:
        A :class:`GcsObjectReader` implementation.
    """
    if use_fake:
        return FakeGcsReader()
    return GcsStorageReader(project=project)

def make_storage_client(project: str | None, credentials_path: str | None):
    from google.cloud import storage
    from google.oauth2 import service_account

    if credentials_path:
        creds = service_account.Credentials.from_service_account_file(credentials_path)
        return storage.Client(project=project, credentials=creds)
    return storage.Client(project=project)
