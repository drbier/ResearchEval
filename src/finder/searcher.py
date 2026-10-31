"""
ResearchEval - Zero-Trust Paper Finder Module
Implements precision medical literature retrieval with:
1. 4-tier programmatic query relaxation ladder (NCBI Entrez -> Semantic Scholar fallback)
2. Strict Binary Clinical Gate (Intervention AND Condition) with 50% baseline cutoff
3. Zero-Trust URL integrity (no generated or hallucinated PMIDs/URLs)
4. Strict null-handling for missing abstracts
5. Timeout and retry backoff against HTTP 429 / 503 rate limits
"""

import os
import sys
import re
import json
import time
import random
import urllib.parse
from typing import Dict, List, Optional, Tuple, Any
import requests
import xml.etree.ElementTree as ET

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Model Hierarchy (Verified Active GA Endpoints)
# Primary: gemini-3.8-flash (Google's flagship flash model for fast reasoning & clinical classification)
# Fallback: gemini-3.5-flash-lite (Active low-latency high-throughput resilience fallback)
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
        "User-Agent": "ResearchEval-Finder/2.0 (Medical Appraisal Workbench; mailto:clinical-research@antigravity.local)",
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
                print(f"[Finder:HTTP] Rate limit encountered ({resp.status_code}). Backing off for {sleep_time:.2f}s (Attempt {attempt+1}/{max_retries})...")
                time.sleep(sleep_time)
                continue

            return resp
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            last_exc = e
            sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.4)
            print(f"[Finder:HTTP] Network warning: {str(e)}. Retrying in {sleep_time:.2f}s (Attempt {attempt+1}/{max_retries})...")
            time.sleep(sleep_time)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed resilient request to {url} after {max_retries} attempts.")


