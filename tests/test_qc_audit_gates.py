import json
import unittest
from src.ingestion.indexer import IndexedDocument
from src.appraisal.commentary import CommentaryAndQCEngine


class TestQCAuditGates(unittest.TestCase):
    def setUp(self):
        self.engine = CommentaryAndQCEngine(api_key="dummy-key")
        self.doc = IndexedDocument(
            filename="PMC13170125.pdf",
            doc_header="Impact of Tamoxifen Only after Lumpectomy for Good Risk DCIS",
            all_anchors={
                "[Doc_Header]": "Impact of Tamoxifen Only after Lumpectomy for Good Risk DCIS",
                "[Abstract, Results]": "878 patients were analyzed. 15-year IBR 11.4% vs 19.0%.",
                "[Methods, Para 3]": "Intent to take tamoxifen was declared at trial entry; adherence was not longitudinally tracked in RTOG 9804.",
                "[Results, Para 6]": "After adjusting for age and trial number, multivariable OS HR = 0.79 (95% CI: 0.57-1.09; p = 0.15).",
                "[Results, Table 2]": "Unadjusted Cox regression OS HR = 0.50 (95% CI: 0.37-0.68; p < 0.001). Total deaths = 214.",
                "[Results, Fig 1]": "Kaplan-Meier overall survival curve for tamoxifen vs no tamoxifen."
            }
        )

    def test_gate_a_strips_inline_brackets(self):
        draft = "Overall survival improved dramatically with HR = 0.50 [Results, Table 2] and remained significant."
        quote = "Overall survival improved dramatically with HR = 0.50 and remained significant."
        self.assertTrue(CommentaryAndQCEngine._verify_quote_in_draft(quote, draft))

    def test_gate_a_ellipsis_and_token_overlap(self):
        draft = "In this pooled cohort of 878 women, medication adherence was completely untracked across both trials."
        ellipsis_quote = "In this pooled cohort of 878 women ... medication adherence was completely untracked"
        self.assertTrue(CommentaryAndQCEngine._verify_quote_in_draft(ellipsis_quote, draft))

        strawman = "The randomized trial demonstrated a 40% reduction in myocardial infarction with aspirin."
        self.assertFalse(CommentaryAndQCEngine._verify_quote_in_draft(strawman, draft))

    def test_gate_b_fuzzy_table_fig_abstract_resolution(self):
        anchors = self.doc.all_anchors
        self.assertEqual(CommentaryAndQCEngine._resolve_citation_anchor("Table 2", anchors), "[Results, Table 2]")
        self.assertEqual(CommentaryAndQCEngine._resolve_citation_anchor("[Res, Table 2]", anchors), "[Results, Table 2]")
        self.assertEqual(CommentaryAndQCEngine._resolve_citation_anchor("[Figure 1]", anchors), "[Results, Fig 1]")
        self.assertEqual(CommentaryAndQCEngine._resolve_citation_anchor("[Abs, Results]", anchors), "[Abstract, Results]")
        self.assertEqual(CommentaryAndQCEngine._resolve_citation_anchor("[Res, p6]", anchors), "[Results, Para 6]")

    def test_gate_b_tier3_fw_c_observational_preserved(self):
        payload = {
            "confidence_tag": "High Certainty",
            "overall_integrity": "CAUTION",
            "audit_status": "ISSUES_DETECTED",
            "summary_verdict": "Observational confounding caveat required.",
            "discrepancies": [
                {
                    "scope": "HOLISTIC_OR_OMISSION",
                    "category": "CAUSAL_OVERREACH",
                    "severity": "YELLOW",
                    "quoted_claim": "Tamoxifen directly causes lower recurrence in good-risk DCIS.",
                    "manuscript_evidence": "Exposure allocation was non-randomized.",
                    "citations": [],
                    "triage_rule_ref": None,
                    "suggested_edit": "Tamoxifen was associated with lower recurrence."
                }
            ],
            "verified_claims": [{"claim": f"Claim {i}", "citations": ["[Results, Table 2]"]} for i in range(15)],
            "publish_readiness": {"verdict": "Fix causal verb.", "pre_publish_fixes": ["Soften causal verb."]}
        }
        res = self.engine._postprocess_audit_output(
            raw_output=json.dumps(payload),
            used_model="gemini-3.8-flash",
            indexed_doc=self.doc,
            appraisal_markdown="",
            commentary_text="Tamoxifen directly causes lower recurrence in good-risk DCIS.",
            framework_id="FW_C",
            framework_name="Observational Study / Real-World Evidence",
            applicable_rules=[]
        )
        self.assertEqual(res["overall_integrity"], "CAUTION")
        self.assertEqual(len(res["discrepancies"]), 1)
        self.assertEqual(res["quarantined_count"], 0)
        # verified_claims capped at 10
        self.assertEqual(len(res["verified_claims"]), 10)

    def test_parse_failure_returns_audit_error_not_verified(self):
        res = self.engine._postprocess_audit_output(
            raw_output="{truncated invalid json",
            used_model="gemini-3.8-flash",
            indexed_doc=self.doc,
            appraisal_markdown="Test appraisal",
            commentary_text="Test commentary"
        )
        self.assertEqual(res["overall_integrity"], "AUDIT_ERROR")
        self.assertEqual(res["audit_status"], "AUDIT_ERROR")
        self.assertEqual(res["status"], "parse_error")


if __name__ == "__main__":
    unittest.main()
