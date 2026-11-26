"""
src/appraisal/qa.py - Interactive Conversational Interrogation Engine ('Ask')

Provides accurate, coordinate-grounded clinical QA for any loaded manuscript.
Uses large-context Gemini models with zero vector DB chunking, strict anchor grounding,
normalized query caching, and rolling conversation history token management.
"""

import os
import re
import json
import hashlib
import requests
from typing import Dict, Any, List, Optional, Tuple
from dotenv import load_dotenv

from src.ingestion.indexer import IndexedDocument
from src.appraisal.sanitizer import sanitize_and_verify_appraisal, SanitizationResult

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Model Hierarchy (Verified active models in order of preference)
# Primary: gemini-3.8-flash (Active Preview, Google's premier flash model for autonomous reasoning)
# Fallback: gemini-3.5-flash-lite (Active GA, ultra-fast low-latency high-throughput model)
MODEL_HIERARCHY = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite"
]
PRIMARY_MODEL = MODEL_HIERARCHY[0]
FALLBACK_MODEL = MODEL_HIERARCHY[1]

class PaperQAEngine:
    """Interrogates a loaded manuscript with exact anchor coordinate grounding."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._query_cache: Dict[str, Dict[str, Any]] = {}

    def normalize_query(self, question: str) -> str:
        """Normalize query text for deterministic hashing: lowercase, strip punctuation, collapsed spaces."""
        q = question.lower().strip()
        q = re.sub(r'[^\w\s]', '', q)
        return re.sub(r'\s+', ' ', q).strip()

    def _get_cache_key(self, filename: str, question: str) -> str:
        """Generate SHA-256 cache key for filename + normalized question."""
        norm_q = self.normalize_query(question)
        composite = f"{filename.strip()}::{norm_q}"
        return hashlib.sha256(composite.encode("utf-8")).hexdigest()

    def assemble_manuscript_context(self, indexed_doc: IndexedDocument) -> Tuple[str, Dict[str, str]]:
        """
        Assemble complete clinical manuscript context while strictly filtering out '[..., Meta ...]' anchors.
        All clinical sections (Abstract, Introduction, Methods, Results, Discussion, Tables, Figures, etc.)
        are included in their entirety with coordinate anchor tags.
        """
        context_parts = []
        valid_anchor_dict = {}

        # 1. Document Header
        header_text = str(indexed_doc.doc_header or "").strip()
        if header_text:
            # Avoid duplicate [Doc_Header] prefix if already present
            if not header_text.startswith("[Doc_Header]"):
                context_parts.append(f"[Doc_Header]\n{header_text}\n")
            else:
                context_parts.append(f"{header_text}\n")
            valid_anchor_dict["[Doc_Header]"] = header_text

        # 2. Iterate through all indexed anchors, filtering out Meta blocks
        for aid, meta in indexed_doc.anchor_metadata.items():
            # Check section name and anchor tag for 'Meta'
            sec_name = (meta.section or "").strip()
            if sec_name.lower() == "meta" or re.search(r'\[.*,\s*Meta\b', aid, re.IGNORECASE):
                continue
            
            # Format clean anchor block
            raw_text = meta.text.strip()
            if raw_text:
                context_parts.append(f"{aid}\n{raw_text}\n")
                valid_anchor_dict[aid] = raw_text

        full_context = "\n".join(context_parts)
        return full_context, valid_anchor_dict

    def _invoke_gemini_rest(
        self,
        prompt: str,
        system_instruction: str,
        preferred_model: Optional[str] = None,
        thinking_level: str = "low",
        json_mode: bool = False,
        temperature: float = 0.15,
        max_output_tokens: int = 4096
    ) -> Tuple[str, str, str]:
        """Call Gemini REST endpoint with verified model fallback hierarchy."""
        models = [preferred_model] if preferred_model and preferred_model in MODEL_HIERARCHY else list(MODEL_HIERARCHY)
        if preferred_model and preferred_model not in models:
            models.insert(0, preferred_model)

        last_error = "Unknown error"
        effective_thinking = thinking_level if thinking_level in ("low", "medium", "high") else "low"

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_output_tokens
                }
            }
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"
            if effective_thinking:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": effective_thinking
                }
            try:
                resp = requests.post(url, json=payload, timeout=60)
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
                    print(f"[PaperQAEngine] Warning: {last_error}. Trying next model...")
            except Exception as e:
                last_error = f"Model {model} failed: {str(e)}"
                print(f"[PaperQAEngine] Warning: {last_error}. Trying next model...")

        raise RuntimeError(f"All Gemini models in hierarchy failed. Last error: {last_error}")

    def ask(
        self,
        indexed_doc: IndexedDocument,
        question: str,
        filename: str = "document.pdf",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        model_override: Optional[str] = None,
        thinking_level: str = "low"
    ) -> Dict[str, Any]:
        """
        Execute an interrogated clinical query on the manuscript.
        Utilizes normalized query caching and capped 4-turn conversational history.
        """
        clean_q = question.strip()
        if not clean_q:
            return {"status": "error", "message": "Question cannot be empty."}

        # Check Normalized Query Cache ($0.00 Cost on Repeat / Quick-Chip Queries)
        cache_key = self._get_cache_key(filename, clean_q)
        if cache_key in self._query_cache:
            cached_res = dict(self._query_cache[cache_key])
            cached_res["cached"] = True
            return cached_res

        # 1. Assemble Full Context (filtering out Meta blocks)
        manuscript_text, valid_anchor_dict = self.assemble_manuscript_context(indexed_doc)

        # 2. Manage Conversation History (Capped at last 4 turns to prevent latency/token inflation)
        capped_history = conversation_history[-4:] if conversation_history else []
        history_prompt = ""
        if capped_history:
            history_lines = ["\n### PREVIOUS CONVERSATION HISTORY (Last turns):"]
            for turn in capped_history:
                role = "User" if turn.get("role") in ("user", "human") else "Assistant"
                history_lines.append(f"{role}: {turn.get('content', '').strip()}")
            history_prompt = "\n".join(history_lines) + "\n"

        # 3. System Instruction
        system_instruction = (
            "You are an Expert Evidence-Based Medicine Analyst interrogating a specific medical study for a clinician.\n"
            "Your objective is to answer the clinician's question accurately, concisely, and with strict factual grounding.\n\n"
            "MANDATORY EXECUTION DIRECTIVES:\n"
            "1. Base your answer EXCLUSIVELY on the provided manuscript text. Never extrapolate, speculate, or introduce external data.\n"
            "2. EXACT ANCHOR CITATIONS: Every factual assertion, quantitative statistic, endpoint finding, or study detail MUST be immediately followed by its exact coordinate anchor in square brackets (e.g., [Abstract, Para 2], [Methods, Para 4], [Results, Table 1], [Results, TableNote p1_504], [Discussion, Para 8]).\n"
            "   - Single anchors only: Write '[Methods, Para 2] [Methods, Para 4]', never combine into '[Methods, Para 2, 4]'.\n"
            "   - Never invent or fabricate anchors.\n"
            "3. NEGATIVE OBSERVATIONS: If the paper does NOT report, evaluate, or mention the queried outcome (e.g. Overall Survival was not tracked, or subgroup analysis was omitted), state this directly and clearly:\n"
            "   'The study does not report or evaluate [requested item] [cite relevant Methods/Results section if applicable].'\n"
            "4. STYLE & CONCISENESS: Deliver direct, clear clinical answers (2 to 4 sentences or a crisp bulleted list). Avoid conversational filler ('Certainly!', 'Here is the analysis', 'I hope this helps!').\n"
            "5. NO LATEX: Do not use LaTeX math formatting or dollar signs ($...$ or $$...$$). Use standard Unicode characters (e.g., n = 31 268, p < 0.05, 95% CI, HR = 0.94, ±, ≥, ≤).\n"
        )

        # 4. User Prompt
        user_prompt = (
            f"### MANUSCRIPT CLINICAL CONTENT:\n"
            f"{manuscript_text}\n"
            f"{history_prompt}\n"
            f"### CLINICIAN QUESTION:\n"
            f"{clean_q}\n\n"
            f"Provide a direct, concisely grounded answer citing exact inline anchor coordinates."
        )

        if not self.api_key:
            return {
                "status": "ready_for_inference_key_needed",
                "question": clean_q,
                "cached": False,
                "context_length_chars": len(manuscript_text),
                "anchors_available_count": len(valid_anchor_dict),
                "selected_model": model_override or PRIMARY_MODEL
            }

        # 5. Call Gemini
        raw_output, thought_output, used_model = self._invoke_gemini_rest(
            prompt=user_prompt,
            system_instruction=system_instruction,
            preferred_model=model_override,
            thinking_level=thinking_level
        )

        # 6. Sanitize and Verify Anchors via existing sanitizer
        sanitization: SanitizationResult = sanitize_and_verify_appraisal(raw_output, valid_anchor_dict)

        result = {
            "status": "success",
            "question": clean_q,
            "answer": sanitization.cleaned_markdown,
            "verified_anchors": sanitization.verified_anchors,
            "invalid_anchors": sanitization.invalid_anchors,
            "selected_model": used_model,
            "thinking_level": thinking_level,
            "cached": False,
            "raw_output": raw_output
        }

        # Save to Normalized Query Cache
        self._query_cache[cache_key] = result
        return result

    def discuss_and_verify_appraisal(
        self,
        indexed_doc: IndexedDocument,
        current_markdown: str,
        critique: str,
        target: str = "analysis",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        model_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Deterministic (temp=0.0) adjudication pass for Analyze (Clinical Analysis or Commentary).
        Verifies each claim in the user's feedback or external audit directly against the full
        indexed manuscript coordinates, refuting unsupported critiques or proposing a coordinate-grounded
        updated draft for user review before applying.
        """
        clean_critique = (critique or "").strip()
        if not clean_critique:
            return {"status": "error", "message": "Feedback or audit critique cannot be empty."}
        if not self.api_key:
            return {"status": "error", "message": "Gemini API key is not configured."}

        manuscript_text, valid_anchor_dict = self.assemble_manuscript_context(indexed_doc)
        # Also include TableNote anchors if present in all_anchors
        for aid, txt in indexed_doc.all_anchors.items():
            if aid not in valid_anchor_dict and "Meta" not in aid and txt.strip():
                valid_anchor_dict[aid] = txt.strip()
                manuscript_text += f"\n{aid}\n{txt.strip()}\n"

        history_blob = ""
        if conversation_history:
            turns = []
            for h in conversation_history[-4:]:
                role = "Clinician" if h.get("role") in ("user", "human") else "Adjudicator"
                turns.append(f"{role}: {str(h.get('content', '')).strip()}")
            if turns:
                history_blob = "\n\n### PRIOR DISCUSSION:\n" + "\n".join(turns)

        target_label = "Clinician Editorial Commentary" if target == "commentary" else "Clinical Analysis Appraisal"

        system_instruction = (
            f"You are a deterministic, evidence-bound clinical methodologist adjudicating feedback or an external audit on a {target_label}.\n"
            "STRICT RULES:\n"
            "1. Verify EVERY point in the feedback/audit directly against the provided MANUSCRIPT CLINICAL CONTENT & TABLES.\n"
            "2. Do NOT blindly agree with the user or external audit! If the current text is accurate and the critique is mistaken or unsupported by the manuscript, mark that point 'REFUTED' and cite the exact coordinate anchor(s) proving it.\n"
            "3. If a critique identifies a real factual error, missing statistic, univariate-vs-multivariable discrepancy, or overstatement confirmed by the manuscript, mark it 'CONFIRMED' or 'PARTIAL', cite the exact coordinate anchor(s), and fix it in 'updated_markdown'.\n"
            "4. EXACT ANCHOR CITATIONS: Every factual claim or correction in 'evidence' and 'updated_markdown' MUST use exact individual coordinate anchors from the manuscript (e.g., [Results, Table 2] [Results, Para 6]). Never invent anchors and never combine multiple numbers into one bracket.\n"
            "5. PRESERVE STRUCTURE: If 'has_updates' is true, output the COMPLETE revised markdown in 'updated_markdown' preserving all existing section headings (# Title, ## Clinical Bottom Line, ## Results in Context, etc.), formatting, and verified coordinate anchors. Do NOT use LaTeX $...$ math. If all points are REFUTED or UNVERIFIABLE, set 'has_updates': false and 'updated_markdown': \"\".\n"
            "Respond strictly as valid JSON matching this schema:\n"
            "{\n"
            '  "overall_verdict": "UPDATES_RECOMMENDED" | "REFUTED_NO_CHANGE" | "PARTIAL_UPDATES",\n'
            '  "summary_response": "2-4 sentence direct, objective response summarizing what was confirmed vs refuted with exact anchors",\n'
            '  "point_by_point": [\n'
            "    {\n"
            '      "claim": "Short summary of the critique point",\n'
            '      "status": "CONFIRMED" | "REFUTED" | "PARTIAL" | "UNVERIFIABLE",\n'
            '      "evidence": "Exact numbers/quotes from the manuscript with coordinate anchor(s)",\n'
            '      "resolution": "Specific correction made in updated_markdown, or why the current text stands"\n'
            "    }\n"
            "  ],\n"
            '  "has_updates": true,\n'
            '  "updated_markdown": "Complete revised markdown if has_updates is true, else empty string"\n'
            "}"
        )

        user_prompt = (
            f"### MANUSCRIPT CLINICAL CONTENT WITH COORDINATE ANCHORS:\n{manuscript_text}\n\n"
            f"### CURRENT {target_label.upper()}:\n{current_markdown}"
            f"{history_blob}\n\n"
            f"### CLINICIAN FEEDBACK / EXTERNAL AUDIT TO ADJUDICATE:\n{clean_critique}"
        )

        raw_json, _, used_model = self._invoke_gemini_rest(
            prompt=user_prompt,
            system_instruction=system_instruction,
            preferred_model=model_override,
            thinking_level="low",
            json_mode=True,
            temperature=0.0,
            max_output_tokens=12288
        )

        try:
            parsed = json.loads(raw_json)
        except Exception:
            cleaned = re.sub(r"^```(?:json)?|```$", "", raw_json.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(cleaned)

        updated_md = (parsed.get("updated_markdown") or "").strip()
        if updated_md:
            san = sanitize_and_verify_appraisal(updated_md, valid_anchor_dict)
            updated_md = san.cleaned_markdown

        return {
            "status": "success",
            "target": target,
            "overall_verdict": parsed.get("overall_verdict", "PARTIAL_UPDATES"),
            "summary_response": parsed.get("summary_response", ""),
            "point_by_point": parsed.get("point_by_point", []),
            "has_updates": bool(parsed.get("has_updates")) and bool(updated_md),
            "updated_markdown": updated_md,
            "selected_model": used_model
        }

    def clear_cache(self, filename: Optional[str] = None):
        """Clear query cache for a specific file or all files."""
        if filename:
            prefix = f"{filename.strip()}::"
            keys_to_del = [k for k in self._query_cache if k.startswith(prefix)]
            for k in keys_to_del:
                del self._query_cache[k]
        else:
            self._query_cache.clear()
