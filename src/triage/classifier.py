import os
import json
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class TriageResult(BaseModel):
    primary_framework_id: str
    framework_name: str
    confidence: float
    matched_triggers: List[str] = Field(default_factory=list)
    sub_feature_tags: List[str] = Field(default_factory=list)
    applicable_rules: List[str] = Field(default_factory=list)
    rationale: str


def evaluate_trigger_ast(trigger: Dict[str, Any], framework_id: str, tags: List[str]) -> bool:
    """
    Deterministic AST evaluator for structured boolean conditions in rulesdb.json.
    Supports:
      - 'framework': exact match (e.g. 'FW_A')
      - 'frameworks': membership match (e.g. ['FW_A', 'FW_F'])
      - 'tag': tag presence (e.g. '+TAG_CONSORT_PRO')
      - 'tags': any tag presence from list
      - 'all': logical AND of child conditions
      - 'any': logical OR of child conditions
      - 'none': logical NOT (none of child conditions may be true)
    """
    if not trigger:
        return True

    def check_node(node: Dict[str, Any]) -> bool:
        if "framework" in node and node["framework"] != framework_id:
            return False
        if "frameworks" in node and framework_id not in node["frameworks"]:
            return False
        if "tag" in node and node["tag"] not in tags:
            return False
        if "tags" in node and not any(t in tags for t in node["tags"]):
            return False
        if "all" in node and node["all"]:
            if not all(check_node(c) for c in node["all"]):
                return False
        if "any" in node and node["any"]:
            if not any(check_node(c) for c in node["any"]):
                return False
        if "none" in node and node["none"]:
            if any(check_node(c) for c in node["none"]):
                return False
        return True

    return check_node(trigger)


