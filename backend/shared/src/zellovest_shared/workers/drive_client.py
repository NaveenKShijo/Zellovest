"""Google Drive API client (Drive v3: changes, files, channels).

Thin REST wrapper shared by the ingestion API (OAuth watch setup) and the
ingestion worker (``sync_drive_changes`` pull sync):

- ``changes.getStartPageToken`` (cursor init)
- ``changes.list`` (incremental pull sync)
- ``files.list`` (full backfill)
- ``files.get?alt=media`` (copy bytes into the GCS bronze lake)
- ``changes.watch`` (push notifications) / ``channels.stop`` (teardown)

Network calls use ``httpx`` with a bearer access token. All methods are
intentionally small and mockable in unit tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import httpx

from zellovest_shared.logging_conf import get_logger

logger = get_logger(__name__)

_DRIVE_BASE = "https://www.googleapis.com/drive/v3"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleDriveError(RuntimeError):
    """Raised when the Drive API returns an error or is unreachable."""


class DriveCursorExpiredError(GoogleDriveError):
    """Raised when a ``changes.list`` pageToken has expired (HTTP 410)."""


class DriveAuthError(GoogleDriveError):
    """Raised when Google rejects the stored OAuth access token (HTTP 401)."""


class DriveTokenRefreshError(RuntimeError):
    """Raised when Google's OAuth token endpoint rejects a refresh grant."""


def resolve_access_token(credentials: dict | object | None) -> str:
    """Extract a bearer token from stored credentials.

    Args:
        credentials: Token mapping, credentials model, or None.

    Returns:
        Access token string (may be empty when only a refresh token is
        configured; callers refresh upstream).
    """
    if credentials is None:
        return ""
    if hasattr(credentials, "model_dump"):
        data = credentials.model_dump()  # type: ignore[union-attr]
    elif isinstance(credentials, dict):
        data = credentials
    else:
        return ""
    token = data.get("access_token") or ""
    return str(token)


def refresh_drive_access_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    *,
    timeout_seconds: float = 15.0,
) -> dict:
    """Exchange a Google refresh token for a fresh access token.

    Args:
        token_url: Google OAuth token endpoint.
        client_id: OAuth client id.
        client_secret: OAuth client secret (never logged).
        refresh_token: Stored offline refresh token.
        timeout_seconds: HTTP timeout bound.

    Returns:
        Token payload with ``access_token`` and ``expires_in`` (and possibly
        a rotated ``refresh_token``).

    Raises:
        DriveTokenRefreshError: When the endpoint is unreachable or rejects
            the grant (the tenant must reconnect).
    """
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                token_url or _GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.warning("drive_token_refresh_transport_error", error_class=type(exc).__name__)
        raise DriveTokenRefreshError("Google token endpoint unreachable") from exc

    if response.status_code != 200:
        logger.warning(
            "drive_token_refresh_rejected",
            status_code=response.status_code,
            response_body=response.text[:500],
        )
        raise DriveTokenRefreshError(
            f"Google token endpoint returned {response.status_code}: {response.text[:200]}"
        )
    try:
        body = response.json()
        if not body.get("access_token"):
            raise ValueError("missing access_token")
    except (ValueError, TypeError) as exc:
        raise DriveTokenRefreshError(f"malformed token response: {exc}") from exc
    return dict(body)


