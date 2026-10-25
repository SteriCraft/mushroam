"""Client iNaturalist : 1 requête/seconde maximum, cache dans data/raw/inat/."""

from __future__ import annotations

from pathlib import Path

import requests

from mushroam.config import RAW_DIR
from mushroam.http import CachedClient


class INatClient(CachedClient):
    def __init__(self, cache_dir: Path | None = None, session: requests.Session | None = None):
        super().__init__("https://api.inaturalist.org", cache_dir or RAW_DIR / "inat",
                         min_interval_s=1.0, session=session)
