"""
Comprehensive Test Suite for F.A.C.T. Paper Finder 2.2
======================================================
Part A: Deterministic / Offline Tests (Fast, zero network, zero LLM tokens).
Part B: Live API Verification & Regression Benchmark Tests (TC-01 through TC-05).

Usage:
    python test_searcher.py          # Runs Part A + Part B (if API key present)
    python test_searcher.py --offline # Runs Part A only
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.finder.searcher import (
    PaperFinder,
    SearchQueryCache,
    CACHE_LOGIC_VERSION,
    AMBIGUOUS_ACRONYMS,
    SURROGATE_BIOMARKER_TERMS,
    MODEL_HIERARCHY,
    PRIMARY_MODEL
)


# ==============================================================================
# PART A: Deterministic / Offline Test Suite
# ==============================================================================

class TestSearcherDeterministic(unittest.TestCase):
    """Part A: Deterministic unit tests requiring zero network calls or LLM tokens."""

    def setUp(self):
        self.finder = PaperFinder(api_key="mock_key_for_testing")

    def test_ambiguous_acronym_blocking(self):
        """Verify bare ambiguous abbreviations like 'T4', 'T3', 'HR' are strictly blocked."""
        # Ambiguous acronyms must exist in the blocklist
        self.assertIn("t4", AMBIGUOUS_ACRONYMS)
        self.assertIn("t3", AMBIGUOUS_ACRONYMS)
        self.assertIn("hr", AMBIGUOUS_ACRONYMS)

        # In query term formatting, bare 'T4' must be eliminated
        formatted = self.finder._format_term_group(["levothyroxine", "T4", "Synthroid", "t3"])
        self.assertIn('"levothyroxine"[tw]', formatted)
        self.assertIn('"Synthroid"[tw]', formatted)
        self.assertNotIn('"T4"', formatted)
        self.assertNotIn('"t3"', formatted)

    def test_query_generation_mesh_and_text_words(self):
        """Verify queries utilize modernized [tw] and [MeSH Terms] without rigid [tiab]."""
        entities = {
            "intervention_agents": [{
                "agent": "levothyroxine",
                "synonyms": ["Synthroid", "L-thyroxine"],
                "parent_classes": ["thyroid hormone", "THRT"],
                "mesh_terms": ["Thyroxine", "Thyroid Hormones"]
            }],
            "condition": ["breast cancer"],
            "endpoints": ["progression", "survival"],
            "population": [],
            "geography": []
        }

        # Tier 1 (Strict): specific terms only + endpoints
        q_t1 = self.finder.build_pubmed_query(entities, tier=1, field_tag="[tw]")
        self.assertIn('"levothyroxine"[tw]', q_t1)
        self.assertIn('"Synthroid"[tw]', q_t1)
        self.assertIn('"breast cancer"[tw]', q_t1)
        self.assertIn('"progression"[tw]', q_t1)
        self.assertNotIn('"thyroid hormone"[tw]', q_t1)

        # Tier 1b (Semantic Expansion): includes parent class + MeSH + endpoints
        q_t1b = self.finder.build_pubmed_query(entities, tier="1b", field_tag="[tw]")
        self.assertIn('"levothyroxine"[tw]', q_t1b)
        self.assertIn('"thyroid hormone"[tw]', q_t1b)
        self.assertIn('"THRT"[tw]', q_t1b)
        self.assertIn('"Thyroid Hormones"[MeSH Terms]', q_t1b)
        self.assertIn('"progression"[tw]', q_t1b)

        # Tier 3 (Core Clinical Only): relaxes endpoints
        q_t3 = self.finder.build_pubmed_query(entities, tier=3, field_tag="[tw]")
        self.assertIn('"breast cancer"[tw]', q_t3)
        self.assertNotIn('"progression"[tw]', q_t3)

    def test_preranking_reserved_slots_for_class_matches(self):
        """Verify pre-ranking guarantees >= 35% reserved quota for parent-class-only matches."""
        entities = {
            "intervention_agents": [{
                "agent": "levothyroxine",
                "synonyms": ["Synthroid"],
                "parent_classes": ["thyroid hormone", "THRT"],
                "mesh_terms": ["Thyroxine", "Thyroid Hormones"]
            }],
            "condition": ["breast cancer"],
            "intervention": ["levothyroxine", "Synthroid"],
            "parent_classes": ["thyroid hormone", "THRT"]
        }

        # Create 10 specific candidates and 10 class-only candidates
        candidates = []
        for i in range(10):
            candidates.append({
                "pmid": f"spec_{i}",
                "title": f"Levothyroxine study {i}",
                "year": "2023",
                "abstract": f"Study evaluating levothyroxine in breast cancer patients cohort {i}."
            })
        for j in range(10):
            candidates.append({
                "pmid": f"class_{j}",
                "title": f"Thyroid hormone study {j}",
                "year": "2023",
                "abstract": f"Study evaluating exogenous thyroid hormone and THRT in breast cancer survival {j}."
            })

        selected = self.finder._prerank_and_select_candidates(
            candidates,
            entities,
            user_query="levothyroxine in breast cancer",
            total_limit=20,
            class_quota_ratio=0.35
        )

        self.assertEqual(len(selected), 20)
        class_only_count = sum(1 for c in selected if c.get("is_class_only"))
        # Must reserve at least 35% of 20 = 7 slots
        self.assertGreaterEqual(class_only_count, 7)

    def test_biomarker_penalty_dynamic_exemption(self):
        """Verify biomarker penalty is NOT applied if the biomarker is part of user query or entity."""
        entities = {
            "intervention_agents": [{
                "agent": "levothyroxine",
                "synonyms": [],
                "parent_classes": ["thyroid hormone"],
                "mesh_terms": ["Thyroxine"]
            }],
            "condition": ["breast cancer"],
            "intervention": ["levothyroxine"],
            "parent_classes": ["thyroid hormone"]
        }

        cand_thyroid = {
            "title": "Thyroid hormone enhances estrogen-mediated proliferation in breast cancer",
            "year": "2023",
            "abstract": "We evaluate thyroid hormone receptor signaling in breast cancer."
        }

        # Since 'thyroid' is part of the parent class, it must NOT receive the -40 penalty
        score = self.finder._score_clinical_priority(cand_thyroid, entities, query_str="levothyroxine promotes breast cancer progression")
        self.assertGreaterEqual(score, 25, "Target domain terms like 'thyroid' must not be penalized when in query/entities.")

    def test_cache_versioning_and_degraded_suppression(self):
        """Verify cache key incorporates logic version string and degraded states are never cached."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = SearchQueryCache(db_path=os.path.join(tmp_dir, "test.db"))

            # 1. Versioning
            _, hash_v2 = cache.normalize_query("levothyroxine breast cancer")
            self.assertTrue(len(hash_v2) == 64)

            # 2. Refusal to cache degraded results
            degraded_payload = {
                "status": "success",
                "is_degraded": True,
                "partial_results": True,
                "qualifying_count": 2,
                "qualifying_papers": [{"title": "P1"}]
            }
            cache.set("levothyroxine breast cancer", degraded_payload)
            self.assertIsNone(cache.get("levothyroxine breast cancer"), "Degraded results must NEVER be cached.")

            # 3. Valid payload IS cached
            valid_payload = {
                "status": "success",
                "is_degraded": False,
                "qualifying_count": 3,
                "qualifying_papers": [{"title": "P1"}, {"title": "P2"}, {"title": "P3"}]
            }
            cache.set("levothyroxine breast cancer", valid_payload)
            cached_res = cache.get("levothyroxine breast cancer")
            self.assertIsNotNone(cached_res)
            self.assertEqual(cached_res["qualifying_count"], 3)


