from __future__ import annotations

import logging
import re
from typing import Any

from .api_client import APIClient
from .backup import BackupManager
from .config import Config
from .notifier import Notifier

logger = logging.getLogger(__name__)

# Tracks accounts we have disabled so we know which ones to check for re-enabling.
_disabled_accounts: set[str] = set()


def _parse_quota_percent(entry: dict[str, Any]) -> float | None:
    """Extract quota usage percentage from an auth-file entry.

    The status_message field typically contains text like:
        "Quota: 45% remaining"  /  "85% used"  /  "quota_remaining: 30"
    We attempt several heuristic patterns; return *remaining* percentage.
    """
    status_msg: str = entry.get("status_message", "") or ""
    status: str = entry.get("status", "") or ""

    # Pattern: "XX% remaining"
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*remaining", status_msg, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # Pattern: "XX% used" → remaining = 100 - used
    m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", status_msg, re.IGNORECASE)
    if m:
        return 100.0 - float(m.group(1))

    # Pattern: "quota_remaining: XX"
    m = re.search(r"quota_remaining\s*:\s*(\d+(?:\.\d+)?)", status_msg, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # Pattern: "remaining: XX%"
    m = re.search(r"remaining\s*:\s*(\d+(?:\.\d+)?)\s*%?", status_msg, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # Generic: any standalone percentage in the message (treat as remaining)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", status_msg)
    if m:
        return float(m.group(1))

    # If status itself indicates exhaustion
    if status.lower() in ("exhausted", "rate_limited", "quota_exceeded"):
        return 0.0

    return None


def _matches_provider_filter(entry: dict[str, Any], filters: list[str]) -> bool:
    if not filters:
        return True
    name: str = entry.get("name", "").lower()
    provider: str = entry.get("provider", "").lower()
    return any(f.lower() in name or f.lower() in provider for f in filters)


async def check_and_act(
    cfg: Config,
    api: APIClient,
    backup: BackupManager,
    notifier: Notifier,
) -> None:
    """Run one monitoring cycle: check quotas, disable/enable as needed."""
    try:
        entries = await api.list_auth_files()
    except Exception:
        logger.exception("Failed to fetch auth files list")
        return

    logger.info("Polled %d auth file(s)", len(entries))

    active_names = {e.get("name", "") for e in entries}

    for entry in entries:
        name: str = entry.get("name", "")
        if not name:
            continue

        if not _matches_provider_filter(entry, cfg.provider_filter):
            continue

        quota = _parse_quota_percent(entry)
        if quota is None:
            logger.debug("Could not determine quota for %s, skipping", name)
            continue

        logger.info("Account %s: %.1f%% quota remaining", name, quota)

        if quota < cfg.quota_threshold:
            await _disable_account(cfg, api, backup, notifier, name, quota)

    # Check previously disabled accounts for re-enabling
    for name in list(_disabled_accounts):
        if name in active_names:
            # Still active (shouldn't happen if we deleted it), skip
            continue
        await _try_reenable(cfg, api, backup, notifier, name)


async def _disable_account(
    cfg: Config,
    api: APIClient,
    backup: BackupManager,
    notifier: Notifier,
    name: str,
    quota: float,
) -> None:
    if name in _disabled_accounts:
        logger.debug("Account %s already disabled, skipping", name)
        return

    msg = f"Account {name} quota at {quota:.1f}% (threshold {cfg.quota_threshold}%), disabling"
    logger.warning(msg)

    if cfg.dry_run:
        logger.info("[DRY RUN] Would disable %s", name)
        await notifier.send("DRY RUN: Quota Low", msg, level="warning")
        return

    # Backup credentials before deleting
    try:
        content = await api.download_auth_file(name)
        backup.save(name, content)
    except Exception:
        logger.exception("Failed to backup %s, aborting disable", name)
        return

    try:
        await api.delete_auth_file(name)
        _disabled_accounts.add(name)
        await notifier.send("Account Disabled", msg, level="warning")
    except Exception:
        logger.exception("Failed to delete auth file %s", name)


async def _try_reenable(
    cfg: Config,
    api: APIClient,
    backup: BackupManager,
    notifier: Notifier,
    name: str,
) -> None:
    """Re-enable a previously disabled account by re-uploading its backup.

    Since the account is deleted, we cannot check its quota via the API.
    The strategy: periodically attempt to re-upload and immediately check the
    new entry's quota. If still below threshold, disable again.
    For simplicity, we re-upload unconditionally and let the next cycle decide.

    A more conservative approach: only re-enable after a cooldown period.
    Current implementation: always try to re-enable; if quota is still low,
    the next poll cycle will disable it again.
    """
    if not backup.exists(name):
        logger.warning("No backup for %s, cannot re-enable", name)
        _disabled_accounts.discard(name)
        return

    msg = f"Attempting to re-enable account {name}"
    logger.info(msg)

    if cfg.dry_run:
        logger.info("[DRY RUN] Would re-enable %s", name)
        return

    content = backup.load(name)
    if content is None:
        _disabled_accounts.discard(name)
        return

    try:
        await api.upload_auth_file(name, content)
        _disabled_accounts.discard(name)
        backup.remove(name)
        await notifier.send("Account Re-enabled", msg, level="info")
        logger.info("Successfully re-enabled %s", name)
    except Exception:
        logger.exception("Failed to re-enable %s", name)
