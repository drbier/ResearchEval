import os
import sys
import json
import glob
import re
import unittest
import pymupdf

project_root = r"D:\SSD-Drive\Antigravity\ResearchEval"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

class TestRuleGroundingAndParaphrase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = os.path.join(project_root, "data")
        cls.ref_dir = os.path.join(project_root, "Reference_papers")
        with open(os.path.join(cls.data_dir, "rulesdb.json"), "r", encoding="utf-8") as f:
            cls.rules = json.load(f)

    def test_01_framework_coverage(self):
        """Every framework FW_A through FW_J must have at least one applicable rule."""
        framework_ids = [f"FW_{c}" for c in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]]
        rule_fws = set()
        for r in self.rules:
            for fw in r.get("framework_ids", []):
                rule_fws.add(fw)
        
        for fw in framework_ids:
            self.assertIn(fw, rule_fws, f"Framework {fw} has no applicable rules in rulesdb.json")

    def test_02_rule_metadata_integrity(self):
        """Every rule must have required metadata fields and structured triggers."""
        required_fields = [
            "rule_id", "target_domain", "framework_ids", "provenance",
            "source_file", "source_item", "source_page", "key_terms",
            "trigger", "directional_bias", "appraisal_action"
        ]
        for r in self.rules:
            for f in required_fields:
                self.assertIn(f, r, f"Rule {r.get('rule_id')} missing field: {f}")
            self.assertIn(r["provenance"], ["checklist", "derived"], f"Invalid provenance for {r['rule_id']}")
            self.assertIsInstance(r["trigger"], dict, f"Rule {r['rule_id']} trigger must be a dict")
            self.assertNotIn("verbatim_quote", r, f"Rule {r['rule_id']} must not store verbatim_quote")

    def test_03_pdf_grounding_and_wording_overlap(self):
        """
        Verify that each rule's key terms exist on cited PDF page (+/- 1 page).
        Verify that no rule copies >= 12 consecutive words from source text (enforcing paraphrase).
        """
        if not os.path.exists(self.ref_dir):
            self.skipTest("Reference_papers directory not present on disk; skipping grounding check.")

        for r in self.rules:
            rel_path = r["source_file"]
            full_path = os.path.join(project_root, rel_path)
            
            # If path contains special unicode chars, locate via glob
            if not os.path.exists(full_path):
                candidates = glob.glob(os.path.join(project_root, os.path.dirname(rel_path), "*"))
                base_target = os.path.basename(rel_path).replace("\u2014", "")[:20]
                matched = [c for c in candidates if base_target in os.path.basename(c)]
                if matched:
                    full_path = matched[0]

            if not os.path.exists(full_path):
                self.fail(f"Source file not found for rule {r['rule_id']}: {rel_path}")

            doc = pymupdf.open(full_path)
            page_idx = r.get("source_page", 1) - 1
            # Check within +/- 1 page window
            window = [p for p in [page_idx - 1, page_idx, page_idx + 1] if 0 <= p < len(doc)]
            
            page_texts = [doc[p].get_text() for p in window]
            combined_page_text = " ".join(page_texts).lower()

            # Grounding check: at least one key term must appear on the page (if page has extractable text)
            if len(combined_page_text.strip()) > 300:
                key_terms = r.get("key_terms", [])
                has_key_term = any(t.lower() in combined_page_text for t in key_terms)
                self.assertTrue(
                    has_key_term,
                    f"Rule {r['rule_id']} key_terms {key_terms} not found near p. {r['source_page']} of {os.path.basename(rel_path)}"
                )

            # Wording overlap guardrail: no 12-consecutive-word run from appraisal_action may match PDF text exactly
            action_words = re.findall(r'[a-zA-Z0-9]+', r.get("appraisal_action", "").lower())
            if len(action_words) >= 12 and len(combined_page_text.strip()) > 300:
                normalized_page = " " + " ".join(re.findall(r'[a-zA-Z0-9]+', combined_page_text)) + " "
                for i in range(len(action_words) - 11):
                    n_gram = " " + " ".join(action_words[i:i+12]) + " "
                    self.assertNotIn(
                        n_gram,
                        normalized_page,
                        f"Rule {r['rule_id']} copied >= 12 consecutive words from source text on p. {r['source_page']}: '{n_gram.strip()}'"
                    )

if __name__ == "__main__":
    unittest.main()
