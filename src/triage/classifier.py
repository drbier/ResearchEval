import os
import json
import re
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field

class TriageResult(BaseModel):
    primary_framework_id: str
    framework_name: str
    confidence: float
    matched_triggers: List[str] = Field(default_factory=list)
    sub_feature_tags: List[str] = Field(default_factory=list)
    applicable_rules: List[str] = Field(default_factory=list)
    rationale: str

class TriageEngine:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.triage_matrix = self._load_json(os.path.join(data_dir, "triagedb.json"))
        self.rules_db = self._load_json(os.path.join(data_dir, "rulesdb.json"))
        
    def _load_json(self, path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def classify_text(self, doc_header: str, abstract_and_methods: str) -> TriageResult:
        """Deterministic heuristic & keyword classification matrix."""
        eval_text = f"{doc_header}\n{abstract_and_methods}".lower()
        
        scores: Dict[str, int] = {}
        matched_trigs: Dict[str, List[str]] = {}
        
        # Step 1: Score each framework
        for fw in self.triage_matrix:
            fw_id = fw["framework_id"]
            scores[fw_id] = 0
            matched_trigs[fw_id] = []
            
            # Check exclusions first
            excluded = False
            for excl in fw.get("exclusions", []):
                # Only exclude if high-confidence exact phrase appears in header/abstract
                if re.search(r'\b' + re.escape(excl.lower()) + r'\b', eval_text):
                    # Negative penalty or flag
                    scores[fw_id] -= 5
            
            # Check triggers
            for trig in fw.get("triggers", []):
                if re.search(r'\b' + re.escape(trig.lower()) + r'\b', eval_text):
                    scores[fw_id] += 2
                    matched_trigs[fw_id].append(trig)
                    
        # Check explicit priority patterns:
        # 1. Non-inferiority trials mention 'randomized' but MUST resolve to FW_F
        if "non-inferiority" in eval_text or "noninferiority" in eval_text or "non-inferior" in eval_text:
            scores["FW_F"] += 15
            
        # 2. Systematic review PRISMA flow mentions must prioritize FW_B over others
        if "systematic review" in eval_text or "meta-analysis" in eval_text or "prisma" in eval_text:
            scores["FW_B"] += 15

        # 3. Observational/Cohort studies with biomarker keywords should map to FW_C (with +TAG_BIOMARKER)
        if ("cohort study" in eval_text or "cohort" in eval_text or "prospective study" in eval_text or "follow-up" in eval_text) and "random" not in eval_text:
            scores["FW_C"] += 12
            
        # Sort frameworks by score
        best_fw_id = max(scores, key=scores.get)
        best_fw = next(fw for fw in self.triage_matrix if fw["framework_id"] == best_fw_id)
        
        # Step 2: Detect Sub-Feature Tags
        detected_tags: List[str] = []
        
        tag_heuristics = {
            "+TAG_NON_INFERIORITY": ["non-inferiority", "noninferiority", "non-inferior", "per-protocol"],
            "+TAG_CONSORT_PRO": ["patient-reported", "quality of life", "hrqol", "prom", "eortc", "fact-"],
            "+TAG_BIOMARKER": ["biomarker", "ctdna", "mutation", "ngs", "vaf", "liquid biopsy", "immunohistochemistry"],
            "+TAG_CROSSOVER": ["cross-over", "crossover", "switched to", "subsequent therapy"],
            "+TAG_SAFETY_HARMS": ["adverse events", "toxicities", "treatment-emergent", "grade 3", "grade 4", "discontinuation"],
            "+TAG_IMMUNOTHERAPY": ["irecist", "pembrolizumab", "nivolumab", "atezolizumab", "checkpoint inhibitor", "pd-1", "pd-l1", "ctla-4"],
            "+TAG_ONCOLOGY": ["overall survival", "progression-free", "recist", "tumor", "tumour", "hazard ratio"],
            "+TAG_SUBGROUP": ["subgroup", "post-hoc", "sub-analysis", "interaction test"],
            "+TAG_LIQUID_BIOPSY_CTDNA": ["ctdna", "liquid biopsy", "cell-free dna", "cfdna"]
        }
        
        for tag, keywords in tag_heuristics.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', eval_text):
                    if tag not in detected_tags:
                        detected_tags.append(tag)
                    break
                    
        # Step 3: Resolve applicable rules from rulesdb.json
        applicable_rules: List[str] = []
        for rule in self.rules_db:
            rule_id = rule["rule_id"]
            cond = rule.get("trigger_condition", "")
            
            # Simple condition evaluator
            # e.g. "framework_id in ['FW_A', 'FW_F']" or "tags.contains('+TAG_CONSORT_PRO')"
            match = False
            if f"framework_id == '{best_fw_id}'" in cond:
                match = True
            elif f"'{best_fw_id}'" in cond and "framework_id in" in cond:
                match = True
            
            for tag in detected_tags:
                if f"'{tag}'" in cond:
                    match = True
                    break
                    
            if match and rule_id not in applicable_rules:
                applicable_rules.append(rule_id)
                
        return TriageResult(
            primary_framework_id=best_fw_id,
            framework_name=best_fw["name"],
            confidence=min(1.0, max(0.5, scores[best_fw_id] / 15.0)),
            matched_triggers=matched_trigs[best_fw_id],
            sub_feature_tags=detected_tags,
            applicable_rules=applicable_rules,
            rationale=f"Classified as {best_fw_id} ({best_fw['name']}) with score {scores[best_fw_id]}. Triggered {len(detected_tags)} sub-tags and {len(applicable_rules)} rules."
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

