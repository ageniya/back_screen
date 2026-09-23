"""Read-only client used by the Pico-side unified back-screen service."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class RemoteRobotClient:
    """Fetch Orin's already-normalized API without controlling it."""

    def __init__(self) -> None:
        self.base_url = os.getenv("ORIN_API_BASE", "").strip().rstrip("/")
        self.root_url = self.base_url[:-7] if self.base_url.endswith("/api/v1") else self.base_url
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _fetch_sync(self, path: str, root: bool = False) -> dict[str, Any] | None:
        if not self.base_url:
            return None
        try:
            prefix = self.root_url if root else self.base_url
            request = Request(f"{prefix}{path}", headers={"Accept": "application/json"})
            with urlopen(request, timeout=1.5) as response:  # nosec B310 - deployment-configured robot LAN URL
                payload = json.loads(response.read().decode("utf-8"))
            self.last_error = None
            return payload if isinstance(payload, dict) else None
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = str(exc)
            return None

    async def fetch(self, path: str) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        # Python 3.8 on some robot images has no asyncio.to_thread.
        return await loop.run_in_executor(None, self._fetch_sync, path)

    async def fetch_root(self, path: str) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_sync, path, True)
