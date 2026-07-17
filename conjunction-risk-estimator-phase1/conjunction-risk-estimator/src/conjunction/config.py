"""Central configuration, loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root if present. Safe no-op if the file doesn't exist.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    spacetrack_username: str | None = os.getenv("SPACETRACK_USERNAME")
    spacetrack_password: str | None = os.getenv("SPACETRACK_PASSWORD")
    tle_db_path: Path = Path(os.getenv("TLE_DB_PATH", "data/tle_cache.db"))

    def has_spacetrack_credentials(self) -> bool:
        return bool(self.spacetrack_username and self.spacetrack_password)


settings = Settings()
