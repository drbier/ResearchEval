"""
ResearchEval - Paper Summarizer Module
Implements structured multi-study science communicator briefings with:
1. Strict restriction to structured abstracts (no full-text drift)
2. Strict null-handling for inaccessible links or papers lacking abstracts ("Unable to access content")
3. Rate-limit pacing and exponential backoff retry for HTTP 429/503 mitigation
4. Sequential processing ensuring no data blending between studies
5. Grounded lay-language communication synthesis (Topic Intro, Categorization, Study Summaries, Conclusion, Final Analysis)
"""

import os
import sys
import re
import json
import time
import random
from typing import Dict, List, Optional, Tuple, Any
import requests
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Model Hierarchy (Verified Active GA Endpoints)
MODEL_DESIGNATION = "Gemini flash"
MODEL_HIERARCHY = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview"
]
PRIMARY_MODEL = MODEL_HIERARCHY[0]
FALLBACK_MODEL = MODEL_HIERARCHY[1]


def resilient_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    max_retries: int = 3,
    base_delay: float = 1.0
) -> requests.Response:
    """Execute HTTP request with exponential backoff on HTTP 429 and 503 rate limits."""
    req_headers = {
        "User-Agent": "ResearchEval-Summarizer/2.0 (Medical Science Communicator; mailto:clinical-research@antigravity.local)",
        "Accept": "application/json,application/xml,text/xml,*/*"
    }
    if headers:
        req_headers.update(headers)

    last_exc = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "POST":
                resp = requests.post(url, headers=req_headers, params=params, json=json_data, timeout=timeout)
            else:
                resp = requests.get(url, headers=req_headers, params=params, timeout=timeout)

            # Handle rate limiting (429) or temporary server unavailability (503)
            if resp.status_code in (429, 503):
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    sleep_time = float(retry_after)
                else:
                    sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.4)
                print(f"[Summarizer:HTTP] Rate limit encountered ({resp.status_code}). Backing off for {sleep_time:.2f}s (Attempt {attempt+1}/{max_retries})...")
                time.sleep(sleep_time)
                continue

            return resp
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            last_exc = e
            sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.4)
            print(f"[Summarizer:HTTP] Network warning: {str(e)}. Retrying in {sleep_time:.2f}s (Attempt {attempt+1}/{max_retries})...")
            time.sleep(sleep_time)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed resilient request to {url} after {max_retries} attempts.")


