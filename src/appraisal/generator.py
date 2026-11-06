import os
import re
import json
import time
import requests
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv

from src.ingestion.indexer import IndexedDocument, parse_and_index_pdf
from src.triage.classifier import TriageEngine, TriageResult
from src.appraisal.sanitizer import sanitize_and_verify_appraisal, SanitizationResult

load_dotenv(r"D:\SSD-Drive\Antigravity\ResearchEval\.env")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Model Hierarchy (Verified endpoints in order of preference & active responsiveness)
# Primary: gemini-3.8-flash (Active GA, Google's flagship flash model for autonomous reasoning & software analysis)
# Fallback: gemini-3.5-flash-lite (Active low-latency high-throughput Flash-Lite)
# Preview Fallback: gemini-3-flash-preview
MODEL_HIERARCHY = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview"
]
PRIMARY_MODEL = MODEL_HIERARCHY[0]
PRO_REASONING_MODEL = "gemini-3.8-flash"

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
        
        # Collect only triggered rules and format for injection
        active_rules = []
        for rid in triage.applicable_rules:
            if rid in self.rulesdb:
                r = self.rulesdb[rid]
                src_filename = os.path.basename(r.get("source_file", ""))
                active_rules.append({
                    "rule_id": r["rule_id"],
                    "target_domain": r.get("target_domain", ""),
                    "citation": f"{r.get('source_item', '')} ({src_filename}, p. {r.get('source_page', '')})",
                    "directional_bias": r.get("directional_bias", ""),
                    "appraisal_action": r.get("appraisal_action", "")
                })
        
        # Assemble relevant lexicon definitions
        relevant_lexicon = []
        doc_raw_lower = indexed_doc.raw_text.lower()
        for entry in self.lexicondb:
            if entry["term"].lower() in doc_raw_lower:
                relevant_lexicon.append(entry)
                
        # System instructions
        system_instruction = (
            "You are an Expert Clinical Research Appraiser acting as an objective, trusted colleague to a busy general clinician.\n"
            "Your task is to deconstruct, critically appraise, and synthesize medical research with clinical objectivity and precision.\n\n"
            "MANDATORY EXECUTION DIRECTIVES:\n"
            "1. You MUST follow the exact markdown heading structure provided in the schema. Start with '# Article Title' (using the real title of the study, NEVER enclosing the title in square brackets like '[Title]').\n"
            "2. Follow immediately with '## Clinical Bottom Line': provide a direct, interpretive takeaway synthesizing clinical findings and validity caveats (not just a descriptive summary).\n"
            "3. In '## Results in Context': Extract EXACT quantitative figures (e.g., exact Odds Ratios, Hazard Ratios, 95% Confidence Intervals, p-values, NNT/ARR) for ALL major endpoints or biomarkers. Do not speak in vague generalities.\n"
            "4. Provide brief, clear plain-language definitions of key statistical metrics used (e.g., Odds Ratio, Hazard Ratio, I^2).\n"
            "5. In '## Assertive Critical Appraisal': Actively critique the study's methods against the triggered bias frameworks. Every critical appraisal point MUST cite the relevant rule ID (e.g. {R_ROB2_D1_RANDOMIZATION}, {R_NI_DUAL_ANALYSIS}) and an exact manuscript coordinate anchor. STRICT RULE: You are FORBIDDEN from applying arbitrary external thresholds or cut-offs not specified in the injected rules (for example, do not invent percentage cut-offs for missing data, or require Grade 3-5 only for harms).\n"
            "6. Ground EVERY factual claim, statistic, and methodological observation with an exact inline source coordinate anchor from the body of the paper (e.g., [Abstract, Para 1], [Methods, Para 4], [Results, Table 2], [Results, Para 6], [Discussion, Para 12]). Never invent coordinates.\n"
            "   INDIVIDUAL ANCHORS ONLY: Each citation MUST be an exact single coordinate anchor. NEVER combine multiple numbers into one bracket like '[Methods, Para 1, 13]' or '[Results, Para 2, 4]'. If citing multiple paragraphs, write them as separate individual brackets: '[Methods, Para 1] [Methods, Para 13]'.\n"
            "   CRITICAL GROUNDING ACCURACY: Before attaching an anchor to a claim or statistic, verify that the cited text block DIRECTLY contains the exact words, findings, or numbers cited. Do NOT cite [Doc_Header] for study findings, statistics, or methodology; [Doc_Header] is ONLY for bibliographic metadata (Title, Authors, Journal, DOI). Do NOT cite an unrelated paragraph (such as an administrative IRB consent paragraph) when making a claim about bias, confounding, or treatment selection.\n"
            "7. In '## Bibliographic Data': Accurately extract Title, Authors, Journal, Year, and DOI / PubMed ID from [Doc_Header]. Ground them with [Doc_Header]. Always format the DOI / PubMed ID as a full live URL (e.g., https://doi.org/10.xxxx/xxxx or https://pubmed.ncbi.nlm.nih.gov/xxxx/). If authors, journal, year, or DOI/PMID are present in [Doc_Header], extract them and never state 'Not specified'.\n"
            "8. FORMATTING & MATHEMATICAL NOTATION: Do NOT use LaTeX math formatting, dollar signs ($...$ or $$...$$), or LaTeX macros like \\text{}, \\beta, \\alpha, \\gamma, \\pm, \\ge. Always write in standard clinical English with standard Unicode symbols when needed (e.g., n = 19, p < 0.05, 1 - β, α = 0.05, CD8⁺, CD4⁺, IFN-γ, ±, ×, ≥, ≤). Never enclose variables, sample sizes, or formulas in dollar signs.\n"
            "9. STRICT NEGATIVE CONSTRAINTS: NO medical disclaimers, NO conversational greetings, pleasantries, or closing sign-offs, and NO therapeutic practice mandates beyond what the source study evaluated.\n"
            "10. MANDATORY METHODOLOGICAL AUDIT BLOCK:\n"
            "At the very end of your response, strictly AFTER '## Bibliographic Data', you MUST output a structured JSON block enclosed in ```methodological_audit ... ``` evaluating each active rule in '### APPLICABLE METHODOLOGICAL RULES'.\n"
            "Each item in the JSON array must strictly follow this format:\n"
            "[\n"
            "  {\n"
            "    \"rule_id\": \"<exact_rule_id>\",\n"
            "    \"status\": \"PASS\" | \"FAIL\" | \"NOT_AVAILABLE\",\n"
            "    \"verdict_title\": \"<short 3-5 word headline>\",\n"
            "    \"explanation\": \"<1-2 concise sentences explaining compliance, deviation, or missing data>\",\n"
            "    \"citations\": [\"<coordinate_anchor>\", ...]\n"
            "  }\n"
            "]\n"
            "RULES FOR STATUS:\n"
            "- 'PASS': Study explicitly fulfilled criteria, minimized bias, or adhered to reporting guidelines.\n"
            "- 'FAIL': Study exhibited identifiable risk of bias, deviation, confounding, or guideline breach.\n"
            "- 'NOT_AVAILABLE': Manuscript omitted or failed to state necessary methodological details.\n"
        )
        
        # Scoped prompt content
        user_prompt = f"""### EVALUATION FRAMEWORK: {triage.primary_framework_id} ({triage.framework_name})
### REQUIRED HEADING STRUCTURE:
{json.dumps(fw_schema.get("headings", []), indent=2)}

### MANDATORY APPRAISAL CRITERIA:
{json.dumps(fw_schema.get("mandatory_elements", []), indent=2)}

### APPLICABLE METHODOLOGICAL RULES (RoB 2, CONSORT, STROBE, etc.):
{json.dumps(active_rules, indent=2)}
(Note: You MUST evaluate each active rule above in the final ```methodological_audit JSON array)

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

    def _invoke_gemini_rest(
        self,
        prompt: str,
        system_instruction: str,
        preferred_model: Optional[str] = None,
        thinking_level: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """Invoke Gemini via direct REST call with automated model fallback and optional thought capture."""
        models_to_try = [preferred_model] if preferred_model else []
        for m in MODEL_HIERARCHY:
            if m not in models_to_try:
                models_to_try.append(m)
                
        effective_thinking = thinking_level or os.getenv("GEMINI_APPRAISAL_THINKING_LEVEL", "low")

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
            if effective_thinking:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": effective_thinking
                }
            try:
                resp = requests.post(url, json=payload, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        text_parts = [p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)]
                        thought_parts = [p.get("text", "") for p in parts if p.get("thought", False)]
                        return "".join(text_parts), "".join(thought_parts), model
                else:
                    last_error = f"Model {model} returned HTTP {resp.status_code}: {resp.text[:200]}"
                    print(f"[SynthesisEngine] Warning: {last_error}. Falling back to next model...")
            except Exception as e:
                last_error = f"Model {model} failed: {str(e)}"
                print(f"[SynthesisEngine] Warning: {last_error}. Falling back to next model...")
                
        raise RuntimeError(f"All Gemini models in hierarchy failed. Last error: {last_error}")

    def _build_fallback_evaluations(
        self,
        active_rules: List[Dict[str, Any]],
        reason: str
    ) -> List[Dict[str, Any]]:
        """Construct safe fallback evaluation entries with PENDING status."""
        fallbacks = []
        for r in active_rules:
            fallbacks.append({
                "rule_id": r.get("rule_id", ""),
                "target_domain": r.get("target_domain", ""),
                "citation": r.get("citation", ""),
                "directional_bias": r.get("directional_bias", ""),
                "appraisal_action": r.get("appraisal_action", ""),
                "status": "PENDING",
                "verdict_title": "Evaluation Pending",
                "explanation": reason,
                "citations": []
            })
        return fallbacks

    def _extract_and_excise_audit_block(
        self,
        raw_output: str,
        active_rules: List[Dict[str, Any]]
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Extract and excise the structured methodological audit block BEFORE coordinate sanitization.
        Uses non-greedy matching from '[' to ']' and graceful fallback to PENDING status upon failure.
        """
        if not raw_output:
            return "", self._build_fallback_evaluations(active_rules, "Empty response received.")

        audit_json_str: Optional[str] = None
        excised_markdown: str = raw_output

        # Strategy 1: Non-greedy fenced block matching (```methodological_audit or ```json)
        fence_match = re.search(
            r'```(?:methodological_audit|json)?\s*(\[\s*\{[\s\S]*?\}\s*\])\s*```?',
            raw_output,
            re.IGNORECASE
        )
        if fence_match:
            audit_json_str = fence_match.group(1).strip()
            # Excise the entire fenced block from the residual markdown
            excised_markdown = (raw_output[:fence_match.start()] + raw_output[fence_match.end():]).strip()
        else:
            # Strategy 2: Look for fence header or tag if closing fence was truncated
            fence_tag_match = re.search(r'```(?:methodological_audit|json)?\s*(\[[\s\S]*)$', raw_output, re.IGNORECASE)
            if fence_tag_match:
                candidate_str = fence_tag_match.group(1).strip()
                # Find matching closing bracket or fallback
                closing_bracket_idx = candidate_str.rfind("]")
                if closing_bracket_idx != -1:
                    audit_json_str = candidate_str[:closing_bracket_idx + 1]
                else:
                    # Token exhaustion cut off before closing ']'; close after last '}'
                    last_brace_idx = candidate_str.rfind("}")
                    if last_brace_idx != -1:
                        audit_json_str = candidate_str[:last_brace_idx + 1] + "\n]"
                excised_markdown = raw_output[:fence_tag_match.start()].strip()

        # Parse the JSON payload defensively with fallback
        parsed_items: Optional[List[Dict[str, Any]]] = None
        if audit_json_str:
            try:
                parsed = json.loads(audit_json_str)
                if isinstance(parsed, list):
                    parsed_items = parsed
            except Exception:
                # Attempt minor repair: remove trailing commas before } or ]
                try:
                    repaired = re.sub(r',\s*([\]\}])', r'\1', audit_json_str)
                    parsed = json.loads(repaired)
                    if isinstance(parsed, list):
                        parsed_items = parsed
                except Exception as parse_err:
                    print(f"[SynthesisEngine] Warning: Audit JSON parse failed: {parse_err}")
                    parsed_items = None

        if not parsed_items:
            return excised_markdown, self._build_fallback_evaluations(
                active_rules,
                "Evaluation omitted or truncated during synthesis."
            )

        # Map parsed evaluations by rule_id
        eval_by_id = {}
        for item in parsed_items:
            if isinstance(item, dict) and "rule_id" in item:
                eval_by_id[str(item["rule_id"]).strip()] = item

        evaluations: List[Dict[str, Any]] = []
        for r in active_rules:
            rid = str(r.get("rule_id", "")).strip()
            if rid in eval_by_id:
                ev = eval_by_id[rid]
                raw_status = str(ev.get("status", "NOT_AVAILABLE")).upper().strip()
                if raw_status not in ("PASS", "FAIL", "NOT_AVAILABLE"):
                    raw_status = "NOT_AVAILABLE"
                
                citations = ev.get("citations", [])
                if not isinstance(citations, list):
                    citations = [str(citations)] if citations else []

                evaluations.append({
                    "rule_id": rid,
                    "target_domain": r.get("target_domain", ""),
                    "citation": r.get("citation", ""),
                    "directional_bias": r.get("directional_bias", ""),
                    "appraisal_action": r.get("appraisal_action", ""),
                    "status": raw_status,
                    "verdict_title": str(ev.get("verdict_title", "")).strip(),
                    "explanation": str(ev.get("explanation", "")).strip(),
                    "citations": citations
                })
            else:
                evaluations.append({
                    "rule_id": rid,
                    "target_domain": r.get("target_domain", ""),
                    "citation": r.get("citation", ""),
                    "directional_bias": r.get("directional_bias", ""),
                    "appraisal_action": r.get("appraisal_action", ""),
                    "status": "PENDING",
                    "verdict_title": "Evaluation Pending",
                    "explanation": "Rule was not evaluated in the synthesized response.",
                    "citations": []
                })

        return excised_markdown, evaluations

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
                "active_rules_detail": payload["active_rules"],
                "rule_evaluations": self._build_fallback_evaluations(payload["active_rules"], "API key needed for live inference."),
                "lexicon_terms_count": len(payload["relevant_lexicon"]),
                "payload": payload
            }
            
        # Step 2: Invoke verified Gemini endpoint
        thinking_lvl = os.getenv("GEMINI_APPRAISAL_THINKING_LEVEL", "low")
        raw_output, thought_output, used_model = self._invoke_gemini_rest(
            prompt=payload["user_prompt"],
            system_instruction=payload["system_instruction"],
            preferred_model=model_override,
            thinking_level=thinking_lvl
        )
        
        # Step 3: Extract and excise audit block BEFORE coordinate sanitization
        residual_markdown, rule_evaluations = self._extract_and_excise_audit_block(
            raw_output=raw_output,
            active_rules=payload["active_rules"]
        )
        
        # Step 4: Sanitize and verify coordinate anchors on residual markdown ONLY
        sanitization = sanitize_and_verify_appraisal(residual_markdown, indexed_doc.all_anchors)
        
        return {
            "status": "success",
            "selected_model": used_model,
            "thinking_level": thinking_lvl,
            "triage": triage.model_dump(),
            "active_rules_detail": payload["active_rules"],
            "rule_evaluations": rule_evaluations,
            "sanitization": sanitization.model_dump(),
            "raw_output": raw_output,
            "thought_output": thought_output,
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

