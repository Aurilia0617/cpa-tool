from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


class Notifier:
    """Send webhook notifications for quota events."""

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url
        self._enabled = bool(webhook_url)

    async def send(self, title: str, message: str, level: str = "info") -> None:
        if not self._enabled:
            return
        payload = {
            "title": title,
            "message": message,
            "level": level,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._url, json=payload)
                resp.raise_for_status()
                logger.debug("Webhook sent: %s", title)
        except Exception:
            logger.exception("Failed to send webhook notification")
