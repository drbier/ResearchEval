import os
import json
import time
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from src.ingestion.indexer import IndexedDocument, parse_and_index_pdf
from src.triage.classifier import TriageEngine, TriageResult
from src.appraisal.sanitizer import sanitize_and_verify_appraisal, SanitizationResult

load_dotenv(r"D:\SSD-Drive\Antigravity\ResearchEval\.env")

# Model Hierarchy (Verified endpoints in order of preference & active responsiveness)
MODEL_HIERARCHY = [
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.8-flash",
    "gemini-3.1-pro-preview"
]
PRIMARY_MODEL = MODEL_HIERARCHY[0]
PRO_REASONING_MODEL = "gemini-3.1-pro-preview"

class SynthesisEngine:
    def __init__(self, data_dir: str, api_key: Optional[str] = None):
        self.data_dir = data_dir
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
        self.triage_engine = TriageEngine(data_dir)
        self.schemadb = self._load_json(os.path.join(data_dir, "schemadb.json"))
        self.rulesdb = {r["rule_id"]: r for r in self._load_json(os.path.join(data_dir, "rulesdb.json"))}
        self.lexicondb = self._load_json(os.path.join(data_dir, "lexicondb.json"))

    def _load_json(self, path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def assemble_prompt_payload(self, indexed_doc: IndexedDocument, triage: TriageResult) -> Dict[str, Any]:
        """Construct the strictly scoped context injection payload."""
        fw_schema = self.schemadb.get(triage.primary_framework_id, {})
        
        # Collect only triggered rules
        active_rules = [self.rulesdb[rid] for rid in triage.applicable_rules if rid in self.rulesdb]
        
        # Assemble relevant lexicon definitions
        relevant_lexicon = []
        doc_raw_lower = indexed_doc.raw_text.lower()
        for entry in self.lexicondb:
            if entry["term"].lower() in doc_raw_lower:
                relevant_lexicon.append(entry)
                
        # System instructions
        system_instruction = (
            "You are an Expert Clinical Research Appraiser acting as an objective peer to medical clinicians.\n"
            "Your task is to produce a rigorous, structured analytical appraisal of the provided primary medical document.\n\n"
            "STRICT RULES:\n"
            "1. You MUST follow the exact markdown heading structure provided in the schema.\n"
            "2. Ground EVERY factual claim, baseline comparison, and statistical outcome with an exact inline source coordinate anchor (e.g. [Methods, Para 3], [Results, Table 2], [Doc_Header]). Never invent coordinates.\n"
            "3. Follow all mandatory appraisal actions for the triggered methodological rules.\n"
            "4. NEVER generate medical disclaimers (e.g., 'This is for informational purposes only...').\n"
            "5. NEVER generate conversational greetings, filler, or sign-offs.\n"
            "6. NEVER issue clinical therapy mandates beyond what the source study evaluated.\n"
        )
        
        # Scoped prompt content
        user_prompt = f"""### EVALUATION FRAMEWORK: {triage.primary_framework_id} ({triage.framework_name})
### REQUIRED HEADING STRUCTURE:
{json.dumps(fw_schema.get("headings", []), indent=2)}

### MANDATORY APPRAISAL CRITERIA:
{json.dumps(fw_schema.get("mandatory_elements", []), indent=2)}

### APPLICABLE METHODOLOGICAL RULES (RoB 2, CONSORT, STROBE, etc.):
{json.dumps(active_rules, indent=2)}

### RELEVANT STATISTICAL DEFINITIONS & CAVEATS:
{json.dumps(relevant_lexicon, indent=2)}

### INDEXED DOCUMENT TEXT WITH COORDINATE ANCHORS:
Doc Header:
{indexed_doc.doc_header}

Anchors & Text:
"""
        # Append anchors and text
        for anchor_id, text in indexed_doc.all_anchors.items():
            if anchor_id != "[Doc_Header]":
                user_prompt += f"\n{anchor_id}\n{text}\n"

        return {
            "system_instruction": system_instruction,
            "user_prompt": user_prompt,
            "triage": triage,
            "active_rules": active_rules,
            "relevant_lexicon": relevant_lexicon
        }

    def _invoke_gemini_rest(self, prompt: str, system_instruction: str, preferred_model: Optional[str] = None) -> Tuple[str, str]:
        """Invoke Gemini via direct REST call with automated model fallback."""
        models_to_try = [preferred_model] if preferred_model else []
        for m in MODEL_HIERARCHY:
            if m not in models_to_try:
                models_to_try.append(m)
                
        last_error = ""
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 8192
                }
            }
            try:
                resp = requests.post(url, json=payload, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        text_parts = [p.get("text", "") for p in parts if "text" in p]
                        return "".join(text_parts), model
                else:
                    last_error = f"Model {model} returned HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as e:
                last_error = f"Model {model} failed: {str(e)}"
                
        raise RuntimeError(f"All Gemini models in hierarchy failed. Last error: {last_error}")

    def generate_appraisal(self, indexed_doc: IndexedDocument, model_override: Optional[str] = None) -> Dict[str, Any]:
        """Execute end-to-end appraisal generation and validation."""
        # Step 1: Triage
        abstract_methods = ""
        for sec in ["Abstract", "Methods"]:
            if sec in indexed_doc.sections:
                for a in indexed_doc.sections[sec]:
                    abstract_methods += f"{a.text}\n"
                    
        triage = self.triage_engine.classify_text(indexed_doc.doc_header, abstract_methods)
        payload = self.assemble_prompt_payload(indexed_doc, triage)
        
        if not self.api_key:
            return {
                "status": "ready_for_inference_key_needed",
                "selected_model": model_override or PRIMARY_MODEL,
                "triage": triage.model_dump(),
                "prompt_length_chars": len(payload["user_prompt"]),
                "active_rules_count": len(payload["active_rules"]),
                "lexicon_terms_count": len(payload["relevant_lexicon"]),
                "payload": payload
            }
            
        # Step 2: Invoke verified Gemini endpoint
        raw_output, used_model = self._invoke_gemini_rest(
            prompt=payload["user_prompt"],
            system_instruction=payload["system_instruction"],
            preferred_model=model_override
        )
        
        # Step 3: Sanitize and verify coordinate anchors
        sanitization = sanitize_and_verify_appraisal(raw_output, indexed_doc.all_anchors)
        
        return {
            "status": "success",
            "selected_model": used_model,
            "triage": triage.model_dump(),
            "sanitization": sanitization.model_dump(),
            "raw_output": raw_output,
            "final_markdown": sanitization.cleaned_markdown
        }

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    data_dir = r"D:\SSD-Drive\Antigravity\ResearchEval\data"
    engine = SynthesisEngine(data_dir)
    
    test_pdf = r"D:\SSD-Drive\Antigravity\ResearchEval\Reference_papers\2.Statistics\Interpreting_the_results_of_noninferiority_trials-.pdf"
    indexed = parse_and_index_pdf(test_pdf)
    res = engine.generate_appraisal(indexed)
    print("Generation Pipeline Check:")
    print("Status:", res["status"])
    print("Selected Model:", res["selected_model"])
    print("Framework:", res["triage"]["primary_framework_id"], "-", res["triage"]["framework_name"])
    print("Prompt Chars:", res["prompt_length_chars"])
    print("Active Rules:", res["active_rules_count"])

