"""
SQLite Query Cache for F.A.S.T. Paper Finder.
Enforces:
1. Normalization: extract, lowercase, and alphabetize query terms before SHA-256 hash.
2. Concurrency Safety: WAL mode (Write-Ahead Logging) and connection timeouts for multi-worker Uvicorn.
3. Cache-Bypass: force_refresh support.
"""

import sqlite3
import hashlib
import json
import time
import os
import re
from contextlib import contextmanager
from typing import Optional, Dict, Any, Tuple, Generator


class SearchQueryCache:
    def __init__(self, db_path: str = "data/search_cache.db", default_ttl: int = 86400):
        self.db_path = db_path
        self.default_ttl = default_ttl
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Create a connection with 30-second busy timeout and WAL mode enabled, ensuring cleanup."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Idempotently initialize cache schema and index."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    normalized_query TEXT,
                    raw_query TEXT,
                    results_json TEXT,
                    created_at REAL,
                    ttl_seconds INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created ON search_cache(created_at);")
            conn.commit()

    @staticmethod
    def normalize_query(query: str) -> Tuple[str, str]:
        """
        Constraint 3: Extract, lowercase, and alphabetize query terms
        before applying the SHA-256 hash to ensure structurally equivalent queries
        hit the same cache entry.
        """
        words = re.findall(r'[a-z0-9]+', query.lower())
        sorted_words = sorted(words)
        normalized = " ".join(sorted_words)
        query_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        return normalized, query_hash

    def get(self, query: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Retrieve cached results if fresh and not bypassed."""
        if force_refresh:
            return None

        _, query_hash = self.normalize_query(query)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT results_json, created_at, ttl_seconds FROM search_cache WHERE query_hash = ?",
                    (query_hash,)
                )
                row = cursor.fetchone()
                if not row:
                    return None

                results_json, created_at, ttl = row
                if time.time() - created_at > ttl:
                    return None

                data = json.loads(results_json)
                data["from_cache"] = True
                data["cached_at"] = created_at
                return data
        except Exception as e:
            print(f"[SearchCache] Error reading cache: {e}")
            return None

    def set(self, query: str, results: Dict[str, Any], ttl: Optional[int] = None):
        """Store results with SHA-256 hash key."""
        normalized, query_hash = self.normalize_query(query)
        ttl_val = ttl or self.default_ttl
        now = time.time()

        # Sanitize payload so from_cache metadata isn't stored inside raw cache
        save_data = {k: v for k, v in results.items() if k not in ("from_cache", "cached_at")}
        results_json = json.dumps(save_data)

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO search_cache (query_hash, normalized_query, raw_query, results_json, created_at, ttl_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(query_hash) DO UPDATE SET
                        results_json = excluded.results_json,
                        created_at = excluded.created_at,
                        ttl_seconds = excluded.ttl_seconds
                    """,
                    (query_hash, normalized, query, results_json, now, ttl_val)
                )
                conn.commit()
        except Exception as e:
            print(f"[SearchCache] Error writing cache: {e}")
