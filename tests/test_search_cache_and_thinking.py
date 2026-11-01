"""
Unit tests for SQLite Search Query Cache and Dynamic Thinking Level Heuristic.
Enforces:
1. Normalization: lowercase, alphabetized terms, SHA-256 hash.
2. Force refresh cache bypass.
3. Concurrency safety (WAL mode, timeouts).
4. Dynamic thinkingLevel heuristic in PaperFinder.
"""

import os
import tempfile
import time
import unittest
from src.finder.cache import SearchQueryCache
from src.finder.searcher import PaperFinder


class TestSearchQueryCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_cache.db")
        self.cache = SearchQueryCache(db_path=self.db_path, default_ttl=3600)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_query_normalization_alphabetization(self):
        """Verify queries with permuted word order produce identical normalized strings and SHA-256 hashes."""
        q1 = "a combo of CoQ10 and selenium reduces cardiac deaths."
        q2 = "Selenium and CoQ10 reduces cardiac deaths, a combo of"
        q3 = "reduces cardiac deaths a combo of selenium and coq10"

        norm1, hash1 = SearchQueryCache.normalize_query(q1)
        norm2, hash2 = SearchQueryCache.normalize_query(q2)
        norm3, hash3 = SearchQueryCache.normalize_query(q3)

        self.assertEqual(norm1, norm2)
        self.assertEqual(norm2, norm3)
        self.assertEqual(hash1, hash2)
        self.assertEqual(hash2, hash3)

        # Confirm words are strictly sorted alphabetically
        words = norm1.split()
        self.assertEqual(words, sorted(words))

    def test_cache_hit_and_force_refresh_bypass(self):
        """Verify cached results are returned on repeat query and bypassed when force_refresh=True."""
        query = "Curcumin knee osteoarthritis randomized trial"
        mock_result = {
            "status": "success",
            "qualifying_count": 3,
            "qualifying_papers": [{"title": "Study 1"}, {"title": "Study 2"}, {"title": "Study 3"}]
        }

        # Initially empty
        self.assertIsNone(self.cache.get(query))

        # Store result
        self.cache.set(query, mock_result)

        # Cache hit
        cached = self.cache.get(query)
        self.assertIsNotNone(cached)
        self.assertTrue(cached.get("from_cache"))
        self.assertEqual(cached["qualifying_count"], 3)

        # Equivalence cache hit (permuted word order)
        permuted_query = "osteoarthritis randomized trial knee Curcumin"
        cached_permuted = self.cache.get(permuted_query)
        self.assertIsNotNone(cached_permuted)
        self.assertTrue(cached_permuted.get("from_cache"))

        # Force refresh bypass
        bypassed = self.cache.get(query, force_refresh=True)
        self.assertIsNone(bypassed, "force_refresh=True must bypass the cache and return None.")

    def test_wal_mode_enabled(self):
        """Verify SQLite connection initializes with WAL journal mode."""
        with self.cache._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            self.assertEqual(mode.lower(), "wal")


class TestDynamicThinkingLevel(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_finder_cache.db")
        self.finder = PaperFinder(api_key="mock_key", cache_db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_routine_query_defaults_to_low(self):
        """Routine keyword search without negation or high complexity defaults to low thinking."""
        query = "CoQ10 and selenium in heart failure"
        level = self.finder.determine_thinking_level(query)
        self.assertEqual(level, "low")

    def test_exclusion_negation_escalates_to_medium(self):
        """Queries containing clinical exclusion/negation tokens escalate to medium thinking."""
        negation_queries = [
            "Non-small cell lung cancer excluding EGFR mutations",
            "Cardiovascular mortality without prior statin therapy",
            "Breast cancer except triple negative",
            "Patients negative for HER2 mutation",
            "Neither chemotherapy nor radiation therapy"
        ]
        for q in negation_queries:
            level = self.finder.determine_thinking_level(q)
            self.assertEqual(level, "medium", f"Query '{q}' should escalate to medium thinking.")

    def test_syntactic_complexity_escalates_to_medium(self):
        """Queries with length > 120 characters escalate to medium thinking."""
        long_query = (
            "A prospective randomized double-blind placebo-controlled multi-center trial evaluating "
            "the long-term cardioprotective and anti-inflammatory effects of CoQ10 in elderly citizens"
        )
        self.assertGreater(len(long_query), 120)
        level = self.finder.determine_thinking_level(long_query)
        self.assertEqual(level, "medium")

    def test_differential_comparison_escalates_to_medium(self):
        """Queries comparing agents with 'vs' or 'compared to' escalate to medium thinking."""
        comp_query = "CoQ10 vs ubiquinol in congestive heart failure"
        level = self.finder.determine_thinking_level(comp_query)
        self.assertEqual(level, "medium")


if __name__ == "__main__":
    unittest.main()

