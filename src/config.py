from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Config:
    base_url: str = "http://localhost:8317"
    management_key: str = ""
    poll_interval: int = 60
    quota_threshold: int = 10
    provider_filter: list[str] = field(default_factory=list)
    webhook_url: str = ""
    backup_dir: str = "/data/backups"
    dry_run: bool = False

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> Config:
        """Load config from YAML file first, then override with environment variables."""
        data: dict = {}

        # Load from YAML if available
        path = Path(config_path) if config_path else Path("config.yaml")
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}

        # Environment variables override YAML values
        env_map = {
            "CPA_BASE_URL": "base_url",
            "CPA_MANAGEMENT_KEY": "management_key",
            "CPA_POLL_INTERVAL": "poll_interval",
            "CPA_QUOTA_THRESHOLD": "quota_threshold",
            "CPA_PROVIDER_FILTER": "provider_filter",
            "CPA_WEBHOOK_URL": "webhook_url",
            "CPA_BACKUP_DIR": "backup_dir",
            "CPA_DRY_RUN": "dry_run",
        }

        for env_key, field_name in env_map.items():
            val = os.environ.get(env_key)
            if val is not None:
                data[field_name] = val

        # Type coercion
        if "poll_interval" in data:
            data["poll_interval"] = int(data["poll_interval"])
        if "quota_threshold" in data:
            data["quota_threshold"] = int(data["quota_threshold"])
        if "dry_run" in data:
            v = data["dry_run"]
            data["dry_run"] = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
        if "provider_filter" in data:
            v = data["provider_filter"]
            if isinstance(v, str):
                data["provider_filter"] = [s.strip() for s in v.split(",") if s.strip()] if v else []

        cfg = cls(**data)

        if not cfg.management_key:
            raise ValueError("CPA_MANAGEMENT_KEY is required (env var or config.yaml)")

        return cfg
