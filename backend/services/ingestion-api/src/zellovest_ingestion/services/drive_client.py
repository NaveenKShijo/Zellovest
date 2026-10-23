"""Compatibility re-exports for the shared Google Drive client.

The implementation lives in :mod:`zellovest_shared.workers.drive_client`
so both the ingestion API and the workers (whose container only ships
``shared/`` and ``services/workers/``) use the same client.
"""

from zellovest_shared.workers.drive_client import (
    DriveAuthError,
    DriveCursorExpiredError,
    DriveTokenRefreshError,
    GoogleDriveClient,
    GoogleDriveError,
    refresh_drive_access_token,
    resolve_access_token,
)

__all__ = [
    "DriveAuthError",
    "DriveCursorExpiredError",
    "DriveTokenRefreshError",
    "GoogleDriveClient",
    "GoogleDriveError",
    "refresh_drive_access_token",
    "resolve_access_token",
]
