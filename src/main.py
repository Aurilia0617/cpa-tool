from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .api_client import APIClient
from .backup import BackupManager
from .config import Config
from .monitor import check_and_act
from .notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cpa-tool")


async def run(cfg: Config) -> None:
    api = APIClient(cfg.base_url, cfg.management_key)
    backup = BackupManager(cfg.backup_dir)
    notifier = Notifier(cfg.webhook_url)

    stop = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info(
        "CPA-Tool started — polling every %ds, threshold %d%%, dry_run=%s",
        cfg.poll_interval,
        cfg.quota_threshold,
        cfg.dry_run,
    )
    if cfg.provider_filter:
        logger.info("Provider filter: %s", ", ".join(cfg.provider_filter))

    try:
        while not stop.is_set():
            await check_and_act(cfg, api, backup, notifier)
            try:
                await asyncio.wait_for(stop.wait(), timeout=cfg.poll_interval)
            except asyncio.TimeoutError:
                pass
    finally:
        await api.close()
        logger.info("CPA-Tool stopped")


def main() -> None:
    try:
        cfg = Config.load()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
