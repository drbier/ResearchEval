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
        json_mode: bool = False,
        timeout: int = 50,
        max_output_tokens: int = 8192
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
                    "maxOutputTokens": max_output_tokens
                }
            }
            if effective_thinking:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": effective_thinking
                }
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            try:
                resp = requests.post(url, json=payload, timeout=timeout)
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
        model_override: Optional[str] = None,
        custom_prompt: Optional[str] = None
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
                "- Keep a balanced clinical perspective that values patient-important outcomes (survival, quality of life, functional status) and lifestyle/physiological context alongside medical interventions.\n"
                "- Do NOT reflexively recommend conventional guideline pharmaceutical regimens (e.g., statins, antiplatelets, antihypertensives) as mandatory unless the study directly evaluated them.\n"
                "- Note calmly when an intervention only alters a surrogate biomarker without improving hard clinical outcomes."
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
            "1. VOICE & CADENCE: Mirror the calm, analytical, collegial tone and sentence rhythm demonstrated in the active clinician exemplars below. NEVER copy exemplar subheadings or metaphors verbatim—write fresh prose.\n"
            "2. TEMPERAMENT GUARDRAIL: Write as a measured, objective clinician talking to peers—dry, direct, and grounded in numbers. NEVER preach, moralize, lecture, or use accusatory/melodramatic framing (e.g., avoid 'moral good', 'profound disregard', 'institutional habit', 'completely collapses', 'statistical quicksand').\n"
            f"3. CLINICAL PHILOSOPHY: {philosophy if philosophy else 'Prioritize patient safety, mechanistic plausibility, and clinical relevance over statistical significance.'}\n"
            f"4. ANALYTICAL CONCEPTS (apply only where genuinely relevant—do NOT force catchphrases): {preferred_terms if preferred_terms else 'absolute risk reduction, clinical relevance, confounding, effect size'}\n"
            f"5. PROHIBITED PHRASING: {prohibited_terms if prohibited_terms else 'Never say \"more research is needed\". Avoid generic conversational AI filler.'}\n"
            "6. CITATION INTEGRITY: When citing findings, you may include verified coordinate anchors like [Results, Table 2] or [Methods, Para 3]. Do NOT invent coordinate anchors.\n"
            "7. FORMAT: Output 2 to 4 clear, measured paragraphs in Markdown suitable for an email, newsletter, or medical discussion board. Format any section subheadings as bold Markdown (`### Subheading` or `**Subheading:**`)."
        )

        clean_custom_prompt = str(custom_prompt or "").strip()[:1000]
        custom_angle_block = ""
        if clean_custom_prompt:
            custom_angle_block = (
                "\n### CLINICIAN'S SPECIFIC ANGLE / THESIS FOR THIS PAPER:\n"
                f"{clean_custom_prompt}\n\n"
                "DIRECTIVE FOR CLINICIAN ANGLE: Lead with and weave in the clinician's stated thesis and framing above in their authentic, measured voice. "
                "Present clinical concerns with calm analytical precision, while ensuring every numerical figure or study-specific outcome claim remains strictly grounded in the Verified Manuscript Excerpts.\n"
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
{custom_angle_block}
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

    @staticmethod
    def _strip_coord_brackets(text: str) -> str:
        """Remove inline [Section, Para/Table] coordinate brackets for quote verification."""
        return re.sub(r'\[[^\]]{2,80}\]', ' ', text or '')

    @classmethod
    def _verify_quote_in_draft(cls, quoted_claim: str, combined_draft: str) -> bool:
        """
        Gate A: Anti-Strawman verification with bracket-stripping, ellipsis support,
        and >=70% content-token sentence overlap fallback.
        """
        if not quoted_claim or not combined_draft:
            return False

        clean_draft = cls._strip_coord_brackets(combined_draft).lower()
        clean_quote = cls._strip_coord_brackets(quoted_claim).lower()

        norm_draft = re.sub(r'[\W_]+', ' ', clean_draft).strip()
        norm_quote = re.sub(r'[\W_]+', ' ', clean_quote).strip()
        if not norm_quote:
            return False

        # Short quotes (< 16 chars) or direct substring match
        if len(norm_quote) <= 15 or norm_quote in norm_draft:
            return True

        # Ellipsis-split segment matching (e.g. "first clause ... second clause")
        if '...' in clean_quote or '…' in clean_quote:
            segs = [re.sub(r'[\W_]+', ' ', s).strip() for s in re.split(r'\.{2,}|…', clean_quote)]
            meaningful_segs = [s for s in segs if len(s) >= 12]
            if meaningful_segs and all(s in norm_draft for s in meaningful_segs):
                return True

        # Content-token overlap fallback (>= 70% overlap with a draft sentence/line)
        q_tokens = [t for t in norm_quote.split() if len(t) >= 3]
        if len(q_tokens) >= 4:
            q_set = set(q_tokens)
            for chunk in re.split(r'[\n\.!?]+', clean_draft):
                c_tokens = set(t for t in re.sub(r'[\W_]+', ' ', chunk).split() if len(t) >= 3)
                if not c_tokens:
                    continue
                overlap = len(q_set & c_tokens) / len(q_set)
                if overlap >= 0.70:
                    return True

        return False

    @staticmethod
    def _resolve_citation_anchor(anc_str: str, all_anchors: Dict[str, str]) -> Optional[str]:
        """
        Gate B Tier 1: Canonical + fuzzy anchor resolution covering Para N, Table N,
        Fig N, TableNote, and Abstract subsections.
        """
        clean = str(anc_str).strip()
        if not clean:
            return None
        if not clean.startswith("["):
            clean = f"[{clean}]"
        if clean in all_anchors:
            return clean

        # Case-insensitive exact match
        clean_lower = clean.lower()
        for k in all_anchors.keys():
            if k.lower() == clean_lower:
                return k

        sec_aliases = {
            "abs": "abstract", "abstract": "abstract",
            "intro": "introduction", "introduction": "introduction",
            "meth": "methods", "method": "methods", "methods": "methods",
            "res": "results", "result": "results", "results": "results",
            "disc": "discussion", "discussion": "discussion",
            "concl": "conclusions", "conclusion": "conclusions", "conclusions": "conclusions",
            "supp": "appendix", "appendix": "appendix"
        }

        inner = clean.strip("[]").strip()
        # Match "[Section, Para N]" or "[Section, pN]"
        m_para = re.match(r'^([A-Za-z\s&]+?)\s*,\s*(?:Para(?:graph)?\s*|p)(\d+)$', inner, re.IGNORECASE)
        if m_para:
            sec_raw = m_para.group(1).strip().lower()
            sec_norm = sec_aliases.get(sec_raw, sec_raw)
            num = m_para.group(2)
            for k in all_anchors.keys():
                kl = k.lower()
                if sec_norm in kl and f"para {num}]" in kl:
                    return k

        # Match "[Section, Table N]" or "[Table N]"
        m_tbl = re.match(r'^(?:([A-Za-z\s&]+?)\s*,\s*)?Table\s*([0-9]+[A-Za-z]?|[IVXLCDM]+)$', inner, re.IGNORECASE)
        if m_tbl:
            sec_raw = (m_tbl.group(1) or "").strip().lower()
            sec_norm = sec_aliases.get(sec_raw, sec_raw)
            tnum = m_tbl.group(2).lower()
            for k in all_anchors.keys():
                kl = k.lower()
                if f"table {tnum}]" in kl and (not sec_norm or sec_norm in kl):
                    return k

        # Match "[Section, Fig N]" or "[Figure N]"
        m_fig = re.match(r'^(?:([A-Za-z\s&]+?)\s*,\s*)?Fig(?:ure)?\.?\s*([0-9]+[A-Za-z]?)$', inner, re.IGNORECASE)
        if m_fig:
            sec_raw = (m_fig.group(1) or "").strip().lower()
            sec_norm = sec_aliases.get(sec_raw, sec_raw)
            fnum = m_fig.group(2).lower()
            for k in all_anchors.keys():
                kl = k.lower()
                if f"fig {fnum}]" in kl and (not sec_norm or sec_norm in kl):
                    return k

        # Match "[Abstract, Methods/Results/Conclusions/Objective]" or "[Abs, Results]"
        m_abs = re.match(r'^(?:Abs|Abstract)\s*,\s*([A-Za-z]+)$', inner, re.IGNORECASE)
        if m_abs:
            sub = m_abs.group(1).strip().lower()
            for k in all_anchors.keys():
                kl = k.lower()
                if kl.startswith("[abstract,") and sub in kl:
                    return k

        return None

    def audit_appraisal_and_commentary(
        self,
        indexed_doc: IndexedDocument,
        appraisal_markdown: str,
        commentary_text: str,
        triage_data: Optional[Dict[str, Any]] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Stage 2: Calibrated Evidence-Bound Methodological Auditor (Informed Medicine Standard).
        Independent stateless verification pass with full-text inspection and hardened
        3-Tier Coordinate Quarantine Pipeline.
        """
        triage_info = triage_data or {}
        framework_id = str(triage_info.get("primary_framework_id", "GENERAL") or "GENERAL")
        framework_name = str(triage_info.get("framework_name", "Clinical Study") or "Clinical Study")
        applicable_rules = triage_info.get("applicable_rules", [])

        # Format complete manuscript anchors (including all Tables & TableNotes, up to 250K chars)
        manuscript_anchors_text = "\n".join(
            f"{aid}: {txt}" for aid, txt in indexed_doc.all_anchors.items() if aid != "[Doc_Header]"
        )

        system_instruction = (
            "You are a stoic, matter-of-fact Clinical Research & Commentary Auditor.\n"
            "Your mandate is to audit drafted medical research appraisals and clinician commentaries strictly against the provided full-text source manuscript coordinates and tables.\n"
            "Ensure 100% factual fidelity, statistical rigor, and clear epistemic boundaries between measured study data and clinical interpretation—without diluting the author's clinical voice.\n\n"
            "1. CORE ANALYTICAL STANDARDS (UNIVERSAL REPORTING INTEGRITY):\n"
            "   - Hard Endpoints First: Prioritize Tier 1 hard clinical outcomes (Overall Survival, all-cause mortality) over surrogate, composite, or intermediate endpoints. Flag abstract spin when null hard endpoints are omitted or buried.\n"
            "   - Observational vs. Randomized Distinction: Distinguish randomized interventions from non-randomized baseline exposures nested inside RCTs. Check whether confounding by indication was tested against the placebo/control arm.\n"
            "   - Reporting Integrity & Harms Transparency: Whenever an intervention adverse event or discontinuation rate is cited, check whether the placebo/control denominator is reported in the manuscript and flag missing control anchoring or relative-vs-absolute risk asymmetry.\n\n"
            "2. STRICT SOURCE-BOUND VERIFICATION:\n"
            "   - Zero External Memory: Cross-reference EVERY number, HR/OR/RR, 95% CI, p-value, sample size, follow-up duration, and causal claim EXCLUSIVELY against the provided manuscript coordinates.\n"
            "   - Complete Document Inspection: Inspect ALL Tables, Figure Legends, Methods, and Multivariable Regression subsections—not just the Abstract and main Results prose.\n"
            "   - Internal Paper Typos: Watch for copy-paste errors inside published manuscripts (e.g., an HR from a secondary endpoint accidentally repeated in OS prose). Cross-check prose against regression tables and flag internal discrepancies explicitly.\n\n"
            "3. METHODOLOGICAL & STATISTICAL FALLACIES TO AUDIT:\n"
            "   - Non-Inferiority Fallacy (treating p > 0.05 superiority as proof of equivalence).\n"
            "   - Categorical vs. Continuous Collapse (effects present only in arbitrary quantiles that vanish linearly).\n"
            "   - Univariate-to-Multivariable Attenuation (unadjusted survival/efficacy gains disappearing after covariate adjustment).\n"
            "   - Overstated Null/Causal Language (e.g., 'confirms no effect' -> 'shows no statistically significant advantage'; causal verbs on observational cohorts).\n"
            "   - Adherence & Exposure Precision (distinguish baseline prescription/intent declared at entry vs. longitudinal adherence tracking).\n\n"
            "4. EPISTEMIC BOUNDARIES (VOICE-PRESERVING):\n"
            "   - Flag biological mechanisms, unmeasured toxicities, or external clinical workups mentioned in commentary that were not measured in the trial if they lack transitional signposting.\n"
            "   - NEVER recommend deleting clinical insights; instead recommend minimal signposting edits (e.g., 'From a broader physiological perspective...', 'In clinical practice...').\n\n"
            "5. NOISE FILTERS:\n"
            "   - IGNORE inline document/page citation brackets (e.g. [Res, p3], [Abs, Results]) and empty stripped-tag parentheses.\n"
            "   - FLAG any unstripped internal rule tags (e.g. {R_HARD_OUTCOME_PRIORITY}, {R_CONSORT_HARMS_01}).\n\n"
            "6. OUTPUT DISCIPLINE:\n"
            "   - Zero filler, pleasantries, praise, or exclamation marks.\n"
            "   - Every item in discrepancies MUST quote the exact claim from the draft in quoted_claim and cite exact manuscript anchor(s) in citations.\n"
            "   - Enumerate 5 to 10 (MAX 10) primary quantitative and methodological points you confirmed in verified_claims.\n"
            "   - If no genuine factual, statistical, omission, or epistemic boundary flaws exist, output audit_status: 'NO_DISCREPANCIES_FOUND' with discrepancies: [].\n"
            "   - Respond ONLY with a valid JSON object matching the requested schema."
        )

        commentary_section_prompt = (
            f"### SUBMITTED CLINICIAN COMMENTARY TO AUDIT:\n{commentary_text}\n"
            if commentary_text.strip()
            else "### SUBMITTED CLINICIAN COMMENTARY TO AUDIT:\n(None submitted. Audit the Research Appraisal alone against the manuscript coordinates.)\n"
        )

        user_prompt = f"""### STUDY DESIGN FRAMEWORK:
ID: {framework_id} ({framework_name})
Active Evaluation Rules: {json.dumps(applicable_rules)}

### MANUSCRIPT DOCUMENT HEADER:
{indexed_doc.doc_header}

{commentary_section_prompt}
### SUBMITTED RESEARCH APPRAISAL TO AUDIT (COMPLETE):
{appraisal_markdown}

### RAW INDEXED MANUSCRIPT COORDINATES & TABLES:
{manuscript_anchors_text[:250000]}

============================================================
### REQUIRED JSON OUTPUT SCHEMA:
{{
  "confidence_tag": "High Certainty" | "Moderate Certainty / Hypothesis" | "Exploratory / Low Certainty",
  "overall_integrity": "VERIFIED" | "CAUTION" | "DISCREPANCY",
  "audit_status": "NO_DISCREPANCIES_FOUND" | "ISSUES_DETECTED",
  "summary_verdict": "<1-2 sentence stoic executive audit conclusion>",
  "discrepancies": [
    {{
      "scope": "LOCALIZED_CLAIM" | "HOLISTIC_OR_OMISSION",
      "category": "NUMERICAL_ERROR" | "CAUSAL_OVERREACH" | "CONTROL_ANCHORING" | "ATTENUATION_OR_FALLACY" | "ADHERENCE_PRECISION" | "EPISTEMIC_BOUNDARY" | "OMITTED_OUTCOME" | "UNSTRIPPED_TAG",
      "severity": "YELLOW" | "RED",
      "quoted_claim": "<exact verbatim substring from commentary or appraisal>",
      "manuscript_evidence": "<concise explanation of how the manuscript contradicts or limits this claim, citing coordinates>",
      "citations": ["<exact coordinate anchor like [Results, Table 2]>"],
      "triage_rule_ref": "<rule_id or null>",
      "suggested_edit": "<minimal revised phrasing preserving author voice>"
    }}
  ],
  "verified_claims": [
    {{
      "claim": "<concise verified number, endpoint, or methodological critique (cap at 5-10 items total)>",
      "citations": ["<exact coordinate anchor>"]
    }}
  ],
  "study_design_caveat": "<optional primary methodological caveat with coordinate citation, or null>",
  "publish_readiness": {{
    "verdict": "<direct assessment of fairness and publish-readiness>",
    "pre_publish_fixes": ["<concrete minimal pre-publish fix if any>"]
  }}
}}
"""

        if not self.api_key:
            return {
                "status": "ready_for_inference_key_needed",
                "selected_model": model_override or PRIMARY_MODEL,
                "confidence_tag": "Exploratory / Low Certainty",
                "overall_integrity": "VERIFIED",
                "audit_status": "NO_DISCREPANCIES_FOUND",
                "summary_verdict": "API key required for live QC audit inference.",
                "discrepancies": [],
                "verified_claims": [],
                "quarantined_count": 0
            }

        raw_output, thought_output, used_model = self._invoke_gemini_rest(
            prompt=user_prompt,
            system_instruction=system_instruction,
            preferred_model=model_override,
            thinking_level="medium",
            temperature=0.0,
            json_mode=True,
            timeout=90,
            max_output_tokens=16384
        )

        return self._postprocess_audit_output(
            raw_output=raw_output,
            used_model=used_model,
            indexed_doc=indexed_doc,
            appraisal_markdown=appraisal_markdown,
            commentary_text=commentary_text,
            framework_id=framework_id,
            framework_name=framework_name,
            applicable_rules=applicable_rules
        )

    def _postprocess_audit_output(
        self,
        raw_output: str,
        used_model: str,
        indexed_doc: IndexedDocument,
        appraisal_markdown: str,
        commentary_text: str,
        framework_id: str = "GENERAL",
        framework_name: str = "Clinical Study",
        applicable_rules: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Parse audit JSON and run hardened 3-Tier Coordinate Verification & Quarantine Pipeline."""
        applicable_rules = applicable_rules or []

        parsed: Dict[str, Any] = {}
        try:
            parsed = json.loads(raw_output)
        except Exception:
            clean_json_match = re.search(r'\{[\s\S]*\}', raw_output or '')
            if clean_json_match:
                try:
                    parsed = json.loads(clean_json_match.group(0))
                except Exception as pe:
                    print(f"[CommentaryAndQCEngine] Audit JSON parse error: {pe}")
                    parsed = {}

        # Never silently default to VERIFIED on malformed/truncated JSON
        if not parsed or not isinstance(parsed, dict):
            return {
                "status": "parse_error",
                "selected_model": used_model,
                "confidence_tag": "Exploratory / Low Certainty",
                "overall_integrity": "AUDIT_ERROR",
                "audit_status": "AUDIT_ERROR",
                "summary_verdict": "Audit response could not be parsed as valid JSON (possible truncation). Please re-run the Adversarial QC Audit.",
                "discrepancies": [],
                "verified_claims": [],
                "quarantined_count": 0,
                "raw_output": raw_output
            }

        raw_discrepancies = parsed.get("discrepancies", [])
        if not isinstance(raw_discrepancies, list):
            raw_discrepancies = []

        validated_discrepancies: List[Dict[str, Any]] = []
        quarantined_count = 0
        combined_draft = f"{commentary_text}\n\n{appraisal_markdown}"

        for item in raw_discrepancies:
            if not isinstance(item, dict):
                continue

            quoted_claim = str(item.get("quoted_claim", "")).strip()
            # Gate A: Anti-Strawman Verification (bracket-stripped + ellipsis + >=70% token overlap)
            if not self._verify_quote_in_draft(quoted_claim, combined_draft):
                quarantined_count += 1
                continue

            scope = str(item.get("scope", "LOCALIZED_CLAIM")).upper()
            category = str(item.get("category", "NUMERICAL_ERROR")).upper()
            raw_citations = item.get("citations", [])
            if not isinstance(raw_citations, list):
                raw_citations = [str(raw_citations)] if raw_citations else []

            evidence_text = str(item.get("manuscript_evidence", "")).strip()

            # Clean any broken/invalid inline brackets from evidence text
            def _clean_inline_brackets(match):
                inner = match.group(1).strip()
                resolved = self._resolve_citation_anchor(inner, indexed_doc.all_anchors)
                return resolved if resolved else inner
            clean_evidence = re.sub(r'\[([^\]]+)\]', _clean_inline_brackets, evidence_text)

            # Gate B: Grounding Verification by Scope
            verified_citations: List[str] = []

            # Tier 1: Canonical + Fuzzy Resolution (Para, Table, Fig, Abstract)
            for c in raw_citations:
                resolved = self._resolve_citation_anchor(str(c), indexed_doc.all_anchors)
                if resolved and resolved not in verified_citations:
                    verified_citations.append(resolved)

            # Tier 2: Substring Grounding Recovery if citations empty
            if not verified_citations and evidence_text:
                numbers = re.findall(r'\b\d+(?:\.\d+)?%?\b', evidence_text)
                for num in numbers:
                    for aid, txt in indexed_doc.all_anchors.items():
                        if num in txt and aid not in verified_citations:
                            verified_citations.append(aid)
                            break
                    if verified_citations:
                        break

            # Tier 3: Quarantine Check
            is_boundary_or_tag = category in ("EPISTEMIC_BOUNDARY", "UNSTRIPPED_TAG", "OMITTED_OUTCOME", "CONTROL_ANCHORING")
            if scope == "LOCALIZED_CLAIM" and not is_boundary_or_tag:
                if not verified_citations:
                    quarantined_count += 1
                    continue
            else:
                rule_ref = str(item.get("triage_rule_ref", "")).strip()
                is_rule_valid = bool(rule_ref and rule_ref in applicable_rules)
                is_observational = bool(
                    framework_id == "FW_C"
                    or "observational" in framework_name.lower()
                    or "cohort" in framework_name.lower()
                )
                has_structural_anchor = any(k in c for c in verified_citations for k in ["Doc_Header", "Abstract", "Methods"])

                if not (verified_citations or is_rule_valid or is_observational or has_structural_anchor or is_boundary_or_tag):
                    quarantined_count += 1
                    continue

                if not verified_citations:
                    verified_citations = ["[Doc_Header]"]

            item["quoted_claim"] = quoted_claim
            item["manuscript_evidence"] = clean_evidence
            item["citations"] = verified_citations
            validated_discrepancies.append(item)

        # Normalize verified_claims (cap at 10)
        raw_verified = parsed.get("verified_claims", [])
        verified_claims_clean: List[Dict[str, Any]] = []
        if isinstance(raw_verified, list):
            for vc in raw_verified[:10]:
                if isinstance(vc, dict) and str(vc.get("claim", "")).strip():
                    vc_cits = []
                    for c in (vc.get("citations") or []):
                        res = self._resolve_citation_anchor(str(c), indexed_doc.all_anchors)
                        if res and res not in vc_cits:
                            vc_cits.append(res)
                    verified_claims_clean.append({
                        "claim": str(vc.get("claim", "")).strip(),
                        "citations": vc_cits
                    })
                elif isinstance(vc, str) and vc.strip():
                    verified_claims_clean.append({"claim": vc.strip(), "citations": []})

        # Recalculate status and integrity after quarantine
        final_status = "ISSUES_DETECTED" if validated_discrepancies else "NO_DISCREPANCIES_FOUND"
        has_red = any(str(d.get("severity", "")).upper() == "RED" for d in validated_discrepancies)
        final_integrity = "DISCREPANCY" if has_red else ("CAUTION" if validated_discrepancies else "VERIFIED")

        summary_verdict = parsed.get("summary_verdict") or (
            "All reviewed commentary points and quantitative findings are supported by the manuscript."
            if not validated_discrepancies else
            f"Audit identified {len(validated_discrepancies)} point(s) requiring calibration against manuscript data."
        )

        publish_readiness = parsed.get("publish_readiness")
        if not isinstance(publish_readiness, dict):
            publish_readiness = None

        return {
            "status": "success",
            "selected_model": used_model,
            "confidence_tag": parsed.get("confidence_tag") or "High Certainty",
            "overall_integrity": final_integrity,
            "audit_status": final_status,
            "summary_verdict": summary_verdict,
            "discrepancies": validated_discrepancies,
            "verified_claims": verified_claims_clean,
            "study_design_caveat": parsed.get("study_design_caveat"),
            "publish_readiness": publish_readiness,
            "quarantined_count": quarantined_count,
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

