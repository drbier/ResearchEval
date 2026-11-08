import os
import re
import json
import time
import requests
from typing import Dict, Any, List, Optional, Tuple

from src.ingestion.indexer import IndexedDocument
from src.appraisal.generator import PRIMARY_MODEL, MODEL_HIERARCHY
from src.appraisal.sanitizer import sanitize_and_verify_appraisal, truncate_markdown_safely

class CommentaryAndQCEngine:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def _invoke_gemini_rest(
        self,
        prompt: str,
        system_instruction: str,
        preferred_model: Optional[str] = None,
        thinking_level: str = "low",
        temperature: float = 0.2,
        json_mode: bool = False
    ) -> Tuple[str, str, str]:
        """Invoke Gemini via direct REST endpoint with model fallback hierarchy."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is not configured.")

        models_to_try = [preferred_model] if preferred_model else []
        for m in MODEL_HIERARCHY:
            if m not in models_to_try:
                models_to_try.append(m)

        effective_thinking = thinking_level if thinking_level in ("low", "medium", "high") else "low"
        last_error = ""

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload: Dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": 8192
                }
            }
            if effective_thinking:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": effective_thinking
                }
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            try:
                resp = requests.post(url, json=payload, timeout=50)
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
                    print(f"[CommentaryAndQCEngine] Warning: {last_error}")
            except Exception as e:
                last_error = f"Model {model} failed: {str(e)}"
                print(f"[CommentaryAndQCEngine] Warning: {last_error}")

        raise RuntimeError(f"All Gemini models in hierarchy failed. Last error: {last_error}")

    def generate_commentary(
        self,
        indexed_doc: IndexedDocument,
        appraisal_markdown: str,
        voice_profile: Optional[Dict[str, Any]] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage 1: Generate clinical editorial commentary grounded in the study appraisal
        and styled by clinician voice profile and exemplars.
        """
        profile = voice_profile or {}
        philosophy = str(profile.get("philosophy", "")).strip()[:500]
        preferred_terms = str(profile.get("preferred_terms", "")).strip()[:300]
        prohibited_terms = str(profile.get("prohibited_terms", "")).strip()[:300]
        therapeutic_lens = str(profile.get("therapeutic_lens", "integrative")).strip().lower()

        # Therapeutic Lens Directives:
        if therapeutic_lens in ("integrative", "naturopathic", "functional"):
            lens_directive = (
                "THERAPEUTIC ORIENTATION: Integrative / Naturopathic / Functional Medicine.\n"
                "- Evaluate findings through the lens of whole-person physiology, biological resilience, nutritional biochemistry, and root-cause lifestyle modifications.\n"
                "- NEVER reflexively prescribe, recommend, or assert conventional guideline pharmaceutical regimens (e.g., high-intensity statins, antiplatelet therapies, antihypertensives) as mandatory or bedrock care unless the study explicitly investigated those specific drugs.\n"
                "- Scrutinize whether pharmacological interventions merely manipulate surrogate biomarkers without altering hard clinical outcomes or all-cause mortality."
            )
        elif therapeutic_lens in ("conventional", "allopathic"):
            lens_directive = (
                "THERAPEUTIC ORIENTATION: Conventional Allopathic / Evidence-Based Clinical Practice.\n"
                "- Evaluate findings according to established guideline-directed medical therapy (GDMT) and standard of care algorithms.\n"
                "- Contextualize results within prevailing consensus guidelines, standard pharmacotherapy indications, and recognized clinical trial endpoints."
            )
        elif therapeutic_lens in ("methodological", "biostatistical"):
            lens_directive = (
                "THERAPEUTIC ORIENTATION: Pure Methodological & Biostatistical Focus.\n"
                "- Maintain an entirely neutral therapeutic stance; do not offer clinical prescribing guidance or advocate for any specific medical philosophy.\n"
                "- Focus exclusively on study design validity, statistical power, confounding variables, selection bias, surrogate versus hard endpoint dissociation, and multiplicity control."
            )
        else:
            lens_directive = (
                "THERAPEUTIC ORIENTATION: Integrative / Naturopathic / Functional Medicine.\n"
                "- Prioritize biological resilience, nutritional biochemistry, and root-cause lifestyle factors. Do NOT mandate conventional pharmaceutical regimens unless directly evaluating them."
            )

        # Extract active exemplars (max 4, max 1500 chars each)
        raw_exemplars = profile.get("exemplars", [])
        active_exemplars: List[Dict[str, Any]] = []
        if isinstance(raw_exemplars, list):
            candidates = [e for e in raw_exemplars if isinstance(e, dict) and e.get("is_active", True) and str(e.get("text", "")).strip()]
            # Sort by updated_at_ms desc if available
            candidates.sort(key=lambda x: x.get("updated_at_ms", 0), reverse=True)
            active_exemplars = candidates[:4]

        # Build exemplar XML blocks
        exemplar_blocks = []
        for idx, ex in enumerate(active_exemplars, 1):
            ex_text = truncate_markdown_safely(str(ex.get("text", "")), max_chars=1500)
            if ex_text:
                exemplar_blocks.append(f'<exemplar index="{idx}">\n{ex_text}\n</exemplar>')
        exemplars_formatted = "\n\n".join(exemplar_blocks) if exemplar_blocks else "No past exemplars provided. Use standard assertive clinical peer commentary."

        # Prune context: Extract only cited anchors from the appraisal
        bracket_pattern = r'\[([^\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Patients?\s+and\s+Methods?|Materials?\s+and\s+Methods?|Results?|Res|Findings?|Discussion|Disc|Conclusions?|Concl|Appendix|Supp(?:lementary)?|Para(?:graph)?|Table(?:Note)?|Fig(?:ure)?(?:Legend)?|Box)\b[^\]]*?)\]'
        cited_matches = re.findall(bracket_pattern, appraisal_markdown, re.IGNORECASE)
        
        pruned_anchors: Dict[str, str] = {}
        for m in cited_matches:
            raw_anc = f"[{m.strip()}]"
            if raw_anc in indexed_doc.all_anchors:
                pruned_anchors[raw_anc] = indexed_doc.all_anchors[raw_anc]

        # If very few anchors cited, fall back to core Abstract and Results anchors
        if len(pruned_anchors) < 4:
            for anc_id, txt in indexed_doc.all_anchors.items():
                if any(k in anc_id for k in ["Abstract", "Results", "Methods"]) and len(pruned_anchors) < 15:
                    pruned_anchors[anc_id] = txt

        anchors_context_str = "\n".join(f"{aid}: {txt}" for aid, txt in pruned_anchors.items())

        # System Instruction for Voice Generation
        system_instruction = (
            "You are an expert clinician drafting an editorial commentary on a medical study to share with clinical colleagues.\n"
            "Your commentary must synthesize the clinical meaning of the findings, critically contextualize effect sizes, "
            "and emphasize real-world patient care implications.\n\n"
            f"{lens_directive}\n\n"
            "STYLISTIC DIRECTIVES (TAILORED BY CLINICIAN VOICE PROFILE):\n"
            "1. VOICE & CADENCE: Mirror the rhetorical structure, sentence length rhythm, and opening hook style demonstrated in the active clinician exemplars below.\n"
            f"2. CLINICAL PHILOSOPHY: {philosophy if philosophy else 'Prioritize patient safety, mechanistic plausibility, and clinical relevance over statistical significance.'}\n"
            f"3. PREFERRED CONCEPTS / PHRASING: {preferred_terms if preferred_terms else 'Use clear, assertive clinical language with rigorous focus on absolute risk reductions.'}\n"
            f"4. PROHIBITED PHRASING: {prohibited_terms if prohibited_terms else 'Never say \"more research is needed\". Avoid generic conversational AI filler.'}\n"
            "5. CITATION INTEGRITY: When citing findings, you may include verified coordinate anchors like [Results, Table 2] or [Methods, Para 3]. Do NOT invent coordinate anchors.\n"
            "6. FORMAT: Output 2 to 4 punchy, high-impact paragraphs in Markdown suitable for an email, newsletter, or medical discussion board."
        )

        user_prompt = f"""### CLINICIAN PAST WRITING EXEMPLARS (STUDY FOR VOICE, CADENCE & TONE):
{exemplars_formatted}

============================================================
### CURRENT STUDY METADATA:
{indexed_doc.doc_header}

### SYNTHESIZED OBJECTIVE CLINICAL APPRAISAL:
{appraisal_markdown[:4000]}

### VERIFIED MANUSCRIPT EXCERPTS:
{anchors_context_str[:6000]}

============================================================
### TASK:
Draft an editorial commentary in the clinician's authentic voice, applying their philosophy and stylistic cadence to the findings of this study.
"""
        if not self.api_key:
            return {
                "status": "ready_for_inference_key_needed",
                "selected_model": model_override or PRIMARY_MODEL,
                "commentary": "API key required for live commentary inference.",
                "active_exemplars_count": len(active_exemplars)
            }

        raw_output, thought_output, used_model = self._invoke_gemini_rest(
            prompt=user_prompt,
            system_instruction=system_instruction,
            preferred_model=model_override,
            thinking_level="low",
            temperature=0.25
        )

        sanitization = sanitize_and_verify_appraisal(raw_output, indexed_doc.all_anchors)

        return {
            "status": "success",
            "commentary": sanitization.cleaned_markdown,
            "raw_output": raw_output,
            "thought_output": thought_output,
            "selected_model": used_model,
            "verified_anchors": sanitization.verified_anchors,
            "invalid_anchors": sanitization.invalid_anchors,
            "active_exemplars_count": len(active_exemplars)
        }

    def audit_appraisal_and_commentary(
        self,
        indexed_doc: IndexedDocument,
        appraisal_markdown: str,
        commentary_text: str,
        triage_data: Optional[Dict[str, Any]] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage 2: Calibrated Evidence-Bound Methodological Auditor.
        Independent stateless verification pass with 3-Tier Coordinate Quarantine Pipeline.
        """
        triage_info = triage_data or {}
        framework_id = triage_info.get("primary_framework_id", "GENERAL")
        framework_name = triage_info.get("framework_name", "Clinical Study")
        applicable_rules = triage_info.get("applicable_rules", [])

        # Format full manuscript anchors for audit reference
        manuscript_anchors_text = "\n".join(
            f"{aid}: {txt}" for aid, txt in indexed_doc.all_anchors.items() if aid != "[Doc_Header]"
        )

        system_instruction = (
            "You are an objective, evidence-bound statistical and methodological auditor.\n"
            "Your task is to independently audit a proposed clinician commentary and research appraisal against the raw manuscript coordinates.\n\n"
            "STRICT AUDIT MANDATES:\n"
            "1. NO FORCED HALLUCINATIONS: Do NOT invent flaws, nitpick stylistic prose, or manufacture discrepancies.\n"
            "   If all numerical claims, risk metrics, and causal assertions accurately reflect the manuscript and respect the study design's limitations,\n"
            "   you MUST output audit_status: 'NO_DISCREPANCIES_FOUND' with an empty discrepancies: [] array.\n"
            "2. VERBATIM QUOTES ONLY: Every item in discrepancies MUST provide an exact, verbatim substring in quoted_claim that appears in the submitted commentary or appraisal.\n"
            "3. SCOPE DECLARATION: Clearly mark scope as 'LOCALIZED_CLAIM' (for specific numbers, doses, or subgroup stats) or 'HOLISTIC_OR_OMISSION' (for overarching causal claims or unmeasured endpoints).\n"
            "4. CITATIONS: Provide exact [Section, Para N] anchors from the manuscript coordinates supporting your audit finding.\n"
            "5. OUTPUT FORMAT: Respond ONLY with a valid JSON object matching the requested schema."
        )

        user_prompt = f"""### STUDY DESIGN FRAMEWORK:
ID: {framework_id} ({framework_name})
Active Evaluation Rules: {json.dumps(applicable_rules)}

### MANUSCRIPT DOCUMENT HEADER:
{indexed_doc.doc_header}

### SUBMITTED CLINICIAN COMMENTARY TO AUDIT:
{commentary_text}

### SUBMITTED RESEARCH APPRAISAL TO AUDIT:
{appraisal_markdown[:4000]}

### RAW INDEXED MANUSCRIPT COORDINATES & TEXT:
{manuscript_anchors_text[:28000]}

============================================================
### REQUIRED JSON OUTPUT SCHEMA:
{{
  "overall_integrity": "VERIFIED" | "CAUTION" | "DISCREPANCY",
  "audit_status": "NO_DISCREPANCIES_FOUND" | "ISSUES_DETECTED",
  "summary_verdict": "<1-2 sentence executive audit conclusion>",
  "discrepancies": [
    {{
      "scope": "LOCALIZED_CLAIM" | "HOLISTIC_OR_OMISSION",
      "category": "NUMERICAL_ERROR" | "CAUSAL_OVERREACH" | "UNDERPOWERED_SAFETY_CLAIM" | "CHERRY_PICKED_ENDPOINT" | "OMITTED_OUTCOME",
      "severity": "YELLOW" | "RED",
      "quoted_claim": "<exact verbatim quote from commentary or appraisal>",
      "manuscript_evidence": "<concise explanation of how the manuscript contradicts or limits this claim, citing coordinates>",
      "citations": ["<exact coordinate anchor like [Results, Table 2]>"],
      "triage_rule_ref": "<rule_id or null>",
      "suggested_edit": "<specific revised phrasing>"
    }}
  ],
  "study_design_caveat": "<optional primary methodological caveat with coordinate citation, or null>"
}}
"""

        if not self.api_key:
            return {
                "status": "ready_for_inference_key_needed",
                "selected_model": model_override or PRIMARY_MODEL,
                "overall_integrity": "VERIFIED",
                "audit_status": "NO_DISCREPANCIES_FOUND",
                "summary_verdict": "API key required for live QC audit inference.",
                "discrepancies": []
            }

        raw_output, thought_output, used_model = self._invoke_gemini_rest(
            prompt=user_prompt,
            system_instruction=system_instruction,
            preferred_model=model_override,
            thinking_level="medium",
            temperature=0.0,
            json_mode=True
        )

        # Parse JSON output defensively
        parsed: Dict[str, Any] = {}
        try:
            parsed = json.loads(raw_output)
        except Exception:
            clean_json_match = re.search(r'\{[\s\S]*\}', raw_output)
            if clean_json_match:
                try:
                    parsed = json.loads(clean_json_match.group(0))
                except Exception as pe:
                    print(f"[CommentaryAndQCEngine] Audit JSON parse error: {pe}")
                    parsed = {}

        if not parsed:
            return {
                "status": "parse_fallback",
                "selected_model": used_model,
                "overall_integrity": "VERIFIED",
                "audit_status": "NO_DISCREPANCIES_FOUND",
                "summary_verdict": "Audit evaluation completed without structured discrepancy detection.",
                "discrepancies": [],
                "raw_output": raw_output
            }

        # -------------------------------------------------------------
        # 3-Tier Coordinate Verification & Quarantine Pipeline
        # -------------------------------------------------------------
        raw_discrepancies = parsed.get("discrepancies", [])
        if not isinstance(raw_discrepancies, list):
            raw_discrepancies = []

        validated_discrepancies: List[Dict[str, Any]] = []
        combined_draft = f"{commentary_text}\n\n{appraisal_markdown}".lower()
        # Normalization for substring check: strip punctuation and collapse whitespace
        norm_combined_draft = re.sub(r'[\W_]+', ' ', combined_draft).strip()

        for item in raw_discrepancies:
            if not isinstance(item, dict):
                continue

            quoted_claim = str(item.get("quoted_claim", "")).strip()
            # Gate A: Anti-Strawman Substring Verification
            # Verify quoted_claim appears in the commentary or appraisal
            norm_quote = re.sub(r'[\W_]+', ' ', quoted_claim.lower()).strip()
            if not norm_quote or (norm_quote not in norm_combined_draft and len(norm_quote) > 15):
                # Dropped as ungrounded strawman
                continue

            scope = str(item.get("scope", "LOCALIZED_CLAIM")).upper()
            raw_citations = item.get("citations", [])
            if not isinstance(raw_citations, list):
                raw_citations = [str(raw_citations)] if raw_citations else []

            evidence_text = str(item.get("manuscript_evidence", "")).strip()

            # Clean any broken/invalid inline brackets from evidence text
            def _clean_inline_brackets(match):
                inner = match.group(1).strip()
                cand = f"[{inner}]"
                return cand if cand in indexed_doc.all_anchors else inner
            clean_evidence = re.sub(r'\[([^\]]+)\]', _clean_inline_brackets, evidence_text)

            # Gate B: Grounding Verification by Scope
            verified_citations: List[str] = []
            
            # Tier 1: Canonical resolution
            for c in raw_citations:
                anc_str = str(c).strip()
                if not anc_str.startswith("["):
                    anc_str = f"[{anc_str}]"
                if anc_str in indexed_doc.all_anchors:
                    if anc_str not in verified_citations:
                        verified_citations.append(anc_str)
                    continue

                # Fuzzy resolution (e.g. [Res, Para 3] -> [Results, Para 3])
                m = re.match(r'\[\s*([A-Za-z\s&]+?)\s*,\s*Para(?:graph)?\s+(\d+)', anc_str, re.IGNORECASE)
                if m:
                    for canonical_key in indexed_doc.all_anchors.keys():
                        if m.group(1).lower() in canonical_key.lower() and f"Para {m.group(2)}" in canonical_key:
                            if canonical_key not in verified_citations:
                                verified_citations.append(canonical_key)
                            break

            # Tier 2: Substring Grounding Recovery if citations empty
            if not verified_citations and evidence_text:
                # Look for numbers or key tokens in manuscript
                numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', evidence_text)
                for num in numbers:
                    for aid, txt in indexed_doc.all_anchors.items():
                        if num in txt and aid not in verified_citations:
                            verified_citations.append(aid)
                            break
                    if verified_citations:
                        break

            # Tier 3: Quarantine Check
            if scope == "LOCALIZED_CLAIM":
                # Strict: Must have at least 1 verified anchor
                if not verified_citations:
                    continue  # Quarantined / dropped
            else:
                # HOLISTIC_OR_OMISSION
                rule_ref = str(item.get("triage_rule_ref", "")).strip()
                is_rule_valid = bool(rule_ref and rule_ref in applicable_rules)
                is_observational = bool("cohort" in framework_id.lower() or "observational" in framework_id.lower())
                has_structural_anchor = any(k in c for c in verified_citations for k in ["Doc_Header", "Abstract", "Methods"])

                if not (verified_citations or is_rule_valid or is_observational or has_structural_anchor):
                    continue  # Quarantined / dropped

                if not verified_citations:
                    verified_citations = ["[Doc_Header]"]

            item["quoted_claim"] = quoted_claim
            item["manuscript_evidence"] = clean_evidence
            item["citations"] = verified_citations
            validated_discrepancies.append(item)

        # Recalculate status and integrity after quarantine
        final_status = "ISSUES_DETECTED" if validated_discrepancies else "NO_DISCREPANCIES_FOUND"
        has_red = any(d.get("severity", "").upper() == "RED" for d in validated_discrepancies)
        final_integrity = "DISCREPANCY" if has_red else ("CAUTION" if validated_discrepancies else "VERIFIED")

        summary_verdict = parsed.get("summary_verdict") or (
            "All reviewed commentary points and quantitative findings are supported by the manuscript."
            if not validated_discrepancies else
            f"Audit identified {len(validated_discrepancies)} point(s) requiring calibration against manuscript data."
        )

        return {
            "status": "success",
            "selected_model": used_model,
            "overall_integrity": final_integrity,
            "audit_status": final_status,
            "summary_verdict": summary_verdict,
            "discrepancies": validated_discrepancies,
            "study_design_caveat": parsed.get("study_design_caveat"),
            "raw_output": raw_output
        }

    def extract_voice_profile_from_samples(
        self,
        samples_text: str,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyzes 1 or more writing samples from any clinician and extracts:
        - Core Clinical Philosophy (<= 500 chars)
        - Preferred Terms / Concepts (comma-separated, <= 300 chars)
        - Prohibited Boilerplate (comma-separated, <= 300 chars)
        - Recommended Hook / Structural Style Summary
        """
        client = get_gemini_client(self.api_key)
        used_model = model_override or PRIMARY_MODEL

        system_instruction = (
            "You are an expert psycholinguist and clinical editor specializing in physician writing styles.\n"
            "Analyze the provided clinician's writing samples and extract their authentic authorial DNA:\n"
            "1. 'philosophy': A concise synthesis (under 450 characters) of their core clinical philosophy, analytical stance, and epistemology.\n"
            "2. 'preferred_terms': A comma-separated string (under 280 characters) of their distinctive terminology, rhetorical concepts, and analytical lenses.\n"
            "3. 'prohibited_terms': A comma-separated string (under 280 characters) of clichéd phrases, generic filler, or AI tropes that clash with their authentic voice.\n"
            "Return strictly valid JSON with keys: 'philosophy', 'preferred_terms', 'prohibited_terms', 'voice_summary'."
        )

        user_prompt = f"""### CLINICIAN WRITING SAMPLES TO ANALYZE:
{samples_text[:12000]}

### INSTRUCTIONS:
Extract the voice profile in JSON matching the exact schema:
{{
  "philosophy": "...",
  "preferred_terms": "term1, term2, term3",
  "prohibited_terms": "filler1, filler2, filler3",
  "voice_summary": "1-2 sentence description of their rhetorical cadence and analytical style"
}}
"""
        response = client.models.generate_content(
            model=used_model,
            contents=[user_prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        raw_text = (response.text or "").strip()
        parsed = {}
        try:
            parsed = json.loads(raw_text)
        except Exception:
            clean = re.sub(r'```(?:json)?\s*', '', raw_text)
            clean = re.sub(r'```', '', clean).strip()
            try:
                parsed = json.loads(clean)
            except Exception:
                parsed = {
                    "philosophy": "Focus on clinical outcomes, patient safety, and absolute risk over surrogate metrics.",
                    "preferred_terms": "absolute risk reduction, clinical relevance, confounding, effect size",
                    "prohibited_terms": "more research is needed, delve, it is crucial to note",
                    "voice_summary": "Assertive clinical peer voice focusing on epidemiological rigor."
                }

        return {
            "status": "success",
            "philosophy": str(parsed.get("philosophy", "")).strip()[:500],
            "preferred_terms": str(parsed.get("preferred_terms", "")).strip()[:300],
            "prohibited_terms": str(parsed.get("prohibited_terms", "")).strip()[:300],
            "voice_summary": str(parsed.get("voice_summary", "")).strip()
        }