class TriageEngine:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.triage_matrix = self._load_json(os.path.join(data_dir, "triagedb.json"))
        self.rules_db = self._load_json(os.path.join(data_dir, "rulesdb.json"))
        
    def _load_json(self, path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def classify_text(self, doc_header: str, abstract_and_methods: str) -> TriageResult:
        """
        Two-stage deterministic triage classifier with precedence ladder:
        Stage 1: Design declaration scoping for exclusion filtering.
        Stage 2: Full-text feature scoring and precedence ladder resolution.
        """
        full_text = f"{doc_header}\n{abstract_and_methods}".lower()
        
        # Stage 1: Design-declaration text (first 1500 chars of abstract/methods + header)
        # Exclusions are checked only here to prevent background citations from penalizing trials
        design_scope_text = f"{doc_header}\n{abstract_and_methods[:1500]}".lower()

        scores: Dict[str, int] = {}
        matched_trigs: Dict[str, List[str]] = {}

        # Sort triage matrix by hierarchy rank
        matrix_sorted = sorted(self.triage_matrix, key=lambda x: x.get("hierarchy_rank", 99))

        for fw in matrix_sorted:
            fw_id = fw["framework_id"]
            scores[fw_id] = 0
            matched_trigs[fw_id] = []

            # Check design exclusions strictly against design scope
            exclusions = fw.get("design_exclusions", fw.get("exclusions", []))
            for excl in exclusions:
                if re.search(r'\b' + re.escape(excl.lower()) + r'\b', design_scope_text):
                    scores[fw_id] -= 10

            # Match triggers across full text
            for trig in fw.get("triggers", []):
                if re.search(r'\b' + re.escape(trig.lower()) + r'\b', full_text):
                    scores[fw_id] += 3
                    matched_trigs[fw_id].append(trig)

        # Precedence Ladder Overrides:
        # 1. Clinical Trial Protocol (FW_E): Explicit protocol declarations without primary results
        is_protocol = any(k in design_scope_text for k in [
            "study protocol", "trial protocol", "protocol for a", "statistical analysis plan",
            "spirit 2013", "rationale and design"
        ])
        has_completed_results = any(k in full_text for k in [
            "we report the results of", "primary outcome was observed in", "overall survival was significantly"
        ])
        if is_protocol and not has_completed_results:
            scores["FW_E"] += 25

        # 2. Systematic Review & Meta-Analysis (FW_B): PRISMA or meta-analysis
        if any(k in design_scope_text for k in ["systematic review", "meta-analysis", "prisma", "pooled analysis"]):
            scores["FW_B"] += 20

        # 3. Non-Inferiority RCT (FW_F): Non-inferiority trials
        if any(k in full_text for k in ["non-inferiority", "noninferiority", "non-inferior", "equivalence trial"]):
            if "random" in full_text:
                scores["FW_F"] += 20

        # 4. Diagnostic Accuracy (FW_D): Sensitivity/specificity against reference standard
        if any(k in design_scope_text for k in ["diagnostic accuracy", "index test", "reference standard", "stard 2015"]):
            scores["FW_D"] += 18

        # 5. Biomarker Study (FW_I): High biomarker density should route to FW_I even if cohort terminology is present
        biomarker_keywords = ["biomarker", "ctdna", "vaf", "mutation", "liquid biopsy", "immunohistochemistry", "assay validation", "genomic"]
        biomarker_hits = sum(1 for kw in biomarker_keywords if kw in full_text)
        is_biomarker_title = any(kw in doc_header.lower() for kw in ["biomarker", "genomic", "mutation", "ctdna"])
        
        if is_biomarker_title or biomarker_hits >= 3:
            scores["FW_I"] += 16
            # If it has cohort terminology, ensure FW_I wins over FW_C
            if scores.get("FW_C", 0) > 0 and scores.get("FW_I", 0) <= scores.get("FW_C", 0):
                scores["FW_I"] = scores.get("FW_C", 0) + 5

        # 6. Health Economics (FW_G): Cost-effectiveness / budget impact
        if any(k in full_text for k in ["cost-effectiveness", "cost-utility", "icer", "qaly", "markov model", "cheers"]):
            scores["FW_G"] += 15

        # 7. Survey Research (FW_J): Surveys and questionnaires
        if any(k in design_scope_text for k in ["survey", "questionnaire", "cross-sectional survey", "response rate"]):
            if "trial" not in design_scope_text and "systematic review" not in design_scope_text:
                scores["FW_J"] += 15

        # Resolve primary framework using scores and hierarchy rank
        best_fw_id = max(scores, key=lambda k: (scores[k], -next(f.get("hierarchy_rank", 99) for f in self.triage_matrix if f["framework_id"] == k)))
        best_fw = next(fw for fw in self.triage_matrix if fw["framework_id"] == best_fw_id)

        # Step 2: Detect Sub-Feature Tags
        detected_tags: List[str] = []
        
        tag_heuristics = {
            "+TAG_NON_INFERIORITY": ["non-inferiority", "noninferiority", "non-inferior", "per-protocol"],
            "+TAG_CONSORT_PRO": ["patient-reported", "quality of life", "hrqol", "prom", "proms", "eortc", "fact-", "pro-ctcae", "kccq", "eq-5d", "sf-36", "haq-di"],
            "+TAG_BIOMARKER": ["biomarker", "ctdna", "mutation", "ngs", "vaf", "liquid biopsy", "immunohistochemistry", "tumor marker"],
            "+TAG_CROSSOVER": ["cross-over", "crossover", "switched to", "subsequent therapy", "treatment switching"],
            "+TAG_SAFETY_HARMS": ["adverse events", "toxicities", "treatment-emergent", "grade 3", "grade 4", "discontinuation", "harms"],
            "+TAG_IMMUNOTHERAPY": ["irecist", "pembrolizumab", "nivolumab", "atezolizumab", "checkpoint inhibitor", "pd-1", "pd-l1", "ctla-4"],
            "+TAG_ONCOLOGY": ["overall survival", "progression-free", "recist", "tumor", "tumour", "hazard ratio", "metastatic", "cancer"],
            "+TAG_SUBGROUP": ["subgroup", "post-hoc", "sub-analysis", "interaction test", "heterogeneity of treatment effect"],
            "+TAG_LIQUID_BIOPSY_CTDNA": ["ctdna", "liquid biopsy", "cell-free dna", "cfdna", "vaf", "chip mutation"],
            "+TAG_COMPOSITE": ["composite endpoint", "composite outcome", "mace", "disease-free survival", "event-free survival"],
            "+TAG_COHORT": ["cohort", "cohort study", "longitudinal follow-up", "registry cohort", "population-based cohort"],
            "+TAG_EHR_CLAIMS": ["electronic health records", "ehr", "claims database", "administrative data", "registry linkage", "icd-9", "icd-10"],
            "+TAG_SURVEY": ["survey", "questionnaire", "likert scale", "response rate", "respondents"],
            "+TAG_IMMORTAL_TIME_RISK": ["immortal time", "time-dependent covariate", "landmark analysis", "time from diagnosis to treatment"],
            "+TAG_CARDIOLOGY": ["cardiovascular", "mace", "heart failure", "myocardial infarction", "ejection fraction", "lvef", "kccq", "nyha", "stemi", "revascularization"],
            "+TAG_NEPHROLOGY": ["egfr", "kidney disease", "renal", "proteinuria", "creatinine", "esrd", "dialysis", "nephropathy"],
            "+TAG_NEUROLOGY": ["edss", "multiple sclerosis", "stroke", "nihss", "disability progression", "relapse rate", "parkinson", "alzheimer"],
            "+TAG_SURROGATE_ENDPOINT": ["surrogate endpoint", "surrogate", "progression-free", "pfs", "dfs", "event-free", "hba1c", "ldl-c", "blood pressure", "biomarker endpoint"]
        }
        
        for tag, keywords in tag_heuristics.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', full_text):
                    if tag not in detected_tags:
                        detected_tags.append(tag)
                    break

        # Step 3: Resolve applicable rules from rulesdb.json using structured AST evaluation
        applicable_rules: List[str] = []
        for rule in self.rules_db:
            rule_id = rule["rule_id"]
            trigger = rule.get("trigger")
            legacy_cond = rule.get("trigger_condition")

            match = False
            if trigger:
                match = evaluate_trigger_ast(trigger, best_fw_id, detected_tags)
            elif legacy_cond:
                # Fallback backward-compatibility for legacy condition strings
                if f"framework_id == '{best_fw_id}'" in legacy_cond:
                    match = True
                elif f"'{best_fw_id}'" in legacy_cond and "framework_id in" in legacy_cond:
                    match = True
                for tag in detected_tags:
                    if f"'{tag}'" in legacy_cond:
                        match = True
                        break

            if match and rule_id not in applicable_rules:
                applicable_rules.append(rule_id)

        # Build descriptive rationale
        top_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top_summary = ", ".join([f"{k}: {v}" for k, v in top_candidates if v > 0])
        rationale = (
            f"Classified as {best_fw_id} ({best_fw['name']}) with score {scores[best_fw_id]} "
            f"(Top candidates: {top_summary}). "
            f"Triggered {len(detected_tags)} sub-tags and {len(applicable_rules)} appraisal rules."
        )

        return TriageResult(
            primary_framework_id=best_fw_id,
            framework_name=best_fw["name"],
            confidence=min(1.0, max(0.5, scores[best_fw_id] / 20.0)),
            matched_triggers=matched_trigs[best_fw_id],
            sub_feature_tags=detected_tags,
            applicable_rules=applicable_rules,
            rationale=rationale
        )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    data_dir = r"D:\SSD-Drive\Antigravity\ResearchEval\data"
    engine = TriageEngine(data_dir)
    sample_header = "Interpreting the results of noninferiority trials—a review. Clinical Studies. Jack Cuzick"
    sample_methods = "Noninferiority trials are becoming increasingly common. Both per-protocol and intention-to-treat analysis are required. Non-inferiority margin delta."
    res = engine.classify_text(sample_header, sample_methods)
    print("Classification result:")
    print(res.model_dump_json(indent=2))
