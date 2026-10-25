"""Client HTTP générique : cache disque, débit limité, reprises sur erreur.

Chaque réponse JSON est stockée compressée dans <cache_dir>/<endpoint>/<clé>.json.gz,
la clé étant un hash du chemin et des paramètres triés. Une requête déjà en cache
n'est jamais refaite (sauf refresh=True).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

USER_AGENT = "mushroam/0.1 (projet personnel de prevision de champignons)"
MAX_RETRIES = 5


def cache_key(path: str, params: dict) -> str:
    canon = json.dumps({"path": path, "params": params}, sort_keys=True, default=str)
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


class CachedClient:
    def __init__(self, api_root: str, cache_dir: Path, min_interval_s: float = 1.0,
                 session: requests.Session | None = None):
        self.api_root = api_root.rstrip("/")
        self.cache_dir = cache_dir
        self.min_interval_s = min_interval_s
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0
        self.n_http = 0  # requêtes réellement envoyées
        self.n_cache = 0  # réponses servies depuis le cache

    def _cache_path(self, path: str, params: dict) -> Path:
        endpoint = path.strip("/").replace("/", "_")
        return self.cache_dir / endpoint / f"{cache_key(path, params)}.json.gz"

    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _fetch(self, path: str, params: dict) -> dict:
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                resp = self.session.get(f"{self.api_root}{path}", params=params, timeout=90)
            except requests.ConnectionError:
                time.sleep(2 ** (attempt + 1))
                continue
            self.n_http += 1
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(2 ** (attempt + 1))  # 2, 4, 8, 16, 32 s
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Échec après {MAX_RETRIES} tentatives : {path} {params}")

    def get(
        self,
        path: str,
        params: dict,
        refresh: bool = False,
        cache_if: Callable[[dict], bool] = lambda _: True,
    ) -> dict:
        """GET avec cache. `cache_if` permet de ne pas figer une réponse encore
        susceptible d'évoluer (ex. : dernière page incomplète d'une pagination)."""
        cpath = self._cache_path(path, params)
        if cpath.exists() and not refresh:
            self.n_cache += 1
            with gzip.open(cpath, "rt", encoding="utf-8") as f:
                return json.load(f)["response"]

        data = self._fetch(path, params)
        if cache_if(data):
            cpath.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "path": path,
                "params": params,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "response": data,
            }
            tmp = cpath.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as f:
                json.dump(record, f)
            tmp.replace(cpath)
        return data
