"""Client GBIF : cache dans data/raw/gbif/, débit volontairement modéré."""

from __future__ import annotations

from pathlib import Path

import requests

from mushroam.config import RAW_DIR
from mushroam.http import CachedClient


class GBIFClient(CachedClient):
    def __init__(self, cache_dir: Path | None = None, session: requests.Session | None = None):
        super().__init__("https://api.gbif.org/v1", cache_dir or RAW_DIR / "gbif",
                         min_interval_s=1.0, session=session)