class PaperSummarizer:
    """
    Precision science communicator engine synthesizing multi-study literature batches
    into lay-accessible structured briefings with strict zero-hallucination guardrails.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.ncbi_efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        self.s2_paper_url = "https://api.semanticscholar.org/graph/v1/paper"
        self.model_designation = MODEL_DESIGNATION

    def _invoke_gemini(
        self,
        prompt: str,
        system_instruction: str,
        json_mode: bool = False,
        preferred_model: Optional[str] = None
    ) -> Tuple[str, str]:
        """Invoke Gemini with automated GA fallback ladder and rate-limit backoff."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable is not configured.")

        models_to_try = [preferred_model] if preferred_model else []
        for m in MODEL_HIERARCHY:
            if m not in models_to_try:
                models_to_try.append(m)

        last_err = ""
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
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            for attempt in range(3):
                try:
                    resp = requests.post(url, json=payload, timeout=45)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            text = "".join([p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)])
                            return text, model
                    elif resp.status_code in (429, 503):
                        sleep_time = (2 ** attempt) + random.uniform(0.2, 0.6)
                        print(f"[Summarizer:Gemini] Model {model} received HTTP {resp.status_code}. Backing off {sleep_time:.2f}s...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        last_err = f"Model {model} returned HTTP {resp.status_code}: {resp.text[:200]}"
                        print(f"[Summarizer:Gemini] Warning: {last_err}. Trying next model...")
                        break
                except Exception as e:
                    last_err = f"Model {model} request failed: {str(e)}"
                    print(f"[Summarizer:Gemini] Warning: {last_err}. Trying next model...")
                    break

        raise RuntimeError(f"All Gemini models in hierarchy failed for PaperSummarizer. Last error: {last_err}")

    def resolve_url_to_structured_abstract(self, raw_input: str) -> Dict[str, Any]:
        """
        Extract PMID/DOI and retrieve official structured abstract.
        Enforces strict null-handling: if abstract is missing, marks status as 'unavailable'.
        """
        clean_input = raw_input.strip()
        if not clean_input:
            return {
                "input_url": clean_input,
                "status": "unavailable",
                "error": "Unable to access content",
                "title": "Unable to access content",
                "structured_abstract": None
            }

        # 1. Check for PubMed ID in URL or raw numeric PMID
        pmid_match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", clean_input, re.IGNORECASE) or \
                     (re.match(r"^\d{6,9}$", clean_input) and re.search(r"(\d+)", clean_input))

        if pmid_match:
            pmid = pmid_match.group(1)
            return self._fetch_pubmed_abstract(pmid, clean_input)

        # 2. Check for DOI in URL
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", clean_input)
        if doi_match:
            doi = doi_match.group(0)
            return self._fetch_doi_abstract(doi, clean_input)

        # 3. Check for Semantic Scholar Paper ID
        s2_match = re.search(r"semanticscholar\.org/paper/(?:[^/]+/)?([a-f0-9]{40})", clean_input, re.IGNORECASE)
        if s2_match:
            s2_id = s2_match.group(1)
            return self._fetch_s2_abstract(s2_id, clean_input)

        # Unrecognized input format
        return {
            "input_url": clean_input,
            "status": "unavailable",
            "error": "Unable to access content",
            "title": "Unable to access content",
            "structured_abstract": None
        }

    def _fetch_pubmed_abstract(self, pmid: str, original_url: str) -> Dict[str, Any]:
        """Query NCBI EFetch for authentic XML title and structured abstract."""
        # Pacing to adhere to NCBI limits
        time.sleep(0.35)

        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml"
        }
        try:
            resp = resilient_request(self.ncbi_efetch_url, params=params, timeout=12)
            if resp.status_code != 200:
                return {
                    "input_url": original_url,
                    "status": "unavailable",
                    "error": "Unable to access content",
                    "title": "Unable to access content",
                    "structured_abstract": None
                }

            root = ET.fromstring(resp.content)
            article = root.find(".//PubmedArticle")
            if article is None:
                return {
                    "input_url": original_url,
                    "status": "unavailable",
                    "error": "Unable to access content",
                    "title": "Unable to access content",
                    "structured_abstract": None
                }

            # Extract exact title
            title_el = article.find(".//ArticleTitle")
            title = "".join(title_el.itertext()).strip() if title_el is not None else "Untitled Publication"

            # Extract structured abstract nodes
            abstract_nodes = article.findall(".//Abstract/AbstractText")
            abstract_sections = []
            for node in abstract_nodes:
                label = node.attrib.get("Label") or node.attrib.get("NlmCategory")
                text = "".join(node.itertext()).strip()
                if not text:
                    continue
                if label:
                    abstract_sections.append(f"{label.upper()}: {text}")
                else:
                    abstract_sections.append(text)

            # Strict null-handling: If abstract is empty, mark unavailable
            if not abstract_sections:
                return {
                    "input_url": original_url,
                    "pmid": pmid,
                    "status": "unavailable",
                    "error": "Unable to access content",
                    "title": title,
                    "structured_abstract": None
                }

            structured_abstract = "\n\n".join(abstract_sections)
            return {
                "input_url": original_url,
                "pmid": pmid,
                "status": "success",
                "title": title,
                "structured_abstract": structured_abstract
            }
        except Exception as e:
            print(f"[Summarizer:NCBI] Error fetching PMID {pmid}: {str(e)}")
            return {
                "input_url": original_url,
                "status": "unavailable",
                "error": "Unable to access content",
                "title": "Unable to access content",
                "structured_abstract": None
            }

    def _fetch_doi_abstract(self, doi: str, original_url: str) -> Dict[str, Any]:
        """Fetch abstract for a DOI via Semantic Scholar API with strict null-handling."""
        time.sleep(0.35)
        url = f"{self.s2_paper_url}/DOI:{doi}?fields=title,abstract,externalIds"
        try:
            resp = resilient_request(url, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                title = (data.get("title") or "").strip()
                abstract = (data.get("abstract") or "").strip()

                # Strict null-handling: If abstract is None or empty, mark unavailable
                if not abstract or len(abstract) < 40:
                    return {
                        "input_url": original_url,
                        "doi": doi,
                        "status": "unavailable",
                        "error": "Unable to access content",
                        "title": title or "Unable to access content",
                        "structured_abstract": None
                    }

                return {
                    "input_url": original_url,
                    "doi": doi,
                    "status": "success",
                    "title": title or f"DOI: {doi}",
                    "structured_abstract": abstract
                }
        except Exception as e:
            print(f"[Summarizer:DOI] Error fetching DOI {doi}: {str(e)}")

        return {
            "input_url": original_url,
            "doi": doi,
            "status": "unavailable",
            "error": "Unable to access content",
            "title": "Unable to access content",
            "structured_abstract": None
        }

    def _fetch_s2_abstract(self, s2_id: str, original_url: str) -> Dict[str, Any]:
        """Fetch abstract for a Semantic Scholar paper ID with strict null-handling."""
        time.sleep(0.35)
        url = f"{self.s2_paper_url}/{s2_id}?fields=title,abstract"
        try:
            resp = resilient_request(url, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                title = (data.get("title") or "").strip()
                abstract = (data.get("abstract") or "").strip()

                if not abstract or len(abstract) < 40:
                    return {
                        "input_url": original_url,
                        "status": "unavailable",
                        "error": "Unable to access content",
                        "title": title or "Unable to access content",
                        "structured_abstract": None
                    }

                return {
                    "input_url": original_url,
                    "status": "success",
                    "title": title or "Scholarly Publication",
                    "structured_abstract": abstract
                }
        except Exception:
            pass

        return {
            "input_url": original_url,
            "status": "unavailable",
            "error": "Unable to access content",
            "title": "Unable to access content",
            "structured_abstract": None
        }

    def summarize_single_study(self, study_data: Dict[str, Any]) -> str:
        """
        Summarize an individual study sequentially conforming strictly to the layout:
        Title:
        {Exact Title extracted from page}
        Summary:
        {Summary of benefits using ONLY the text found at URL}
        Source:
        {Exact Input URL}
        """
        input_url = study_data.get("input_url", "")
        status = study_data.get("status")
        title = study_data.get("title", "")
        abstract = study_data.get("structured_abstract")

        # Anti-Hallucination Guard: If content could not be accessed, do not guess
        if status != "success" or not abstract:
            return (
                f"Title:\n"
                f"{title if title and title != 'Unable to access content' else 'Unable to access content'}\n\n"
                f"Summary:\n"
                f"Unable to access content\n\n"
                f"Source:\n"
                f"{input_url}"
            )

        system_prompt = (
            "You are a science communicator renowned for your ability to explain complex medical and scientific topics to lay people.\n"
            "Your mission is to create a clear, accessible summary from the study abstract provided.\n"
            "STRICT PROTOCOLS:\n"
            "1. Grounding: Summarize the clinical findings and benefits using ONLY the explicit text in the abstract.\n"
            "   DO NOT bring in outside claims, speculation, or unverified mechanisms.\n"
            "2. Layperson Clarity: Explain statistical findings in plain, intuitive language without dumbing down the science.\n"
            "3. Format: Output ONLY the concise summary text (1-3 paragraphs) describing the benefits and findings.\n"
            "   Do not output titles, source labels, or meta-introductions here."
        )

        user_prompt = (
            f"STUDY TITLE: {title}\n\n"
            f"STRUCTURED ABSTRACT:\n{abstract}\n\n"
            "Write the lay-accessible summary of benefits and findings strictly grounded in this text."
        )

        summary_text, _ = self._invoke_gemini(user_prompt, system_prompt)
        summary_clean = summary_text.strip()

        return (
            f"Title:\n"
            f"{title}\n\n"
            f"Summary:\n"
            f"{summary_clean}\n\n"
            f"Source:\n"
            f"{input_url}"
        )

    def generate_overarching_synthesis(
        self,
        valid_studies: List[Dict[str, Any]],
        individual_summaries: List[str]
    ) -> Dict[str, str]:
        """
        Generate Section 1 (Topic Intro), Section 2 (Categorization Header),
        Section 4 (Conclusion), and Section 5 (Final Analysis).
        """
        if not valid_studies:
            return {
                "topic_intro": "No study content could be accessed from the provided links.",
                "categorization_header": "## General Health Topics",
                "conclusion": "No clinical conclusions could be drawn due to inaccessible study content.",
                "final_analysis": "Please check the provided URLs to ensure they link to public PubMed records or open abstracts."
            }

        abstracts_context = []
        for s in valid_studies:
            abstracts_context.append(f"TITLE: {s.get('title')}\nABSTRACT: {s.get('structured_abstract')}")
        context_blob = "\n\n---\n\n".join(abstracts_context)

        system_prompt = (
            "You are a world-class science communicator.\n"
            "Synthesize the overarching sections for a multi-study briefing based strictly on the provided study abstracts.\n"
            "Respond strictly in JSON matching this schema:\n"
            "{\n"
            '  "topic_intro": "1-2 sentence explanation of the general topic or compound (e.g., if studies are about Curcumin, explain what Curcumin is)",\n'
            '  "categorization_header": "## Compound Name (if multiple compounds or single compound) or ## Health Topic (e.g., ## Curcumin or ## Cardiovascular Health)",\n'
            '  "conclusion": "Brief overarching summary highlighting the benefits seen across all studies for each component",\n'
            '  "final_analysis": "Overarching summary of all the components combined with practical clinical context"\n'
            "}"
        )

        user_prompt = f"STUDY ABSTRACTS:\n{context_blob}"

        raw_json, _ = self._invoke_gemini(user_prompt, system_prompt, json_mode=True)
        try:
            res = json.loads(raw_json)
        except Exception:
            clean_json = re.sub(r"^```(?:json)?|```$", "", raw_json.strip(), flags=re.MULTILINE).strip()
            res = json.loads(clean_json)

        return {
            "topic_intro": res.get("topic_intro", "").strip(),
            "categorization_header": res.get("categorization_header", "## Key Clinical Findings").strip(),
            "conclusion": res.get("conclusion", "").strip(),
            "final_analysis": res.get("final_analysis", "").strip()
        }

    def summarize_batch(self, raw_inputs: List[str], max_batch_size: int = 10) -> Dict[str, Any]:
        """
        Execute end-to-end sequential multi-paper summarization.
        Guarantees:
        1. Sequential processing: processes each URL independently without blending data.
        2. Strict output layout:
           1. Topic Intro
           2. Categorization
           3. Study Summaries (Strict layout for each study)
           4. Conclusion
           5. Final Analysis
        """
        # Clean inputs while preserving order
        cleaned_urls = []
        for line in raw_inputs:
            # Handle multiple URLs pasted in a single multiline string or list
            for part in re.split(r"[\n\r,]+", str(line)):
                u = part.strip()
                if u and u not in cleaned_urls:
                    cleaned_urls.append(u)

        if not cleaned_urls:
            return {
                "status": "error",
                "message": "No valid URLs or PMIDs provided.",
                "formatted_markdown": "No URLs provided to summarize."
            }

        # Restrict batch size to 3-10
        process_batch = cleaned_urls[:max_batch_size]

        # Step 1: Sequential Ingestion (Strictly to Structured Abstracts)
        print(f"[Summarizer:Batch] Starting ingestion for {len(process_batch)} links...")
        ingested_studies = []
        valid_studies = []

        for idx, u in enumerate(process_batch):
            print(f"[Summarizer:Batch] Ingesting link {idx+1}/{len(process_batch)}: {u[:60]}...")
            study_data = self.resolve_url_to_structured_abstract(u)
            ingested_studies.append(study_data)
            if study_data.get("status") == "success" and study_data.get("structured_abstract"):
                valid_studies.append(study_data)

        # Step 2: Sequential Study Summaries (Strict Layout)
        print(f"[Summarizer:Batch] Generating {len(ingested_studies)} individual study summaries...")
        individual_blocks = []
        for study in ingested_studies:
            block = self.summarize_single_study(study)
            individual_blocks.append(block)

        # Step 3: Overarching Synthesis (Topic Intro, Categorization, Conclusion, Final Analysis)
        print(f"[Summarizer:Batch] Synthesizing overarching sections across {len(valid_studies)} accessible studies...")
        overarching = self.generate_overarching_synthesis(valid_studies, individual_blocks)

        # Step 4: Assemble Strict Output Document Layout
        doc_parts = []

        # 1. Topic Intro
        if overarching.get("topic_intro"):
            doc_parts.append(f"### 1. Topic Intro\n{overarching['topic_intro']}")

        # 2. Categorization
        header = overarching.get("categorization_header") or "## Study Findings"
        doc_parts.append(f"### 2. Categorization\n{header}")

        # 3. Study Summaries
        studies_formatted = "\n\n---\n\n".join(individual_blocks)
        doc_parts.append(f"### 3. Study Summaries\n\n{studies_formatted}")

        # 4. Conclusion
        if overarching.get("conclusion"):
            doc_parts.append(f"### 4. Conclusion\n{overarching['conclusion']}")

        # 5. Final Analysis
        if overarching.get("final_analysis"):
            doc_parts.append(f"### 5. Final Analysis\n{overarching['final_analysis']}")

        full_markdown = "\n\n".join(doc_parts)

        return {
            "status": "success",
            "total_requested": len(cleaned_urls),
            "total_processed": len(process_batch),
            "accessible_count": len(valid_studies),
            "inaccessible_count": len(process_batch) - len(valid_studies),
            "ingested_studies": ingested_studies,
            "individual_summaries": individual_blocks,
            "overarching": overarching,
            "formatted_markdown": full_markdown,
            "model_designation": MODEL_DESIGNATION,
            "model_endpoint": PRIMARY_MODEL
        }

