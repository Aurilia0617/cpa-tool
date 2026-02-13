from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupManager:
    """Manage credential backups on the local filesystem."""

    def __init__(self, backup_dir: str) -> None:
        self._dir = Path(backup_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, name: str) -> Path:
        return self._dir / name

    def save(self, name: str, content: bytes) -> None:
        dest = self._path_for(name)
        dest.write_bytes(content)
        logger.info("Backup saved: %s", dest)

    def load(self, name: str) -> bytes | None:
        src = self._path_for(name)
        if not src.exists():
            logger.warning("No backup found for %s", name)
            return None
        return src.read_bytes()

    def exists(self, name: str) -> bool:
        return self._path_for(name).exists()

    def remove(self, name: str) -> None:
        p = self._path_for(name)
        if p.exists():
            p.unlink()
            logger.info("Backup removed: %s", p)
