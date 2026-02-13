from __future__ import annotations

import logging
import re
from typing import Any

from .api_client import APIClient
from .config import Config
from .notifier import Notifier

logger = logging.getLogger(__name__)

# Tracks accounts we have disabled so we can detect recovery.
_disabled_by_us: set[str] = set()

# Keywords in status / status_message that indicate quota exhaustion.
_EXHAUSTED_KEYWORDS = (
    "exhausted",
    "rate_limit",
    "rate limit",
    "quota_exceeded",
    "quota exceeded",
    "out of credits",
    "limit reached",
    "capacity",
)


def _is_quota_exhausted(entry: dict[str, Any]) -> bool:
    """Determine if an auth entry's quota is exhausted.

    Uses multiple signals from the API response:
    - unavailable == true
    - status contains exhaustion-related keywords
    - status_message contains exhaustion-related keywords or percentage hints
    """
    # Direct unavailable flag
    if entry.get("unavailable", False):
        return True

    status: str = (entry.get("status", "") or "").lower()
    status_msg: str = (entry.get("status_message", "") or "").lower()

    # Check keywords in status
    for kw in _EXHAUSTED_KEYWORDS:
        if kw in status or kw in status_msg:
            return True

    # Heuristic: percentage in status_message indicating low remaining quota
    # e.g. "0% remaining", "remaining: 0%", "100% used"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*remaining", status_msg)
    if m and float(m.group(1)) == 0:
        return True

    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", status_msg)
    if m and float(m.group(1)) >= 100:
        return True

    return False


def _matches_provider_filter(entry: dict[str, Any], filters: list[str]) -> bool:
    if not filters:
        return True
    name: str = entry.get("name", "").lower()
    provider: str = (entry.get("provider", "") or entry.get("type", "") or "").lower()
    return any(f.lower() in name or f.lower() in provider for f in filters)


async def check_and_act(
    cfg: Config,
    api: APIClient,
    notifier: Notifier,
) -> None:
    """Run one monitoring cycle: check auth file statuses, disable/enable as needed."""
    try:
        entries = await api.list_auth_files()
    except Exception:
        logger.exception("Failed to fetch auth files list")
        return

    logger.info("Polled %d auth file(s)", len(entries))

    for entry in entries:
        name: str = entry.get("name", "")
        if not name:
            continue

        if not _matches_provider_filter(entry, cfg.provider_filter):
            continue

        already_disabled: bool = entry.get("disabled", False)
        exhausted = _is_quota_exhausted(entry)

        status = entry.get("status", "")
        status_msg = entry.get("status_message", "")
        logger.info(
            "Account %s: disabled=%s, unavailable=%s, status=%s, status_message=%s",
            name, already_disabled, entry.get("unavailable", False), status, status_msg,
        )

        if exhausted and not already_disabled:
            # Quota exhausted and account still enabled → disable it
            await _disable_account(cfg, api, notifier, name, status_msg)
        elif not exhausted and already_disabled and name in _disabled_by_us:
            # Quota recovered and we were the ones who disabled it → re-enable
            await _enable_account(cfg, api, notifier, name)


async def _disable_account(
    cfg: Config,
    api: APIClient,
    notifier: Notifier,
    name: str,
    reason: str,
) -> None:
    msg = f"Account {name} quota exhausted ({reason}), disabling"
    logger.warning(msg)

    if cfg.dry_run:
        logger.info("[DRY RUN] Would disable %s", name)
        await notifier.send("DRY RUN: Quota Exhausted", msg, level="warning")
        return

    try:
        await api.set_auth_file_status(name, disabled=True)
        _disabled_by_us.add(name)
        await notifier.send("Account Disabled", msg, level="warning")
    except Exception:
        logger.exception("Failed to disable auth file %s", name)


async def _enable_account(
    cfg: Config,
    api: APIClient,
    notifier: Notifier,
    name: str,
) -> None:
    msg = f"Account {name} quota recovered, re-enabling"
    logger.info(msg)

    if cfg.dry_run:
        logger.info("[DRY RUN] Would re-enable %s", name)
        await notifier.send("DRY RUN: Quota Recovered", msg, level="info")
        return

    try:
        await api.set_auth_file_status(name, disabled=False)
        _disabled_by_us.discard(name)
        await notifier.send("Account Re-enabled", msg, level="info")
    except Exception:
        logger.exception("Failed to re-enable auth file %s", name)
