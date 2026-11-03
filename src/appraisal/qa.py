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

load_dotenv(r"D:\SSD-Drive\Antigravity\ResearchEval\.env")

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
        thinking_level: str = "low"
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
                    "temperature": 0.15,
                    "maxOutputTokens": 4096
                }
            }
            if effective_thinking:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": effective_thinking
                }
            try:
                resp = requests.post(url, json=payload, timeout=40)
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
            "2. EXACT ANCHOR CITATIONS: Every factual assertion, quantitative statistic, endpoint finding, or study detail MUST be immediately followed by its exact coordinate anchor in square brackets (e.g., [Abstract, Para 2], [Methods, Para 4], [Results, Table 1], [Results, TableNote p1_504], [Discussion, Para 8], [Doc_Header]).\n"
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

    def clear_cache(self, filename: Optional[str] = None):
        """Clear query cache for a specific file or all files."""
        if filename:
            prefix = f"{filename.strip()}::"
            keys_to_del = [k for k in self._query_cache if k.startswith(prefix)]
            for k in keys_to_del:
                del self._query_cache[k]
        else:
            self._query_cache.clear()
