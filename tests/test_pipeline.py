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

    def test_06_framework_coverage_and_threshold_audit(self):
        """Verify all 10 frameworks have schema, triage config, and >=1 rule; audit threshold purge."""
        import json
        with open(os.path.join(self.data_dir, "triagedb.json"), "r", encoding="utf-8") as f:
            triagedb = json.load(f)
        with open(os.path.join(self.data_dir, "schemadb.json"), "r", encoding="utf-8") as f:
            schemadb = json.load(f)
        with open(os.path.join(self.data_dir, "rulesdb.json"), "r", encoding="utf-8") as f:
            rulesdb = json.load(f)

        expected_fws = [f"FW_{c}" for c in ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]]
        
        triage_fw_ids = [fw["framework_id"] for fw in triagedb]
        for fw_id in expected_fws:
            self.assertIn(fw_id, triage_fw_ids, f"Missing framework {fw_id} in triagedb")
            self.assertIn(fw_id, schemadb, f"Missing framework {fw_id} in schemadb")
            
            # Check schemadb has granular headings
            headings = schemadb[fw_id]["headings"]
            self.assertIn("## Research Objective", headings)
            self.assertIn("## Study Design", headings)
            self.assertIn("## Setting and Participants", headings)

        # Verify threshold purge: no ungrounded cutoffs in rulesdb.json
        rules_text = json.dumps(rulesdb)
        self.assertNotIn("missing data exceeds 5-10%", rules_text, "Ungrounded 5-10% missing data cutoff found in rulesdb")
        self.assertNotIn("3% - 5%", rules_text, "Ungrounded 3-5% discount rate cutoff found in rulesdb")
        self.assertNotIn("Grade 3-5 only", rules_text, "Ungrounded Grade 3-5 only harms cutoff found in rulesdb")
        self.assertNotIn("20% missing", rules_text, "Ungrounded 20% PRO missing data cutoff found in rulesdb")

        # Verify new required rules exist
        rule_ids = {r["rule_id"] for r in rulesdb}
        self.assertIn("R_CONSORT_HARMS_17A2", rule_ids)
        self.assertIn("R_NI_OBJECTIVE_MARGIN", rule_ids)
        self.assertIn("R_CHEERS_2022_EQUITY_PPIE", rule_ids)
        self.assertIn("R_SURROGATE_CLINICAL_OUTCOME", rule_ids)

    def test_07_ast_boolean_evaluation_and_no_collapse(self):
        """Verify deterministic boolean AST evaluation prevents AND collapse to OR."""
        from src.triage.classifier import evaluate_trigger_ast

        # Rule requiring both FW_A and +TAG_ONCOLOGY
        ast_and = {
            "all": [
                {"framework": "FW_A"},
                {"tag": "+TAG_ONCOLOGY"}
            ]
        }
        # FW_A without tag -> must be False
        self.assertFalse(evaluate_trigger_ast(ast_and, "FW_A", []))
        # Tag present but FW_B -> must be False
        self.assertFalse(evaluate_trigger_ast(ast_and, "FW_B", ["+TAG_ONCOLOGY"]))
        # Both present -> must be True
        self.assertTrue(evaluate_trigger_ast(ast_and, "FW_A", ["+TAG_ONCOLOGY"]))

        # Disjunction: FW_A OR FW_F
        ast_or = {
            "any": [
                {"framework": "FW_A"},
                {"framework": "FW_F"}
            ]
        }
        self.assertTrue(evaluate_trigger_ast(ast_or, "FW_A", []))
        self.assertTrue(evaluate_trigger_ast(ast_or, "FW_F", []))
        self.assertFalse(evaluate_trigger_ast(ast_or, "FW_C", []))

    def test_08_triage_precedence_ladder(self):
        """Verify precedence ladder: Protocol traps FW_E, Biomarker traps FW_I over FW_C, Survey traps FW_J."""
        engine = TriageEngine(self.data_dir)

        # 1. Protocol with trial mention -> must resolve to FW_E, not FW_A
        proto_header = "Study protocol for a randomized trial evaluating immunotherapy in lung cancer (SPIRIT 2013)"
        proto_methods = "This trial protocol describes the planned design, sample size power calculations, and statistical analysis plan."
        res_proto = engine.classify_text(proto_header, proto_methods)
        self.assertEqual(res_proto.primary_framework_id, "FW_E")
        self.assertIn("R_SPIRIT_POWER_SAMPLE_SIZE", res_proto.applicable_rules)

        # 2. AMORIS Biomarker Cohort -> must resolve to FW_I, not generic FW_C
        amoris_header = "Blood biomarker profiles and exceptional longevity in a 35-year follow-up of the Swedish AMORIS cohort"
        amoris_methods = "We evaluated biomarker profiles including glucose, uric acid, creatinine in 44,636 participants in the AMORIS cohort."
        res_amoris = engine.classify_text(amoris_header, amoris_methods)
        self.assertEqual(res_amoris.primary_framework_id, "FW_I")
        self.assertIn("+TAG_COHORT", res_amoris.sub_feature_tags)
        self.assertIn("+TAG_BIOMARKER", res_amoris.sub_feature_tags)
        self.assertIn("R_REMARK_SPECIMEN_ASSAY", res_amoris.applicable_rules)

        # 3. Survey Research -> must resolve to FW_J
        survey_header = "Physician attitudes toward oncology guidelines: A cross-sectional survey questionnaire"
        survey_methods = "A cross-sectional survey was distributed to clinicians with 5-point Likert scales. Response rate and non-response bias were evaluated."
        res_survey = engine.classify_text(survey_header, survey_methods)
        self.assertEqual(res_survey.primary_framework_id, "FW_J")
        self.assertIn("R_SURVEY_RESPONSE_BIAS", res_survey.applicable_rules)

    def test_09_pan_medical_triage_and_lexicon(self):
        """Verify pan-medical tagging (Cardiology, Nephrology, Neurology) and RECIST 1.1 lexicon values."""
        engine = TriageEngine(self.data_dir)

        # 1. Cardiology trial (DAPA-HF style)
        cardio_header = "Dapagliflozin in Patients with Heart Failure and Reduced Ejection Fraction: A Multicenter Randomized Double-Blind Trial"
        cardio_methods = "Patients with HFrEF were randomly assigned to dapagliflozin or placebo. The primary composite outcome was cardiovascular death or hospitalization for heart failure. Symptoms were assessed via the Kansas City Cardiomyopathy Questionnaire (KCCQ)."
        res_cardio = engine.classify_text(cardio_header, cardio_methods)
        self.assertEqual(res_cardio.primary_framework_id, "FW_A")
        self.assertIn("+TAG_CARDIOLOGY", res_cardio.sub_feature_tags)
        self.assertIn("+TAG_COMPOSITE", res_cardio.sub_feature_tags)
        self.assertIn("+TAG_CONSORT_PRO", res_cardio.sub_feature_tags)
        self.assertIn("R_COMPOSITE_DECONSTRUCTION", res_cardio.applicable_rules)

        # 2. Check RECIST 1.1 and pan-medical entries in lexicondb
        import json
        with open(os.path.join(self.data_dir, "lexicondb.json"), "r", encoding="utf-8") as f:
            lexicon = json.load(f)
        lex_terms = {item["term"]: item for item in lexicon}
        
        self.assertIn("RECIST 1.1 Criteria", lex_terms)
        recist_def = lex_terms["RECIST 1.1 Criteria"]["definition"]
        self.assertIn("10 mm", recist_def)
        self.assertIn("15 mm", recist_def)
        self.assertIn("20% relative increase", recist_def)
        self.assertIn("5 mm", recist_def)

        self.assertIn("Major Adverse Cardiac Events (MACE)", lex_terms)
        self.assertIn("Kansas City Cardiomyopathy Questionnaire (KCCQ)", lex_terms)
        self.assertIn("eGFR Slope & Composite Renal Endpoints", lex_terms)
        self.assertIn("Expanded Disability Status Scale (EDSS)", lex_terms)

if __name__ == "__main__":
    unittest.main()