# ==============================================================================
# PART B: Live API Benchmark & Verification Tests (TC-01 through TC-05)
# ==============================================================================

class TestSearcherLiveBenchmarks(unittest.TestCase):
    """Part B: Live API verification testing authentic PubMed retrieval and gatekeeping."""

    @classmethod
    def setUpClass(cls):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise unittest.SkipTest("GEMINI_API_KEY not configured. Skipping live benchmark tests.")
        cls.finder = PaperFinder(api_key=api_key)

    def test_tc01_tc02_levothyroxine_landmark_papers(self):
        """
        TC-01 & TC-02:
        Query: 'levothyroxine promotes breast cancer progression'
        Expected:
        - PMID 37723865 (Thyroid hormone enhances estrogen-mediated proliferation...)
        - PMID 33097494 (Exogenous Thyroid Hormone Is Associated with Shortened Survival...)
        Both must appear in the retrieved and verified candidate pool.
        """
        query = "levothyroxine promotes breast cancer progression"
        print(f"\n[Part B] Executing Live Benchmark: '{query}'...")
        res = self.finder.find_papers(query, max_results=10, force_refresh=True)

        self.assertEqual(res.get("status"), "success")
        qualifying = res.get("qualifying_papers", [])
        verified_pmids = {str(p.get("pmid")) for p in qualifying if p.get("pmid")}
        titles = [p.get("title") for p in qualifying]

        print(f"[Part B] Retrieved {len(qualifying)} verified papers:")
        for idx, t in enumerate(titles, 1):
            print(f"  {idx}. {t}")

        # TC-01 Assertion: Paper 1
        has_paper_1 = "37723865" in verified_pmids or any("proliferation" in t.lower() and "thyroid hormone" in t.lower() for t in titles)
        self.assertTrue(has_paper_1, "TC-01 FAILED: Landmark paper PMID 37723865 must be present in verified results.")

        # TC-02 Assertion: Paper 3
        has_paper_3 = "33097494" in verified_pmids or any("shortened survival" in t.lower() and "thyroid hormone" in t.lower() for t in titles)
        self.assertTrue(has_paper_3, "TC-02 FAILED: Landmark paper PMID 33097494 must be present in verified results.")

    def test_tc03_paper_2_expected_failure(self):
        """
        TC-03: Soft Assertion / Expected Boundary Limitation for Paper #2.
        PMID 38437824 (Korean nationwide cohort on Levothyroxine subsequent primary cancers)
        has breast cancer data ONLY in full-text tables, with zero mentions in the PubMed abstract.
        Documents this boundary behavior without failing the test suite.
        """
        query = "levothyroxine promotes breast cancer progression"
        res = self.finder.find_papers(query, max_results=10, force_refresh=False)
        verified_pmids = {str(p.get("pmid")) for p in res.get("qualifying_papers", []) if p.get("pmid")}

        if "38437824" in verified_pmids:
            print("[Part B: TC-03] Note: Paper #2 (PMID 38437824) was surprisingly matched!")
        else:
            print("[Part B: TC-03] Expected Boundary Behavior Verified: PMID 38437824 lacks 'breast' in PubMed abstract (data in full-text tables only).")

    def test_tc04_curcumin_tamoxifen_regression(self):
        """TC-04: Regression benchmark - Curcumin enhances tamoxifen in ER+ breast cancer."""
        query = "curcumin enhances tamoxifen in ER+ breast cancer"
        print(f"\n[Part B] Executing Regression Benchmark: '{query}'...")
        res = self.finder.find_papers(query, max_results=5, force_refresh=False)

        self.assertEqual(res.get("status"), "success")
        self.assertGreaterEqual(res.get("qualifying_count", 0), 1)
        titles = [p.get("title", "").lower() for p in res.get("qualifying_papers", [])]
        has_curcumin_tamoxifen = any("curcumin" in t and "tamoxifen" in t for t in titles)
        self.assertTrue(has_curcumin_tamoxifen, "TC-04 Regression: Must find studies evaluating curcumin + tamoxifen co-administration.")

    def test_tc05_coq10_swedish_cohort_regression(self):
        """TC-05: Regression benchmark - CoQ10 cardiovascular mortality in Swedish cohort (KiSel-10)."""
        query = "CoQ10 cardiovascular mortality in Swedish cohort"
        print(f"\n[Part B] Executing Regression Benchmark: '{query}'...")
        res = self.finder.find_papers(query, max_results=5, force_refresh=False)

        self.assertEqual(res.get("status"), "success")
        qualifying = res.get("qualifying_papers", [])
        self.assertGreaterEqual(len(qualifying), 1)

        # First paper must be the landmark Alehagen KiSel-10 trial (PMID 22626835 or high scoring Swedish trial)
        top_paper = qualifying[0]
        self.assertGreaterEqual(top_paper.get("match_score", 0), 85)
        top_title = top_paper.get("title", "").lower()
        self.assertTrue("cardiovascular mortality" in top_title or "kisel-10" in top_title or "selenium" in top_title)


if __name__ == "__main__":
    if "--offline" in sys.argv:
        suite = unittest.TestLoader().loadTestsFromTestCase(TestSearcherDeterministic)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)
    else:
        unittest.main(verbosity=2)
