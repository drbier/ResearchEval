import unittest
from unittest.mock import patch, MagicMock
from src.appraisal.sanitizer import truncate_markdown_safely
from src.appraisal.commentary import CommentaryAndQCEngine
from src.ingestion.indexer import IndexedDocument, CoordinateAnchor

class TestCommentaryAndQC(unittest.TestCase):
    def test_truncate_markdown_safely(self):
        # 1. Under limit
        short_text = "**Bold statement.**"
        self.assertEqual(truncate_markdown_safely(short_text, 100), "**Bold statement.**")

        # 2. Block boundary accumulation
        multi_p = "Paragraph 1 is here.\n\nParagraph 2 is here too.\n\nParagraph 3 is dropped."
        res = truncate_markdown_safely(multi_p, 48)
        self.assertIn("Paragraph 1 is here.", res)
        self.assertIn("Paragraph 2 is here too.", res)
        self.assertNotIn("Paragraph 3", res)

        # 3. Delimiter parity balancing (unclosed bold)
        unclosed = "**Unclosed bold text at the end of the line"
        res_del = truncate_markdown_safely(unclosed, 100)
        self.assertTrue(res_del.endswith("**"))

        # 4. Dangling link stripping
        dangling = "Here is some text with [unfinished link](http://example.com/very/long"
        res_link = truncate_markdown_safely(dangling, 40)
        self.assertNotIn("[unfinished link", res_link)

    def test_quarantine_pipeline_strawman_and_anchors(self):
        engine = CommentaryAndQCEngine(api_key="mock_key")
        
        mock_doc = MagicMock(spec=IndexedDocument)
        mock_doc.doc_header = "Title: Sun Exposure Study\nJournal: JIM 2014"
        mock_doc.all_anchors = {
            "[Results, Table 2]": "All cause mortality was reduced HR 0.60.",
            "[Methods, Para 1]": "Prospective cohort of 29518 women."
        }

        # Mock LLM audit response with 1 valid finding, 1 strawman finding, and 1 ungrounded localized finding
        mock_json_response = """{
            "overall_integrity": "DISCREPANCY",
            "audit_status": "ISSUES_DETECTED",
            "summary_verdict": "Discrepancy detected.",
            "discrepancies": [
                {
                    "scope": "LOCALIZED_CLAIM",
                    "category": "NUMERICAL_ERROR",
                    "severity": "YELLOW",
                    "quoted_claim": "mortality was reduced",
                    "manuscript_evidence": "Table 2 shows HR 0.60 [Results, Table 2]",
                    "citations": ["[Results, Table 2]"],
                    "suggested_edit": "mortality had an HR of 0.60"
                },
                {
                    "scope": "LOCALIZED_CLAIM",
                    "category": "NUMERICAL_ERROR",
                    "severity": "RED",
                    "quoted_claim": "A completely invented strawman statement that never existed in the commentary draft",
                    "manuscript_evidence": "The author made this up [Methods, Para 1]",
                    "citations": ["[Methods, Para 1]"],
                    "suggested_edit": "Fix"
                },
                {
                    "scope": "LOCALIZED_CLAIM",
                    "category": "NUMERICAL_ERROR",
                    "severity": "RED",
                    "quoted_claim": "sun seekers lived longer",
                    "manuscript_evidence": "No evidence for this claim [Fictional, Para 99]",
                    "citations": ["[Fictional, Para 99]"],
                    "suggested_edit": "Drop claim"
                }
            ],
            "study_design_caveat": "Observational cohort study [Methods, Para 1]"
        }"""

        with patch.object(engine, "_invoke_gemini_rest", return_value=(mock_json_response, "", "gemini-3.8-flash")):
            audit_res = engine.audit_appraisal_and_commentary(
                indexed_doc=mock_doc,
                appraisal_markdown="Analysis: sun seekers lived longer and mortality was reduced.",
                commentary_text="My commentary: Sun seekers lived longer and mortality was reduced significantly."
            )

            # Gate A should drop the strawman statement
            discrepancies = audit_res["discrepancies"]
            quoted_claims = [d["quoted_claim"] for d in discrepancies]
            self.assertNotIn("A completely invented strawman statement that never existed in the commentary draft", quoted_claims)

            # Tier 3 Quarantine should drop the ungrounded citation [Fictional, Para 99]
            self.assertNotIn("sun seekers lived longer", quoted_claims)

            # The valid finding citing [Results, Table 2] must be preserved
            self.assertIn("mortality was reduced", quoted_claims)
            self.assertEqual(len(discrepancies), 1)

if __name__ == "__main__":
    unittest.main()