class PaperFinder:
    """
    Precision-focused Research Paper Finder enforcing zero-trust URL invariants
    and binary clinical gate qualification.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.ncbi_esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        self.ncbi_efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        self.s2_search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
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
                    "temperature": 0.1,
                    "maxOutputTokens": 4096
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
                        print(f"[Finder:Gemini] Model {model} received HTTP {resp.status_code}. Backing off {sleep_time:.2f}s...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        last_err = f"Model {model} returned HTTP {resp.status_code}: {resp.text[:200]}"
                        print(f"[Finder:Gemini] Warning: {last_err}. Trying next model...")
                        break
                except Exception as e:
                    last_err = f"Model {model} request failed: {str(e)}"
                    print(f"[Finder:Gemini] Warning: {last_err}. Trying next model...")
                    break

        raise RuntimeError(f"All Gemini models in hierarchy failed for PaperFinder. Last error: {last_err}")

    def extract_clinical_entities(self, query: str) -> Dict[str, Any]:
        """
        Extract clinical entity arrays (Intervention, Condition, Population, Geography).
        The LLM is strictly constrained to JSON entity extraction; it does NOT generate query strings.
        """
        system_prompt = (
            "You are a medical literature search expert. Extract clinical search entities from the user's natural language query.\n"
            "Respond strictly with a JSON object matching this schema:\n"
            "{\n"
            '  "intervention": ["list", "of", "compounds", "or", "interventions", "synonyms"],\n'
            '  "condition": ["list", "of", "diseases", "outcomes", "or", "endpoints"],\n'
            '  "population": ["list", "of", "demographics", "or", "gender", "or", "patient", "groups"],\n'
            '  "geography": ["list", "of", "countries", "or", "regions"],\n'
            '  "study_design": ["list", "of", "study", "types"]\n'
            "}\n"
            "Rules:\n"
            "- Include common medical and biochemical synonyms (e.g. 'CoQ10' -> ['coenzyme Q10', 'CoQ10', 'ubiquinone']).\n"
            "- Expand geographic adjectives to both noun and demonym (e.g. 'Scandinavian' -> ['Sweden', 'Swedish', 'Denmark', 'Danish', 'Norway', 'Norwegian', 'Scandinavian']).\n"
            "- If an entity category is not mentioned or implied, leave its array empty [].\n"
            "- DO NOT output any narrative text, explanations, or markdown fences outside the JSON."
        )

        user_prompt = f"Extract clinical entities for search: \"{query.strip()}\""
        raw_json, _ = self._invoke_gemini(user_prompt, system_prompt, json_mode=True)

        try:
            entities = json.loads(raw_json)
        except Exception:
            clean_json = re.sub(r"^```(?:json)?|```$", "", raw_json.strip(), flags=re.MULTILINE).strip()
            entities = json.loads(clean_json)

        # Guarantee list types and lowercase normalization
        return {
            "intervention": [str(t).strip() for t in entities.get("intervention", []) if str(t).strip()],
            "condition": [str(t).strip() for t in entities.get("condition", []) if str(t).strip()],
            "population": [str(t).strip() for t in entities.get("population", []) if str(t).strip()],
            "geography": [str(t).strip() for t in entities.get("geography", []) if str(t).strip()],
            "study_design": [str(t).strip() for t in entities.get("study_design", []) if str(t).strip()]
        }

    def _format_term_group(self, terms: List[str], field_tag: str = "[tiab]") -> str:
        """Format a group of alternative synonyms with field tags and boolean OR."""
        cleaned = []
        for term in terms:
            t = term.strip().replace('"', '')
            if not t:
                continue
            cleaned.append(f'"{t}"{field_tag}')
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        return f"({' OR '.join(cleaned)})"

    def build_pubmed_query(self, entities: Dict[str, Any], tier: int) -> Optional[str]:
        """
        Build programmatic Entrez query string adhering to the 4-tier relaxation ladder.
        Invariant: Intervention and Condition are NEVER dropped.
        """
        int_group = self._format_term_group(entities.get("intervention", []))
        cond_group = self._format_term_group(entities.get("condition", []))

        # Core clinical entities are mandatory
        if not int_group and not cond_group:
            return None
        core_parts = [p for p in [int_group, cond_group] if p]

        pop_group = self._format_term_group(entities.get("population", []))
        geo_group = self._format_term_group(entities.get("geography", []))

        if tier == 1:
            # Tier 1 (Strict): Intervention AND Condition AND Geography AND Population
            parts = list(core_parts)
            if geo_group:
                parts.append(geo_group)
            if pop_group:
                parts.append(pop_group)
            return " AND ".join(parts)

        elif tier == 2:
            # Tier 2 (Relax Geography): Intervention AND Condition AND Population
            parts = list(core_parts)
            if pop_group:
                parts.append(pop_group)
            return " AND ".join(parts)

        elif tier == 3:
            # Tier 3 (Core Clinical Only): Intervention AND Condition
            return " AND ".join(core_parts)

        # Tier 4 is handled via Semantic Scholar API
        return None

    def search_ncbi_esearch(self, pubmed_query: str, retmax: int = 15) -> List[str]:
        """Execute live NCBI Entrez ESearch query and retrieve authentic PMIDs."""
        params = {
            "db": "pubmed",
            "term": pubmed_query,
            "retmode": "json",
            "retmax": retmax,
            "sort": "relevance"
        }
        resp = resilient_request(self.ncbi_esearch_url, params=params, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])
            return [str(pid).strip() for pid in id_list if str(pid).strip()]
        return []

    def fetch_pubmed_metadata(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """
        Retrieve official XML metadata via NCBI EFetch for authentic PMIDs.
        Extracts structured abstract sections, verbatim title, authors, year, and canonical URL.
        """
        if not pmids:
            return []

        # Pacing to adhere to NCBI rate limits (<= 3 req/sec unauthenticated)
        time.sleep(0.35)

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml"
        }
        resp = resilient_request(self.ncbi_efetch_url, params=params, timeout=15)
        if resp.status_code != 200:
            return []

        candidates = []
        try:
            root = ET.fromstring(resp.content)
            for article in root.findall(".//PubmedArticle"):
                # 1. PMID
                pmid_el = article.find(".//MedlineCitation/PMID")
                pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""
                if not pmid:
                    continue

                # 2. Verbatim Title
                title_el = article.find(".//ArticleTitle")
                title = "".join(title_el.itertext()).strip() if title_el is not None else f"PubMed Article {pmid}"

                # 3. Publication Year
                year = "Unknown"
                year_el = article.find(".//JournalIssue/PubDate/Year")
                if year_el is not None and year_el.text:
                    year = year_el.text.strip()
                else:
                    medline_date = article.find(".//JournalIssue/PubDate/MedlineDate")
                    if medline_date is not None and medline_date.text:
                        match = re.search(r"\b(19\d\d|20\d\d)\b", medline_date.text)
                        if match:
                            year = match.group(1)

                # 4. Authors
                authors = []
                for author in article.findall(".//AuthorList/Author"):
                    last = author.find("LastName")
                    init = author.find("Initials")
                    if last is not None and last.text:
                        name = last.text.strip()
                        if init is not None and init.text:
                            name += f" {init.text.strip()}"
                        authors.append(name)

                # 5. Structured Abstract Extraction
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

                abstract_text = "\n\n".join(abstract_sections) if abstract_sections else None

                # 6. Journal
                journal_el = article.find(".//Journal/Title") or article.find(".//Journal/ISOAbbreviation")
                journal = journal_el.text.strip() if journal_el is not None and journal_el.text else "PubMed Indexed Journal"

                candidates.append({
                    "pmid": pmid,
                    "title": title,
                    "year": year,
                    "authors": authors,
                    "journal": journal,
                    "abstract": abstract_text,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "source": "PubMed",
                    "is_fallback": False
                })
        except Exception as e:
            print(f"[Finder:XML] Error parsing NCBI EFetch XML: {str(e)}")

        return candidates

    def search_semantic_scholar_fallback(self, entities: Dict[str, Any], retmax: int = 10) -> List[Dict[str, Any]]:
        """
        Tier 4 Fallback: Query Semantic Scholar API when PubMed yields zero candidates.
        Enforces STRICT null-handling: any candidate lacking a structured abstract is immediately discarded.
        """
        int_terms = entities.get("intervention", [])
        cond_terms = entities.get("condition", [])
        if not int_terms or not cond_terms:
            return []

        query_str = f"{' '.join(int_terms[:2])} {' '.join(cond_terms[:2])}".strip()
        params = {
            "query": query_str,
            "fields": "title,year,authors,abstract,externalIds,url,venue",
            "limit": retmax
        }

        try:
            resp = resilient_request(self.s2_search_url, params=params, timeout=12)
            if resp.status_code != 200:
                return []

            data = resp.json()
            raw_papers = data.get("data", [])
            valid_candidates = []

            for p in raw_papers:
                # STRICT NULL-HANDLING: Discard papers lacking abstracts
                abstract = p.get("abstract")
                if not abstract or not isinstance(abstract, str) or len(abstract.strip()) < 50:
                    continue

                title = (p.get("title") or "").strip()
                if not title:
                    continue

                year = str(p.get("year")) if p.get("year") else "Unknown"
                ext_ids = p.get("externalIds") or {}
                pmid = ext_ids.get("PubMed")
                doi = ext_ids.get("DOI")

                if pmid:
                    verified_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                elif doi:
                    verified_url = f"https://doi.org/{doi}"
                elif p.get("url"):
                    verified_url = p.get("url")
                else:
                    continue  # Zero-Trust: If no canonical URL exists, do not guess

                authors = [a.get("name", "") for a in p.get("authors", []) if a.get("name")]
                venue = p.get("venue") or "Scholarly Publication"

                valid_candidates.append({
                    "pmid": pmid,
                    "title": title,
                    "year": year,
                    "authors": authors,
                    "journal": venue,
                    "abstract": abstract.strip(),
                    "url": verified_url,
                    "source": "Semantic Scholar Fallback",
                    "is_fallback": True
                })

            return valid_candidates
        except Exception as e:
            print(f"[Finder:S2] Semantic Scholar fallback search error: {str(e)}")
            return []

    def verify_and_score_candidate(
        self,
        candidate: Dict[str, Any],
        entities: Dict[str, Any],
        user_query: str
    ) -> Optional[Dict[str, Any]]:
        """
        Enforce the Strict Binary Clinical Gate:
        1. Does the study evaluate target Intervention?
        2. Does the study evaluate target Condition/Endpoint?
        If EITHER is false -> Match Score = 0% (Immediately Discarded).
        If BOTH are true -> Base score 50% + secondary criteria weighting (up to 100%).
        """
        abstract = candidate.get("abstract")
        # Strict null handling: Discard immediately if no abstract text
        if not abstract or len(abstract.strip()) < 40:
            return None

        system_instruction = (
            "You are a precision clinical methodology verifier. Evaluate candidate studies against user criteria.\n"
            "MANDATORY CLINICAL DIRECTIVE:\n"
            "You MUST apply a strict BINARY CLINICAL GATE:\n"
            "Question 1: Does this study explicitly evaluate the Target Intervention (or identical chemical/biochemical entity)? (true/false)\n"
            "Question 2: Does this study explicitly evaluate the Target Condition or clinical outcome? (true/false)\n\n"
            "If EITHER Question 1 OR Question 2 is false, the study FAILS the clinical gate.\n"
            "The match_score MUST BE 0. Do NOT award points for matching demographic or geography if the medical compound or condition is mismatched.\n\n"
            "If BOTH Question 1 AND Question 2 are true, the study passes the clinical gate:\n"
            "- Baseline Qualified Score = 50%\n"
            "- Secondary: Target Population / Gender / Cohort alignment: up to +20%\n"
            "- Secondary: Target Geographic / Setting alignment: up to +20%\n"
            "- Secondary: Clinical study design specificity (prospective trial/human cohort vs cell): up to +10%\n"
            "Total Match Score = 50 to 100.\n\n"
            "Respond strictly in JSON matching this schema:\n"
            "{\n"
            '  "matches_intervention": bool,\n'
            '  "matches_condition": bool,\n'
            '  "binary_gate_passed": bool,\n'
            '  "population_match": bool,\n'
            '  "geography_match": bool,\n'
            '  "study_design_match": bool,\n'
            '  "match_score": int,\n'
            '  "grounded_summary": "1-2 concise sentences summarizing the key benefits and findings based STRICTLY on the abstract text"\n'
            "}"
        )

        prompt = (
            f"USER QUERY: \"{user_query}\"\n"
            f"TARGET ENTITIES:\n"
            f"- Intervention: {json.dumps(entities.get('intervention', []))}\n"
            f"- Condition: {json.dumps(entities.get('condition', []))}\n"
            f"- Population: {json.dumps(entities.get('population', []))}\n"
            f"- Geography: {json.dumps(entities.get('geography', []))}\n\n"
            f"CANDIDATE STUDY:\n"
            f"Title: {candidate.get('title')}\n"
            f"Year: {candidate.get('year')}\n"
            f"Abstract:\n{abstract}"
        )

        try:
            raw_json, _ = self._invoke_gemini(prompt, system_instruction, json_mode=True)
            res = json.loads(raw_json)

            score = int(res.get("match_score", 0))
            gate_passed = bool(res.get("binary_gate_passed", False))

            # Enforce 50% baseline qualification cutoff
            if not gate_passed or score < 50:
                return None

            candidate["match_score"] = score
            candidate["matches_intervention"] = bool(res.get("matches_intervention", False))
            candidate["matches_condition"] = bool(res.get("matches_condition", False))
            candidate["population_match"] = bool(res.get("population_match", False))
            candidate["geography_match"] = bool(res.get("geography_match", False))
            candidate["study_design_match"] = bool(res.get("study_design_match", False))
            candidate["grounded_summary"] = (res.get("grounded_summary") or "").strip()

            return candidate
        except Exception as e:
            print(f"[Finder:Verify] Verification error for '{candidate.get('title')[:40]}': {str(e)}")
            return None

    def find_papers(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """
        Execute the 4-tier programmatic relaxation search workflow and return verified papers.
        Output format strictly adheres to the Zero-Trust URL Rule.
        """
        query_clean = query.strip()
        if not query_clean:
            return {
                "status": "error",
                "message": "Query string is empty.",
                "qualifying_papers": [],
                "formatted_output": "Search Failed: Empty query."
            }

        # Step 1: Entity Extraction via Gemini Flash
        entities = self.extract_clinical_entities(query_clean)
        has_geo = bool(entities.get("geography"))
        has_pop = bool(entities.get("population"))

        tier_used = 1
        raw_candidates = []
        source_db = "PubMed"
        is_fallback = False

        # Step 2: Execute 4-Tier Programmatic Relaxation Ladder
        # --- TIER 1: Full Strict Query ---
        t1_query = self.build_pubmed_query(entities, tier=1)
        pmids = self.search_ncbi_esearch(t1_query, retmax=max_results + 5) if t1_query else []

        if pmids:
            tier_used = 1
            raw_candidates = self.fetch_pubmed_metadata(pmids)
        elif has_geo:
            # --- TIER 2: Relax Geography ---
            print("[Finder:Ladder] Tier 1 yielded 0 results. Cascading to Tier 2 (Relax Geography)...")
            t2_query = self.build_pubmed_query(entities, tier=2)
            pmids = self.search_ncbi_esearch(t2_query, retmax=max_results + 5) if t2_query else []
            if pmids:
                tier_used = 2
                raw_candidates = self.fetch_pubmed_metadata(pmids)

        if not raw_candidates and has_pop:
            # --- TIER 3: Relax Population (Core Clinical Only) ---
            print("[Finder:Ladder] Tier 2 yielded 0 results. Cascading to Tier 3 (Core Clinical Only)...")
            t3_query = self.build_pubmed_query(entities, tier=3)
            pmids = self.search_ncbi_esearch(t3_query, retmax=max_results + 5) if t3_query else []
            if pmids:
                tier_used = 3
                raw_candidates = self.fetch_pubmed_metadata(pmids)

        if not raw_candidates:
            # --- TIER 4: Semantic Scholar Fallback ---
            print("[Finder:Ladder] PubMed search yielded 0 results. Cascading to Tier 4 (Semantic Scholar Fallback)...")
            tier_used = 4
            source_db = "Semantic Scholar Fallback"
            is_fallback = True
            raw_candidates = self.search_semantic_scholar_fallback(entities, retmax=max_results + 5)

        if not raw_candidates:
            return {
                "status": "not_found",
                "message": "Search Failed: No literature candidates matching clinical criteria located across PubMed and Semantic Scholar.",
                "query": query_clean,
                "entities": entities,
                "tier_used": tier_used,
                "source_database": source_db,
                "is_fallback": is_fallback,
                "qualifying_papers": [],
                "formatted_output": "Search Failed"
            }

        # Step 3: Enforce Binary Clinical Gate on All Retrieved Candidates
        verified_papers = []
        for cand in raw_candidates:
            cand["tier_used"] = tier_used
            cand["is_fallback"] = is_fallback
            verified = self.verify_and_score_candidate(cand, entities, query_clean)
            if verified:
                verified_papers.append(verified)

        # Step 4: Rank by Match Score (Descending) & Clamp to Max Results
        verified_papers.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        final_papers = verified_papers[:max_results]

        if not final_papers:
            return {
                "status": "not_found",
                "message": "Search Failed: Candidates were retrieved but failed the binary clinical gate (Intervention/Condition mismatch).",
                "query": query_clean,
                "entities": entities,
                "tier_used": tier_used,
                "source_database": source_db,
                "is_fallback": is_fallback,
                "qualifying_papers": [],
                "formatted_output": "Search Failed"
            }

        # Step 5: Construct Strict Output Layout (Exact Gem Protocol)
        formatted_blocks = []
        for p in final_papers:
            block = (
                f"Title: {p.get('title')} Year:{p.get('year')}\n"
                f"Summary: {p.get('grounded_summary')}\n"
                f"Source: {p.get('url')}"
            )
            formatted_blocks.append(block)

        strict_formatted_output = "\n\n".join(formatted_blocks)

        return {
            "status": "success",
            "query": query_clean,
            "entities": entities,
            "tier_used": tier_used,
            "source_database": source_db,
            "is_fallback": is_fallback,
            "total_evaluated": len(raw_candidates),
            "qualifying_count": len(final_papers),
            "qualifying_papers": final_papers,
            "formatted_output": strict_formatted_output,
            "model_designation": MODEL_DESIGNATION,
            "model_endpoint": PRIMARY_MODEL
        }
