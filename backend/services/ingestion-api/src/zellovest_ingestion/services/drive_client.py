"""Google Drive API client (Drive v3: changes, files, channels).

Thin REST wrapper used by the Drive ingestion endpoints for:
- ``changes.getStartPageToken`` (cursor init)
- ``changes.list`` (incremental pull sync; data-plane polling lives in the
  ``sync_drive_changes`` worker, watch setup uses this client at connect time)
- ``files.list`` (folder inspection)
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


class GoogleDriveError(RuntimeError):
    """Raised when the Drive API returns an error or is unreachable."""


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
        if resp.status_code != 200:
            logger.warning("drive_start_token_bad_status", status_code=resp.status_code)
            raise GoogleDriveError(f"Drive startPageToken failed: HTTP {resp.status_code}")
        try:
            token = resp.json().get("startPageToken", "")
        except ValueError as exc:
            raise GoogleDriveError("Drive startPageToken returned invalid JSON") from exc
        if not token:
            raise GoogleDriveError("Drive startPageToken response missing token")
        logger.info("drive_start_token_fetched")
        return str(token)

    def list_changes(
        self,
        page_token: str,
        page_size: int = 100,
        supports_all_drives: bool = True,
        include_removed: bool = True,
    ) -> tuple[list[dict], str | None]:
        """Pull one ``changes.list`` page.

        Args:
            page_token: Cursor from a previous call / stored checkpoint.
            page_size: Items per page (1-1000).

        Returns:
            Tuple of (change items, ``newStartPageToken`` or next ``pageToken``).

        Raises:
            GoogleDriveError: On transport or API errors. Callers should treat
                HTTP 410 (cursor expired) as a signal to re-seed with
                :meth:`get_start_page_token` and do a full re-list.
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
                    "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,time,file(id,name,mimeType,modifiedTime,size,parents,trashed))",
                },
            )
        except httpx.HTTPError as exc:
            logger.error("drive_changes_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive changes.list failed: {exc}") from exc
        if resp.status_code == 410:
            raise GoogleDriveError("Drive pageToken expired (HTTP 410); re-seed startPageToken")
        if resp.status_code != 200:
            raise GoogleDriveError(f"Drive changes.list failed: HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GoogleDriveError("Drive changes.list returned invalid JSON") from exc
        changes = payload.get("changes", [])
        new_token = payload.get("newStartPageToken") or payload.get("nextPageToken")
        return list(changes), (str(new_token) if new_token else None)

    def list_files(
        self,
        folder_id: str | None = None,
        page_size: int = 100,
        page_token: str | None = None,
        supports_all_drives: bool = True,
    ) -> tuple[list[dict], str | None]:
        """List files/folders (folder inspection).

        Args:
            folder_id: Drive folder id to list; ``None`` lists root-visible files.

        Returns:
            Tuple of (file dicts, next page token or None).
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
        if resp.status_code != 200:
            raise GoogleDriveError(f"Drive files.list failed: HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GoogleDriveError("Drive files.list returned invalid JSON") from exc
        return list(payload.get("files", [])), payload.get("nextPageToken")

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
        if resp.status_code != 200:
            raise GoogleDriveError(f"Drive changes.watch failed: HTTP {resp.status_code}")
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
                "https://www.googleapis.com/drive/v3/channels/stop",
                headers=self._headers(),
                json={"id": channel_id, "resourceId": resource_id},
            )
        except httpx.HTTPError as exc:
            logger.error("drive_stop_transport_error", error_class=type(exc).__name__)
            raise GoogleDriveError(f"Drive channels.stop failed: {exc}") from exc
        if resp.status_code not in (200, 204):
            raise GoogleDriveError(f"Drive channels.stop failed: HTTP {resp.status_code}")
        logger.info("drive_channel_stopped", channel_id=channel_id)
