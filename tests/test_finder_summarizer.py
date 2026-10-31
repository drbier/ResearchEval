"""
Unit tests for PaperFinder and PaperSummarizer modules.
ENFORCES ZERO LLM TOKEN WASTE: All external HTTP and LLM calls are mocked with fixtures.
"""

import unittest
from unittest.mock import patch, MagicMock
from src.finder.searcher import PaperFinder
from src.summarizer.engine import PaperSummarizer


class TestPaperFinder(unittest.TestCase):
    """Verify PaperFinder 4-tier relaxation ladder, binary clinical gate, and zero-trust formatting."""

    def setUp(self):
        self.finder = PaperFinder(api_key="mock_test_key")

    def test_query_relaxation_ladder_generation(self):
        """Verify programmatic Boolean query generation across tiers."""
        entities = {
            "intervention": ["CoQ10", "ubiquinone"],
            "condition": ["heart attack", "myocardial infarction"],
            "population": ["women"],
            "geography": ["Sweden", "Scandinavian"],
            "study_design": ["RCT"]
        }

        # Tier 1: Includes all components
        t1 = self.finder.build_pubmed_query(entities, tier=1)
        self.assertIn('"CoQ10"[tiab]', t1)
        self.assertIn('"heart attack"[tiab]', t1)
        self.assertIn('"Sweden"[tiab]', t1)
        self.assertIn('"women"[tiab]', t1)

        # Tier 2: Relaxes Geography (drops Sweden/Scandinavian)
        t2 = self.finder.build_pubmed_query(entities, tier=2)
        self.assertIn('"CoQ10"[tiab]', t2)
        self.assertIn('"heart attack"[tiab]', t2)
        self.assertIn('"women"[tiab]', t2)
        self.assertNotIn("Sweden", t2)

        # Tier 3: Core Clinical Only (drops Population and Geography)
        t3 = self.finder.build_pubmed_query(entities, tier=3)
        self.assertIn('"CoQ10"[tiab]', t3)
        self.assertIn('"heart attack"[tiab]', t3)
        self.assertNotIn("women", t3)
        self.assertNotIn("Sweden", t3)

    @patch.object(PaperFinder, "_invoke_gemini")
    def test_binary_clinical_gate_rejection(self, mock_gemini):
        """Verify binary clinical gate immediately rejects mismatching intervention/condition (0% score)."""
        # Scenario: Population matches, but Intervention does NOT match
        mock_gemini.return_value = (
            '{"matches_intervention": false, "matches_condition": true, "binary_gate_passed": false, "match_score": 0, "grounded_summary": ""}',
            "gemini-3.8-flash"
        )

        candidate = {
            "title": "Study of Vitamin D in Swedish Women",
            "year": "2021",
            "abstract": "We evaluated Vitamin D for heart disease in Swedish women."
        }
        entities = {
            "intervention": ["CoQ10"],
            "condition": ["heart attack"],
            "population": ["women"],
            "geography": ["Sweden"]
        }

        verified = self.finder.verify_and_score_candidate(candidate, entities, "CoQ10 in Swedish women")
        self.assertIsNone(verified, "Candidate failing binary clinical gate must be rejected (returned None).")

    @patch.object(PaperFinder, "_invoke_gemini")
    def test_binary_clinical_gate_acceptance(self, mock_gemini):
        """Verify candidate passing binary clinical gate achieves >= 50% baseline score."""
        mock_gemini.return_value = (
            '{"matches_intervention": true, "matches_condition": true, "binary_gate_passed": true, "population_match": true, "geography_match": true, "study_design_match": true, "match_score": 95, "grounded_summary": "CoQ10 supplementation significantly reduced cardiovascular mortality in elderly Swedish cohort."}',
            "gemini-3.8-flash"
        )

        candidate = {
            "title": "Cardiovascular Mortality and Coenzyme Q10 Supplementation",
            "year": "2013",
            "abstract": "A 5-year prospective randomized double-blind placebo-controlled trial in Swedish elderly cohort."
        }
        entities = {
            "intervention": ["CoQ10"],
            "condition": ["cardiovascular mortality"],
            "population": ["elderly"],
            "geography": ["Sweden"]
        }

        verified = self.finder.verify_and_score_candidate(candidate, entities, "CoQ10 in Sweden")
        self.assertIsNotNone(verified)
        self.assertEqual(verified["match_score"], 95)
        self.assertEqual(verified["matches_intervention"], True)
        self.assertEqual(verified["matches_condition"], True)
        self.assertIn("cardiovascular mortality", verified["grounded_summary"])

    def test_semantic_scholar_strict_null_handling(self):
        """Verify papers lacking abstracts in Semantic Scholar are rejected."""
        null_candidate = {
            "title": "Missing Abstract Paper",
            "abstract": None,
            "year": 2020
        }
        entities = {"intervention": ["CoQ10"], "condition": ["heart failure"]}
        verified = self.finder.verify_and_score_candidate(null_candidate, entities, "CoQ10 query")
        self.assertIsNone(verified, "Papers lacking abstracts must be strictly discarded.")


class TestPaperSummarizer(unittest.TestCase):
    """Verify PaperSummarizer strict abstract restriction, null-handling, and layout."""

    def setUp(self):
        self.summarizer = PaperSummarizer(api_key="mock_test_key")

    def test_null_handling_for_inaccessible_url(self):
        """Verify inaccessible URLs yield 'Unable to access content' without hallucinating."""
        res = self.summarizer.resolve_url_to_structured_abstract("https://example.com/invalid-link")
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["error"], "Unable to access content")

        # Test single study summary layout for inaccessible link
        summary_out = self.summarizer.summarize_single_study(res)
        self.assertIn("Title:\nUnable to access content", summary_out)
        self.assertIn("Summary:\nUnable to access content", summary_out)
        self.assertIn("Source:\nhttps://example.com/invalid-link", summary_out)

    @patch.object(PaperSummarizer, "_invoke_gemini")
    def test_single_study_strict_layout(self, mock_gemini):
        """Verify valid study summary produces exact Title / Summary / Source layout."""
        mock_gemini.return_value = (
            "Coenzyme Q10 was shown to reduce cardiovascular death rates by 43% over a five-year period in older adults.",
            "gemini-3.8-flash"
        )

        study_data = {
            "status": "success",
            "input_url": "https://pubmed.ncbi.nlm.nih.gov/23843810/",
            "title": "Cardiovascular mortality and CoQ10 trial",
            "structured_abstract": "OBJECTIVE: Test CoQ10. RESULTS: Mortality decreased 43%."
        }

        output = self.summarizer.summarize_single_study(study_data)
        expected = (
            "Title:\n"
            "Cardiovascular mortality and CoQ10 trial\n\n"
            "Summary:\n"
            "Coenzyme Q10 was shown to reduce cardiovascular death rates by 43% over a five-year period in older adults.\n\n"
            "Source:\n"
            "https://pubmed.ncbi.nlm.nih.gov/23843810/"
        )
        self.assertEqual(output.strip(), expected.strip())


if __name__ == "__main__":
    unittest.main()