@dataclass
class GoogleDriveClient:
    """Minimal Drive v3 client for ingestion sync/watch."""

    access_token: str = ""
    timeout_seconds: float = 15.0
    _http: httpx.Client | None = field(default=None, repr=False)

    def _headers(self) -> dict[str, str]:
        """Build auth headers."""
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _client(self) -> httpx.Client:
        """Return a (lazily created) sync httpx client."""
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout_seconds)
        return self._http

    def close(self) -> None:
        """Close the underlying HTTP connection pool (idempotent)."""
        if self._http is not None:
            self._http.close()
            self._http = None

    def _raise_for_status(self, response: httpx.Response, operation: str) -> None:
        """Translate Drive HTTP failures into typed client exceptions.

        Args:
            response: Drive API response.
            operation: Human-readable operation for error messages.

        Raises:
            DriveAuthError: On HTTP 401 (reconnect required).
            DriveCursorExpiredError: On HTTP 410 (changes cursor expired).
            GoogleDriveError: On any other non-200 response.
        """
        if response.status_code == 401:
            logger.warning("drive_auth_rejected", operation=operation)
            raise DriveAuthError(f"Drive {operation} failed: HTTP 401")
        if response.status_code == 410:
            logger.warning("drive_cursor_expired", operation=operation)
            raise DriveCursorExpiredError(
                "Drive pageToken expired (HTTP 410); re-seed startPageToken"
            )
        if response.status_code != 200:
            raise GoogleDriveError(f"Drive {operation} failed: HTTP {response.status_code}")

    def get_start_page_token(self, supports_all_drives: bool = True) -> str:
        """Fetch the initial ``startPageToken`` for incremental sync.

        Raises:
            GoogleDriveError: On transport or API errors.
        """
        try:
            resp = self._client().get(
                f"{_DRIVE_BASE}/changes/startPageToken",
                headers=self._headers(),
                params={"supportsAllDrives": str(supports_all_drives).lower()},
            )
        except httpx.HTTPError as exc:
            logger.error("drive_start_token_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive startPageToken request failed: {exc}") from exc
        self._raise_for_status(resp, "startPageToken")
        try:
            token = resp.json().get("startPageToken", "")
        except ValueError as exc:
            raise GoogleDriveError("Drive startPageToken returned invalid JSON") from exc
        if not token:
            raise GoogleDriveError("Drive startPageToken response missing token")
        logger.info("drive_start_token_fetched")
        return str(token)

    def list_changes_page(
        self,
        page_token: str,
        page_size: int = 100,
        supports_all_drives: bool = True,
        include_removed: bool = True,
    ) -> tuple[list[dict], str | None, str | None]:
        """Pull one ``changes.list`` page.

        Args:
            page_token: Cursor from a previous call / stored checkpoint.
            page_size: Items per page (1-1000).
            supports_all_drives: Include shared drives.
            include_removed: Include removal tombstones.

        Returns:
            Tuple of (changes, ``nextPageToken``, ``newStartPageToken``).

        Raises:
            DriveCursorExpiredError: When Google expires the cursor (HTTP 410).
            GoogleDriveError: On transport or API errors.
        """
        try:
            resp = self._client().get(
                f"{_DRIVE_BASE}/changes",
                headers=self._headers(),
                params={
                    "pageToken": page_token,
                    "pageSize": min(max(page_size, 1), 1000),
                    "supportsAllDrives": str(supports_all_drives).lower(),
                    "includeItemsFromAllDrives": str(supports_all_drives).lower(),
                    "includeRemoved": str(include_removed).lower(),
                    "fields": (
                        "nextPageToken,newStartPageToken,"
                        "changes(fileId,removed,time,file(id,name,mimeType,modifiedTime,"
                        "size,parents,trashed))"
                    ),
                },
            )
        except httpx.HTTPError as exc:
            logger.error("drive_changes_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive changes.list failed: {exc}") from exc
        self._raise_for_status(resp, "changes.list")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GoogleDriveError("Drive changes.list returned invalid JSON") from exc
        changes = list(payload.get("changes", []))
        next_page = payload.get("nextPageToken")
        new_start = payload.get("newStartPageToken")
        return changes, (str(next_page) if next_page else None), (
            str(new_start) if new_start else None
        )

    def list_changes(
        self,
        page_token: str,
        page_size: int = 100,
        supports_all_drives: bool = True,
        include_removed: bool = True,
    ) -> tuple[list[dict], str | None]:
        """Pull one ``changes.list`` page (backward-compatible helper).

        Returns:
            Tuple of (change items, next page/new-start token or None).

        Raises:
            GoogleDriveError: On transport or API errors.
        """
        changes, next_page, new_start = self.list_changes_page(
            page_token,
            page_size=page_size,
            supports_all_drives=supports_all_drives,
            include_removed=include_removed,
        )
        return changes, next_page or new_start

    def list_files(
        self,
        folder_id: str | None = None,
        page_size: int = 100,
        page_token: str | None = None,
        supports_all_drives: bool = True,
    ) -> tuple[list[dict], str | None]:
        """List files/folders for a full backfill.

        Args:
            folder_id: Drive folder id to list; ``None`` lists all files.
            page_size: Items per page (1-1000).
            page_token: Opaque page token from a prior call.
            supports_all_drives: Include shared drives.

        Returns:
            Tuple of (file dicts, next page token or None).

        Raises:
            GoogleDriveError: On transport or API errors.
        """
        query_parts = ["trashed = false"]
        if folder_id:
            query_parts.append(f"'{folder_id}' in parents")
        try:
            params: dict[str, str | int] = {
                "q": " and ".join(query_parts),
                "pageSize": min(max(page_size, 1), 1000),
                "supportsAllDrives": str(supports_all_drives).lower(),
                "includeItemsFromAllDrives": str(supports_all_drives).lower(),
                "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size,parents)",
                "orderBy": "folder,name",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = self._client().get(
                f"{_DRIVE_BASE}/files", headers=self._headers(), params=params
            )
        except httpx.HTTPError as exc:
            logger.error("drive_files_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive files.list failed: {exc}") from exc
        self._raise_for_status(resp, "files.list")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GoogleDriveError("Drive files.list returned invalid JSON") from exc
        return list(payload.get("files", [])), payload.get("nextPageToken")

    def download_file(self, file_id: str, supports_all_drives: bool = True) -> bytes:
        """Download one file's bytes via ``files.get?alt=media``.

        Args:
            file_id: Drive file id.
            supports_all_drives: Include shared drives.

        Returns:
            Raw file bytes.

        Raises:
            GoogleDriveError: On transport or API errors.
        """
        try:
            resp = self._client().get(
                f"{_DRIVE_BASE}/files/{file_id}",
                headers=self._headers(),
                params={
                    "alt": "media",
                    "supportsAllDrives": str(supports_all_drives).lower(),
                },
            )
        except httpx.HTTPError as exc:
            logger.error("drive_download_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive files.get failed: {exc}") from exc
        self._raise_for_status(resp, "files.get")
        return resp.content

    def watch_changes(
        self,
        channel_id: str | None,
        webhook_url: str,
        page_token: str,
        token: str | None = None,
        supports_all_drives: bool = True,
    ) -> dict:
        """Create a ``changes.watch`` push channel.

        Returns:
            Dict with ``id``, ``resourceId`` and ``expiration``.
        """
        body = {
            "id": channel_id or uuid.uuid4().hex,
            "type": "web_hook",
            "address": webhook_url,
        }
        if token:
            body["token"] = token
        try:
            resp = self._client().post(
                f"{_DRIVE_BASE}/changes/watch",
                headers=self._headers(),
                params={
                    "pageToken": page_token,
                    "supportsAllDrives": str(supports_all_drives).lower(),
                    "includeItemsFromAllDrives": str(supports_all_drives).lower(),
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            logger.error("drive_watch_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive changes.watch failed: {exc}") from exc
        self._raise_for_status(resp, "changes.watch")
        try:
            return dict(resp.json())
        except ValueError as exc:
            raise GoogleDriveError("Drive changes.watch returned invalid JSON") from exc

    def stop_channel(self, channel_id: str, resource_id: str) -> None:
        """Tear down a push channel via ``channels.stop``.

        Raises:
            GoogleDriveError: On transport or API errors.
        """
        try:
            resp = self._client().post(
                f"{_DRIVE_BASE}/channels/stop",
                headers=self._headers(),
                json={"id": channel_id, "resourceId": resource_id},
            )
        except httpx.HTTPError as exc:
            logger.error("drive_stop_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive channels.stop failed: {exc}") from exc
        if resp.status_code not in (200, 204):
            raise GoogleDriveError(f"Drive channels.stop failed: HTTP {resp.status_code}")
        logger.info("drive_channel_stopped", channel_id=channel_id)
