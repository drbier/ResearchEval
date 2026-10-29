import os
import sys
import unittest

# Ensure project root is in path
project_root = r"D:\SSD-Drive\Antigravity\ResearchEval"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.ingestion.indexer import parse_and_index_pdf
from src.triage.classifier import TriageEngine
from src.appraisal.sanitizer import sanitize_and_verify_appraisal
from src.appraisal.generator import SynthesisEngine
from src.ingestion.fetcher import PaperFetcher

class TestResearchEvalPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = os.path.join(project_root, "data")
        cls.test_pdf = os.path.join(
            project_root,
            "Reference_papers",
            "2.Statistics",
            "Interpreting_the_results_of_noninferiority_trials-.pdf"
        )

    def test_01_knowledge_bases_exist(self):
        """Verify all 4 core JSON databases exist and have valid entries."""
        for name in ["triagedb.json", "rulesdb.json", "lexicondb.json", "schemadb.json"]:
            path = os.path.join(self.data_dir, name)
            self.assertTrue(os.path.exists(path), f"Missing database: {name}")

    def test_02_pdf_coordinate_indexing(self):
        """Verify PDF parser extracts layout-aware coordinate anchors."""
        indexed = parse_and_index_pdf(self.test_pdf)
        self.assertGreater(len(indexed.all_anchors), 10, "Failed to extract coordinate anchors")
        self.assertIn("[Doc_Header]", indexed.all_anchors, "Missing [Doc_Header] coordinate")
        self.assertTrue(any(a.startswith("[Introduction, Para") for a in indexed.all_anchors))

    def test_03_triage_classification(self):
        """Verify triage classifier correctly identifies study design and triggered rules."""
        engine = TriageEngine(self.data_dir)
        indexed = parse_and_index_pdf(self.test_pdf)
        
        abstract_methods = ""
        for sec in ["Abstract", "Introduction", "Methods"]:
            if sec in indexed.sections:
                for a in indexed.sections[sec][:10]:
                    abstract_methods += f"{a.text}\n"
                    
        triage = engine.classify_text(indexed.doc_header, abstract_methods)
        # Non-inferiority paper must classify as FW_F
        self.assertEqual(triage.primary_framework_id, "FW_F")
        self.assertIn("+TAG_NON_INFERIORITY", triage.sub_feature_tags)
        self.assertIn("R_NI_DUAL_ANALYSIS", triage.applicable_rules)

    def test_04_sanitizer_and_anchor_verification(self):
        """Verify sanitizer strips disclaimers/fillers and flags invalid anchors."""
        valid_set = {"[Doc_Header]": "Header", "[Methods, Para 1]": "Methods"}
        test_text = (
            "# Title\n"
            "This trial showed benefit [Methods, Para 1] and [Doc_Header].\n"
            "An unsupported assertion was made [Invalid, Para 99].\n\n"
            "Disclaimer: This evaluation is for informational purposes only.\n"
            "I hope this helps! Let me know if you need anything else."
        )
        res = sanitize_and_verify_appraisal(test_text, valid_set)
        self.assertNotIn("informational purposes only", res.cleaned_markdown)
        self.assertNotIn("I hope this helps", res.cleaned_markdown)
        self.assertIn("[Methods, Para 1]", res.verified_anchors)
        self.assertIn("[Doc_Header]", res.verified_anchors)
        self.assertIn("[Invalid, Para 99]", res.invalid_anchors)
        self.assertFalse(res.is_valid)

    def test_05_pubmed_availability_and_retrieval(self):
        """Verify PubMed availability check via elink and JATS XML full-text retrieval."""
        upload_dir = os.path.join(self.data_dir, "uploads")
        fetcher = PaperFetcher(upload_dir)

        # 1. PubMed with full text in PMC
        res1 = fetcher.check_url_availability("https://pubmed.ncbi.nlm.nih.gov/37726553/")
        self.assertEqual(res1.get("status"), "success")
        self.assertTrue(res1.get("full_text_available"))
        self.assertEqual(res1.get("source_type"), "PubMed Central (PMC)")
        self.assertEqual(res1.get("pmcid"), "PMC10643434")

        # 2. Paywalled PubMed
        res2 = fetcher.check_url_availability("35000000")
        self.assertEqual(res2.get("status"), "success")
        self.assertFalse(res2.get("full_text_available"))
        self.assertTrue(res2.get("is_abstract_only"))

        # 3. Full-text retrieval via PMC ID
        resolved = fetcher.resolve_url("PMC10643434")
        self.assertEqual(resolved.get("status"), "full_text_pdf")
        self.assertFalse(resolved.get("is_abstract_only"))
        pdf_path = os.path.join(upload_dir, resolved.get("pdf_filename"))
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 5000)

if __name__ == "__main__":
    unittest.main()

