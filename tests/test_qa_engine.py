import unittest
from unittest.mock import patch, MagicMock
from src.ingestion.indexer import IndexedDocument, CoordinateAnchor
from src.appraisal.qa import PaperQAEngine
from src.appraisal.sanitizer import sanitize_and_verify_appraisal


class TestPaperQAEngine(unittest.TestCase):

    def setUp(self):
        self.engine = PaperQAEngine(api_key="mock_key")
        self.doc_header = (
            "Title: DANCAVAS II Trial Screening Analysis\n"
            "Authors: Lindholt JS, Diederichsen ACP\n"
            "Journal: NEJM (2023)\n"
            "DOI/PMID: 10.1056/NEJMoa2214457"
        )
        self.anchors = {
            "[Abstract, Para 1]": CoordinateAnchor(
                anchor_id="[Abstract, Para 1]",
                page_number=1,
                page_width=595.0,
                page_height=842.0,
                section="Abstract",
                item_type="para",
                index=1,
                bbox=[10.0, 10.0, 200.0, 50.0],
                text="Cardiovascular screening may reduce mortality."
            ),
            "[Abstract, TableNote p1_504]": CoordinateAnchor(
                anchor_id="[Abstract, TableNote p1_504]",
                page_number=1,
                page_width=595.0,
                page_height=842.0,
                section="Abstract",
                item_type="tablenote",
                index=504,
                bbox=[10.0, 60.0, 200.0, 80.0],
                text="Values are expressed as numbers and percentages."
            ),
            "[Methods, Para 4]": CoordinateAnchor(
                anchor_id="[Methods, Para 4]",
                page_number=2,
                page_width=595.0,
                page_height=842.0,
                section="Methods",
                item_type="para",
                index=4,
                bbox=[10.0, 100.0, 200.0, 150.0],
                text="A total of 31,268 participants were randomized."
            ),
            "[Header, Meta 1]": CoordinateAnchor(
                anchor_id="[Header, Meta 1]",
                page_number=1,
                page_width=595.0,
                page_height=842.0,
                section="meta",
                item_type="meta",
                index=1,
                bbox=[10.0, 5.0, 200.0, 15.0],
                text="Downloaded from nejm.org on October 12, 2023."
            ),
            "[Footer, Meta 2]": CoordinateAnchor(
                anchor_id="[Footer, Meta 2]",
                page_number=2,
                page_width=595.0,
                page_height=842.0,
                section="Discussion",
                item_type="meta",
                index=2,
                bbox=[10.0, 750.0, 200.0, 760.0],
                text="Copyright 2023 Massachusetts Medical Society."
            ),
            "[Results, FigLegend 1]": CoordinateAnchor(
                anchor_id="[Results, FigLegend 1]",
                page_number=3,
                page_width=595.0,
                page_height=842.0,
                section="Results",
                item_type="figlegend",
                index=1,
                bbox=[10.0, 200.0, 200.0, 250.0],
                text="Figure 1 shows cumulative incidence of all-cause mortality."
            ),
            "[Methods, Box 1]": CoordinateAnchor(
                anchor_id="[Methods, Box 1]",
                page_number=2,
                page_width=595.0,
                page_height=842.0,
                section="Methods",
                item_type="box",
                index=1,
                bbox=[10.0, 300.0, 200.0, 350.0],
                text="Box 1 lists inclusion and exclusion criteria."
            )
        }
        self.indexed_doc = IndexedDocument(
            filename="dancavas.pdf",
            doc_header=self.doc_header,
            anchor_metadata=self.anchors,
            all_anchors={k: v.text for k, v in self.anchors.items()},
            raw_text="Full raw text"
        )

    def test_assemble_manuscript_context_filters_meta(self):
        """Verifies that Meta anchors are strictly filtered out while clinical sections are retained."""
        context, valid_anchors = self.engine.assemble_manuscript_context(self.indexed_doc)
        
        # Verify Doc_Header is included
        self.assertIn("[Doc_Header]", valid_anchors)
        self.assertIn("DANCAVAS II", context)
        
        # Verify clinical anchors are included
        self.assertIn("[Abstract, Para 1]", valid_anchors)
        self.assertIn("[Abstract, TableNote p1_504]", valid_anchors)
        self.assertIn("[Methods, Para 4]", valid_anchors)
        self.assertIn("[Results, FigLegend 1]", valid_anchors)
        self.assertIn("[Methods, Box 1]", valid_anchors)
        
        # Verify Meta anchors are strictly excluded
        self.assertNotIn("[Header, Meta 1]", valid_anchors)
        self.assertNotIn("[Footer, Meta 2]", valid_anchors)
        self.assertNotIn("Downloaded from nejm.org", context)
        self.assertNotIn("Massachusetts Medical Society", context)

    def test_query_normalization(self):
        """Verifies normalization handles punctuation, spaces, and case folding."""
        raw = "  How many Patients were in the STUDY?!!  "
        normalized = self.engine.normalize_query(raw)
        self.assertEqual(normalized, "how many patients were in the study")

    def test_query_cache_returns_zero_cost_hit(self):
        """Verifies repeat queries hit the in-memory cache and report cached=True."""
        clean_mock_answer = "The study enrolled 31,268 men [Methods, Para 4]."
        mock_sanitization = MagicMock()
        mock_sanitization.cleaned_markdown = clean_mock_answer
        mock_sanitization.verified_anchors = ["[Methods, Para 4]"]
        mock_sanitization.invalid_anchors = []

        with patch.object(self.engine, "_invoke_gemini_rest", return_value=(clean_mock_answer, "", "gemini-3.8-flash")), \
             patch("src.appraisal.qa.sanitize_and_verify_appraisal", return_value=mock_sanitization):
            
            # Turn 1: Fresh execution
            res1 = self.engine.ask(self.indexed_doc, "How many patients?", filename="dancavas.pdf")
            self.assertEqual(res1["cached"], False)
            self.assertEqual(res1["answer"], clean_mock_answer)
            self.assertEqual(res1["selected_model"], "gemini-3.8-flash")

            # Turn 2: Repeat execution with different punctuation/casing
            res2 = self.engine.ask(self.indexed_doc, "how many patients???", filename="dancavas.pdf")
            self.assertEqual(res2["cached"], True)
            self.assertEqual(res2["answer"], clean_mock_answer)

    def test_conversation_history_cap(self):
        """Verifies rolling conversation history caps at the last 4 turns."""
        history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "A3"},
            {"role": "user", "content": "Q4"},
            {"role": "assistant", "content": "A4"},
            {"role": "user", "content": "Q5"},
            {"role": "assistant", "content": "A5"}
        ]

        captured_prompt = {}

        def fake_invoke(prompt, system_instruction, preferred_model=None, thinking_level="low"):
            captured_prompt["text"] = prompt
            return "Sample answer [Methods, Para 4]", "", "gemini-3.8-flash"

        with patch.object(self.engine, "_invoke_gemini_rest", side_effect=fake_invoke):
            self.engine.ask(
                self.indexed_doc,
                "What about safety?",
                filename="dancavas_hist.pdf",
                conversation_history=history
            )

        prompt_str = captured_prompt.get("text", "")
        # Should not include older turns Q1, Q2, Q3
        self.assertNotIn("Q1", prompt_str)
        self.assertNotIn("A1", prompt_str)
        self.assertNotIn("Q2", prompt_str)
        self.assertNotIn("Q3", prompt_str)
        # Should include recent turns Q4, A4, Q5, A5 (last 4 turns)
        self.assertIn("Q4", prompt_str)
        self.assertIn("A4", prompt_str)
        self.assertIn("Q5", prompt_str)
        self.assertIn("A5", prompt_str)

    def test_expanded_sanitizer_regex_handles_tablenote_and_box(self):
        """Verifies sanitizer audits TableNote, FigLegend, and Box anchors properly."""
        valid_anchors = {
            "[Abstract, TableNote 504]": "Note text",
            "[Results, FigLegend 1]": "Legend text",
            "[Methods, Box 1]": "Box text"
        }
        test_markdown = (
            "Screening protocol details are in [Methods, Box 1]. "
            "Primary rates are shown in [Results, FigLegend 1] and noted in [Abstract, TableNote 504]."
        )
        res = sanitize_and_verify_appraisal(test_markdown, valid_anchors)
        self.assertIn("[Methods, Box 1]", res.verified_anchors)
        self.assertIn("[Results, FigLegend 1]", res.verified_anchors)
        self.assertIn("[Abstract, TableNote 504]", res.verified_anchors)
        self.assertEqual(len(res.invalid_anchors), 0)


if __name__ == "__main__":
    unittest.main()
