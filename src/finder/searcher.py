import os
import sys
import re
import json
import time
import random
import urllib.parse
import concurrent.futures
import sqlite3
import hashlib
from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple, Any, Generator, Set
import requests
import xml.etree.ElementTree as ET

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Cache Logic Version - incrementing forces fresh evaluation across heuristic updates
CACHE_LOGIC_VERSION = "v2.2"

# Model Hierarchy (Verified Active GA Endpoints)
# Primary: gemini-3.8-flash (Active stable generation model, released Sep 2, 2026, no retirement date)
# Fallback 1: gemini-3.5-flash-lite (Active stable generation model, released Jul 21, 2026, no retirement date)
# Fallback 2: gemini-3-flash-preview (Active preview fast resilience fallback)
MODEL_DESIGNATION = "Gemini flash"
MODEL_HIERARCHY = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview"
]
PRIMARY_MODEL = MODEL_HIERARCHY[0]
FALLBACK_MODEL = MODEL_HIERARCHY[1]

# Stopwords to filter out of clinical intervention terms
SEARCH_STOPWORDS = {
    "combo", "combination", "supplementation", "supplement", "supplements",
    "therapy", "therapies", "treatment", "treatments", "trial", "trials",
    "study", "studies", "reduced", "reduces", "reducing", "reduction",
    "effect", "effects", "effective", "efficacy", "versus", "vs", "and", "or"
}

# Ambiguous short acronyms that collide with staging or statistical symbols
# These are strictly prohibited as bare search terms to prevent false positives (e.g. 'T4' tumor staging)
AMBIGUOUS_ACRONYMS = {
    "t4", "t3", "hr", "er", "pr", "cr", "or", "rr", "ci", "sd", "se"
}

# Intermediate surrogate biomarker terms to deprioritize when searching for hard clinical endpoints
# NOTE: 'thyroid' is permanently excluded so valid endocrine treatments are never penalized.
SURROGATE_BIOMARKER_TERMS = [
    "microrna", "telomere", "fibrosis", "fgf-23", "fibroblast growth factor",
    "d-dimer", "copeptin", "sirt1", "glutathione", "osteopontin", "selectin",
    "metabolic profile", "glycation", "renal function", "structural equation modelling",
    "point of view", "mr-proadm", "igf-1", "insulin-like", "oxidative stress",
    "redox status", "micro-rna", "fructosamine"
]


class SearchQueryCache:
    """
    SQLite Query Cache for F.A.C.T. Paper Finder.
    Enforces:
    1. Normalization: extract, lowercase, and alphabetize query terms with logic versioning.
    2. Concurrency Safety: WAL mode (Write-Ahead Logging) and connection timeouts.
    3. Degraded Result Suppression: never caches partial/degraded results or empty sets.
    4. Cache-Bypass: force_refresh support.
    5. TTL Cleanup: automated expiration pruning.
    """
    def __init__(self, db_path: str = "data/search_cache.db", default_ttl: int = 86400):
        self.db_path = db_path
        self.default_ttl = default_ttl
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Create a connection with 30-second busy timeout and WAL mode enabled, ensuring cleanup."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Idempotently initialize cache schema and index."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    normalized_query TEXT,
                    raw_query TEXT,
                    results_json TEXT,
                    created_at REAL,
                    ttl_seconds INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created ON search_cache(created_at);")
            conn.commit()

    @staticmethod
    def normalize_query(query: str) -> Tuple[str, str]:
        """
        Extract, lowercase, and alphabetize query terms, prepending CACHE_LOGIC_VERSION
        before applying the SHA-256 hash to invalidate stale heuristic formats.
        """
        words = re.findall(r'[a-z0-9]+', query.lower())
        sorted_words = sorted(words)
        normalized = " ".join(sorted_words)
        versioned = f"{CACHE_LOGIC_VERSION}:{normalized}"
        query_hash = hashlib.sha256(versioned.encode('utf-8')).hexdigest()
        return normalized, query_hash

    def get(self, query: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Retrieve cached results if fresh and not bypassed."""
        if force_refresh:
            return None

        _, query_hash = self.normalize_query(query)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT results_json, created_at, ttl_seconds FROM search_cache WHERE query_hash = ?",
                    (query_hash,)
                )
                row = cursor.fetchone()
                if not row:
                    return None

                results_json, created_at, ttl = row
                if time.time() - created_at > ttl:
                    return None

                data = json.loads(results_json)
                data["from_cache"] = True
                data["cached_at"] = created_at
                return data
        except Exception as e:
            print(f"[SearchCache] Error reading cache: {e}")
            return None

    def set(self, query: str, results: Dict[str, Any], ttl: Optional[int] = None):
        """Store results with SHA-256 hash key. Refuses to cache degraded or partial outputs."""
        # Never cache degraded, partial, error, or empty result sets
        if (
            results.get("is_degraded")
            or results.get("partial_results")
            or results.get("status") in ("error", "timeout")
            or results.get("qualifying_count", 0) == 0
        ):
            return

        normalized, query_hash = self.normalize_query(query)
        ttl_val = ttl or self.default_ttl
        now = time.time()

        save_data = {k: v for k, v in results.items() if k not in ("from_cache", "cached_at")}
        results_json = json.dumps(save_data)

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO search_cache (query_hash, normalized_query, raw_query, results_json, created_at, ttl_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(query_hash) DO UPDATE SET
                        results_json = excluded.results_json,
                        created_at = excluded.created_at,
                        ttl_seconds = excluded.ttl_seconds
                    """,
                    (query_hash, normalized, query, results_json, now, ttl_val)
                )
                conn.commit()
        except Exception as e:
            print(f"[SearchCache] Error writing cache: {e}")

    def cleanup_expired(self):
        """Prune expired rows from the cache database."""
        try:
            with self._get_connection() as conn:
                now = time.time()
                conn.execute("DELETE FROM search_cache WHERE (? - created_at) > ttl_seconds", (now,))
                conn.commit()
        except Exception as e:
            print(f"[SearchCache] Error cleaning up expired cache: {e}")


def resilient_request(
    url: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    base_delay: float = 0.5,
    timeout: int = 15
) -> requests.Response:
    """Network wrapper with exponential backoff and rate-limit handling."""
    req_headers = {
        "User-Agent": "FACT-ResearchEval/2.2 (Clinical Evidence System; mailto:info@wonkproject.com)",
        **(headers or {})
    }

    last_exc = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "POST":
                resp = requests.post(url, headers=req_headers, params=params, json=json_data, timeout=timeout)
            else:
                resp = requests.get(url, headers=req_headers, params=params, timeout=timeout)

            if resp.status_code == 200:
                return resp
            elif resp.status_code in (429, 500, 502, 503, 504):
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.4)
                print(f"[Finder:HTTP] Status {resp.status_code} from {url}. Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                continue
            else:
                return resp
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            last_exc = e
            sleep_time = base_delay * (2 ** attempt) + random.uniform(0.1, 0.4)
            print(f"[Finder:HTTP] Network warning: {str(e)}. Retrying in {sleep_time:.2f}s...")
            time.sleep(sleep_time)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed resilient request to {url} after {max_retries} attempts.")


class CanonicalPaperStore:
    """
    Deterministic multi-attribute deduplication store for literature search candidates.
    Enforces resolution hierarchy: DOI > PMID > PMCID > Normalized Title Hash.
    Ensures candidates across PubMed, Europe PMC, and Semantic Scholar merge seamlessly
    into a unified canonical citation record without duplicate cards.
    """
    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._key_to_canonical: Dict[str, str] = {}

    @staticmethod
    def extract_keys(paper: Dict[str, Any]) -> List[str]:
        keys = []
        # 1. Normalized DOI (highest precedence)
        doi = str(paper.get("doi") or "").strip().lower()
        if doi and doi != "none":
            clean_doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi).strip()
            if clean_doi:
                keys.append(f"doi:{clean_doi}")

        # 2. PMID
        pmid = str(paper.get("pmid") or "").strip()
        if pmid and pmid.lower() != "none" and pmid.isdigit():
            keys.append(f"pmid:{pmid}")

        # 3. PMCID
        pmcid = str(paper.get("pmcid") or "").strip().upper()
        if pmcid and pmcid != "NONE":
            if not pmcid.startswith("PMC"):
                pmcid = f"PMC{pmcid}"
            keys.append(f"pmc:{pmcid}")

        # 4. Normalized Title Hash (fallback when identifiers are absent)
        title = str(paper.get("title") or "").strip()
        norm_title = re.sub(r"[^a-z0-9]", "", title.lower())
        if len(norm_title) >= 12:
            thash = hashlib.md5(norm_title.encode("utf-8")).hexdigest()[:16]
            keys.append(f"title:{thash}")

        return keys

    def add_or_merge(self, paper: Dict[str, Any]) -> bool:
        """
        Add paper if new, or merge metadata into existing canonical record.
        Returns True if a new paper was added, False if merged.
        """
        keys = self.extract_keys(paper)
        if not keys:
            raw_id = f"raw:{len(self._store)}"
            self._store[raw_id] = dict(paper)
            return True

        canonical_id = None
        for k in keys:
            if k in self._key_to_canonical:
                canonical_id = self._key_to_canonical[k]
                break

        if canonical_id is None:
            # New unique candidate: pick primary key as canonical ID
            canonical_id = keys[0]
            self._store[canonical_id] = dict(paper)
            for k in keys:
                self._key_to_canonical[k] = canonical_id
            return True
        else:
            # Merge missing fields and enrich links
            existing = self._store[canonical_id]
            for field in ["doi", "pmid", "pmcid", "pmc_url", "abstract", "journal"]:
                if not existing.get(field) and paper.get(field):
                    existing[field] = paper[field]

            if not existing.get("has_full_text") and paper.get("has_full_text"):
                existing["has_full_text"] = True
                if paper.get("pmc_url"):
                    existing["pmc_url"] = paper["pmc_url"]

            # Merge source attribution if multi-source
            if paper.get("source") and paper.get("source") != existing.get("source"):
                existing["source"] = f"{existing.get('source', '')} + {paper.get('source', '')}"

            # Map any new keys to the existing canonical ID (transitive closure)
            for k in keys:
                if k not in self._key_to_canonical:
                    self._key_to_canonical[k] = canonical_id

            # Keep higher match or priority score if present
            if paper.get("match_score", 0) > existing.get("match_score", 0):
                existing["match_score"] = paper["match_score"]
            if paper.get("priority_score", 0) > existing.get("priority_score", 0):
                existing["priority_score"] = paper["priority_score"]

            return False

    def get_all(self) -> List[Dict[str, Any]]:
        return list(self._store.values())

    def contains(self, paper: Dict[str, Any]) -> bool:
        keys = self.extract_keys(paper)
        return any(k in self._key_to_canonical for k in keys)


class PaperFinder:
    """
    Precision-focused Research Paper Finder enforcing bidirectional entity expansion,
    zero-trust URL invariants, deterministic pre-ranking, and binary clinical qualification.
    """

    NEGATION_TOKENS = [
        "without", "excluding", "except", "non-", "negative for",
        "neither", "nor", "in the absence of", "no history of", "free of"
    ]

    def __init__(self, api_key: Optional[str] = None, cache_db_path: str = "data/search_cache.db"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.ncbi_esearch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        self.ncbi_efetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        self.europe_pmc_search_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        self.s2_search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        self.model_designation = MODEL_DESIGNATION
        self.cache = SearchQueryCache(db_path=cache_db_path)
        self.cache.cleanup_expired()

    def determine_thinking_level(self, query: str, entities: Optional[Dict[str, Any]] = None) -> str:
        """Dynamic thinkingLevel heuristic: escalates to 'medium' for complex or comparative queries."""
        q_lower = query.lower()
        if any(neg in q_lower for neg in self.NEGATION_TOKENS):
            return "medium"
        if len(query.strip()) > 120:
            return "medium"
        if any(comp in q_lower for comp in [" vs ", " vs. ", " versus ", " compared to ", " superiority "]):
            return "medium"
        if entities and entities.get("is_combination"):
            return "medium"
        return "low"

    def _invoke_gemini(
        self,
        prompt: str,
        system_instruction: str,
        json_mode: bool = False,
        preferred_model: Optional[str] = None,
        thinking_level: Optional[str] = None,
        timeout: int = 35
    ) -> Tuple[str, str]:
        """Invoke Gemini with automated GA fallback ladder, rate-limit backoff, and dynamic thinkingConfig."""
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
                    "maxOutputTokens": 8192
                }
            }
            if thinking_level:
                payload["generationConfig"]["thinkingConfig"] = {
                    "thinkingLevel": thinking_level
                }
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"

            for attempt in range(3):
                try:
                    resp = requests.post(url, json=payload, timeout=timeout)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            text = "".join([p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)])
                            return text, model
                    elif resp.status_code in (429, 503):
                        err_body = resp.text.lower()
                        if "quota" in err_body or "resource_exhausted" in err_body:
                            print(f"[Finder:Gemini] Model {model} exceeded daily quota. Failing over to next model...")
                            break
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
        Extract clinical search entities (Intervention, Condition, Population, Geography).
        Performs Bidirectional Entity Expansion: expands downward to specific chemical/brand synonyms
        and upward to parent therapeutic classes (e.g. levothyroxine -> thyroid hormone, THRT)
        and MeSH terms. Strictly filters out bare ambiguous abbreviations like 'T4'.
        """
        system_prompt = (
            "You are a medical literature search expert. Extract clinical search entities from the user's natural language query.\n"
            "Respond strictly with a JSON object matching this schema:\n"
            "{\n"
            '  "is_combination": bool,\n'
            '  "intervention_agents": [\n'
            '    {\n'
            '      "agent": "Primary name of distinct compound/drug/intervention",\n'
            '      "synonyms": ["list", "of", "specific", "chemical", "and", "brand", "synonyms"],\n'
            '      "parent_classes": ["list", "of", "broader", "therapeutic", "umbrella", "terms", "and", "clinical", "classes"],\n'
            '      "mesh_terms": ["list", "of", "authoritative", "MeSH", "headings"]\n'
            '    }\n'
            '  ],\n'
            '  "known_study_names": ["list of recognized clinical trial names or acronyms, e.g. KiSel-10, Q-SYMBIO"],\n'
            '  "lead_investigators": ["list of key landmark investigators/authors, e.g. Alehagen"],\n'
            '  "condition": ["core primary disease or pathological condition, e.g. breast cancer, breast neoplasms"],\n'
            '  "endpoints": ["clinical outcomes, prognostic metrics, or endpoints, e.g. progression, proliferation, survival, mortality, recurrence, resistance"],\n'
            '  "population": ["list", "of", "demographics", "or", "gender", "or", "patient", "groups"],\n'
            '  "geography": ["list", "of", "countries", "or", "regions"],\n'
            '  "study_design": ["list", "of", "study", "types"]\n'
            "}\n"
            "Rules:\n"
            "- Perform BIDIRECTIONAL EXPANSION for medications: expand downwards (brands, salts) AND upwards to the parent therapeutic class.\n"
            "  * Example: for 'levothyroxine', synonyms: ['L-thyroxine', 'synthroid', 'levoxyl', 'thyroxine'], parent_classes: ['thyroid hormone', 'thyroid hormones', 'exogenous thyroid hormone', 'thyroid hormone replacement therapy', 'THRT'], mesh_terms: ['Thyroxine', 'Thyroid Hormones'].\n"
            "- CRITICAL DECOUPLING OF CONDITION VS ENDPOINTS: Decouple the core disease/condition from clinical outcomes or biological endpoints.\n"
            "  * 'condition': Core primary disease or pathological condition (e.g. ['breast cancer', 'breast neoplasms']). DO NOT attach outcome words to condition phrases.\n"
            "  * 'endpoints': Specific clinical outcomes, prognostic metrics, or endpoints mentioned or implied (e.g. if query mentions 'progression', include ['progression', 'proliferation', 'survival', 'mortality', 'recurrence', 'resistance']). If no endpoints are mentioned or implied, leave [] empty.\n"
            "- CRITICAL GUARDRAIL: DO NOT include bare ambiguous abbreviations like 'T4', 'T3', 'HR', 'PR', 'CR' in synonyms (they collide with cancer staging and statistical metrics).\n"
            "- DO NOT include generic meta-words like 'combo', 'combination', 'supplementation', 'supplement', 'therapy', 'trial', 'study', 'reduced' as agents or synonyms.\n"
            "- Expand geographic adjectives to both noun and demonym (e.g. 'Scandinavian' -> ['Sweden', 'Swedish', 'Denmark', 'Danish', 'Norway', 'Norwegian']).\n"
            "- If an entity category is not mentioned or implied, leave its array empty [].\n"
            "- DO NOT output narrative text outside the JSON."
        )

        user_prompt = f"Extract clinical entities for search: \"{query.strip()}\""
        thinking_level = self.determine_thinking_level(query)
        raw_json, _ = self._invoke_gemini(user_prompt, system_prompt, json_mode=True, thinking_level=thinking_level)

        try:
            entities = json.loads(raw_json)
        except Exception:
            clean_json = re.sub(r"^```(?:json)?|```$", "", raw_json.strip(), flags=re.MULTILINE).strip()
            entities = json.loads(clean_json)

        # Parse intervention agents with parent classes and mesh terms
        raw_agents = entities.get("intervention_agents", [])
        parsed_agents = []
        flat_interventions = []
        flat_parent_classes = []

        if isinstance(raw_agents, list):
            for item in raw_agents:
                if isinstance(item, dict):
                    agent_name = str(item.get("agent", "")).strip()
                    synonyms = [str(s).strip() for s in item.get("synonyms", []) if str(s).strip()]
                    parent_classes = [str(p).strip() for p in item.get("parent_classes", []) if str(p).strip()]
                    mesh_terms = [str(m).strip() for m in item.get("mesh_terms", []) if str(m).strip()]

                    # Clean stopwords and ambiguous acronyms
                    agent_clean = agent_name if (agent_name.lower() not in SEARCH_STOPWORDS and agent_name.lower() not in AMBIGUOUS_ACRONYMS) else ""
                    synonyms_clean = [s for s in synonyms if s.lower() not in SEARCH_STOPWORDS and s.lower() not in AMBIGUOUS_ACRONYMS]
                    parent_clean = [p for p in parent_classes if p.lower() not in SEARCH_STOPWORDS and p.lower() not in AMBIGUOUS_ACRONYMS]
                    mesh_clean = [m for m in mesh_terms if m.lower() not in SEARCH_STOPWORDS and m.lower() not in AMBIGUOUS_ACRONYMS]

                    if agent_clean or synonyms_clean or parent_clean:
                        parsed_agents.append({
                            "agent": agent_clean or (synonyms_clean[0] if synonyms_clean else (parent_clean[0] if parent_clean else "")),
                            "synonyms": synonyms_clean,
                            "parent_classes": parent_clean,
                            "mesh_terms": mesh_clean
                        })
                        if agent_clean:
                            flat_interventions.append(agent_clean)
                        flat_interventions.extend(synonyms_clean)
                        flat_parent_classes.extend(parent_clean)
                elif isinstance(item, str) and item.strip():
                    val = item.strip()
                    if val.lower() not in SEARCH_STOPWORDS and val.lower() not in AMBIGUOUS_ACRONYMS:
                        parsed_agents.append({"agent": val, "synonyms": [], "parent_classes": [], "mesh_terms": []})
                        flat_interventions.append(val)

        # Backward compatibility fallback
        if not parsed_agents and entities.get("intervention"):
            for item in entities.get("intervention", []):
                val = str(item).strip()
                if val and val.lower() not in SEARCH_STOPWORDS and val.lower() not in AMBIGUOUS_ACRONYMS:
                    flat_interventions.append(val)
            if flat_interventions:
                parsed_agents.append({"agent": flat_interventions[0], "synonyms": flat_interventions[1:], "parent_classes": [], "mesh_terms": []})

        # Deduplicate
        seen = set()
        dedup_flat = []
        for term in flat_interventions:
            low = term.lower()
            if low not in seen:
                seen.add(low)
                dedup_flat.append(term)

        seen_pc = set()
        dedup_parent = []
        for term in flat_parent_classes:
            low = term.lower()
            if low not in seen_pc:
                seen_pc.add(low)
                dedup_parent.append(term)

        raw_endpoints = entities.get("endpoints", [])
        if isinstance(raw_endpoints, str):
            raw_endpoints = [raw_endpoints]
        endpoints_clean = [
            str(t).strip() for t in raw_endpoints
            if str(t).strip() and str(t).lower() not in SEARCH_STOPWORDS and str(t).lower() not in AMBIGUOUS_ACRONYMS
        ]

        is_combination = bool(entities.get("is_combination", False)) or len(parsed_agents) > 1

        return {
            "is_combination": is_combination,
            "intervention_agents": parsed_agents,
            "intervention": dedup_flat,
            "parent_classes": dedup_parent,
            "known_study_names": [str(t).strip() for t in entities.get("known_study_names", []) if str(t).strip()],
            "lead_investigators": [str(t).strip() for t in entities.get("lead_investigators", []) if str(t).strip()],
            "condition": [str(t).strip() for t in entities.get("condition", []) if str(t).strip() and str(t).lower() not in SEARCH_STOPWORDS],
            "endpoints": endpoints_clean,
            "population": [str(t).strip() for t in entities.get("population", []) if str(t).strip()],
            "geography": [str(t).strip() for t in entities.get("geography", []) if str(t).strip()],
            "study_design": [str(t).strip() for t in entities.get("study_design", []) if str(t).strip()]
        }

    def _format_term_group(
        self,
        terms: List[str],
        field_tag: str = "[tw]",
        mesh_terms: Optional[List[str]] = None
    ) -> str:
        """Format a group of alternative synonyms with field tags and boolean OR."""
        cleaned = []
        seen = set()
        for term in terms:
            t = term.strip().replace('"', '')
            if not t or t.lower() in SEARCH_STOPWORDS or t.lower() in AMBIGUOUS_ACRONYMS:
                continue
            if t.lower() not in seen:
                seen.add(t.lower())
                cleaned.append(f'"{t}"{field_tag}')

        if mesh_terms:
            for m in mesh_terms:
                m_clean = m.strip().replace('"', '')
                if m_clean and m_clean.lower() not in seen:
                    seen.add(m_clean.lower())
                    cleaned.append(f'"{m_clean}"[MeSH Terms]')

        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        return f"({' OR '.join(cleaned)})"

    def _format_intervention_query(self, entities: Dict[str, Any], include_parent_class: bool = True, field_tag: str = "[tw]") -> str:
        """
        Format intervention query enforcing conjunction (AND) across distinct co-agents
        and disjunction (OR) across synonyms within each agent.
        Includes parent classes and MeSH terms when include_parent_class is True.
        """
        agents = entities.get("intervention_agents", [])
        if agents and len(agents) > 0:
            agent_clauses = []
            for a in agents:
                terms = []
                if a.get("agent"):
                    terms.append(a["agent"])
                if a.get("synonyms"):
                    terms.extend(a["synonyms"])
                if include_parent_class and a.get("parent_classes"):
                    terms.extend(a["parent_classes"])

                mesh = a.get("mesh_terms", []) if include_parent_class else []
                clause = self._format_term_group(terms, field_tag=field_tag, mesh_terms=mesh)
                if clause:
                    agent_clauses.append(clause)
            if agent_clauses:
                return " AND ".join(agent_clauses) if len(agent_clauses) > 1 else agent_clauses[0]

        # Fallback to flat intervention list
        flat_terms = list(entities.get("intervention", []))
        if include_parent_class and entities.get("parent_classes"):
            flat_terms.extend(entities.get("parent_classes", []))
        return self._format_term_group(flat_terms, field_tag=field_tag)

    def build_pubmed_query(
        self,
        entities: Dict[str, Any],
        tier: Any,
        field_tag: str = "[tw]"
    ) -> Optional[str]:
        """
        Build programmatic Entrez query string adhering to the modernized ladder:
        - Tier 1: Specific Drug terms + Condition + Endpoints + Geography + Population
        - Tier 1b (Semantic Expansion): (Specific Drug OR Parent Classes OR MeSH) + Condition + Endpoints + Geo + Pop
        - Tier 2 (Relax Geography): (Specific OR Parent Class) + Condition + Endpoints + Population
        - Tier 3 (Core Clinical Only): (Specific OR Parent Class) + Condition (drops Endpoints, Geo, Pop)
        - Tier 4: Handled via Semantic Scholar API
        """
        tier_str = str(tier).lower().strip()
        include_parent = tier_str in ("1b", "2", "3")

        int_group = self._format_intervention_query(entities, include_parent_class=include_parent, field_tag=field_tag)
        cond_group = self._format_term_group(entities.get("condition", []), field_tag=field_tag)
        endpoints_group = self._format_term_group(entities.get("endpoints", []), field_tag=field_tag) if tier_str not in ("3", "3.0") else ""

        if not int_group and not cond_group:
            return None
        core_parts = [p for p in [int_group, cond_group] if p]
        if endpoints_group and tier_str not in ("3", "3.0"):
            core_parts.append(endpoints_group)

        pop_group = self._format_term_group(entities.get("population", []), field_tag=field_tag)
        geo_group = self._format_term_group(entities.get("geography", []), field_tag=field_tag)

        # Landmark study / investigator boosts
        landmark_parts = []
        for name in entities.get("known_study_names", []):
            if name.strip():
                landmark_parts.append(f'"{name.strip()}"[tw]')
        for auth in entities.get("lead_investigators", []):
            if auth.strip():
                landmark_parts.append(f'"{auth.strip()}"[Author]')
        landmark_clause = f"({' OR '.join(landmark_parts)})" if landmark_parts else None

        if tier_str in ("1", "1.0"):
            parts = list(core_parts)
            if geo_group:
                parts.append(geo_group)
            if pop_group:
                parts.append(pop_group)
            base_t1 = " AND ".join(parts)
            if landmark_clause and cond_group:
                return f"({landmark_clause} OR ({base_t1}))"
            return base_t1

        elif tier_str in ("1b", "1.5"):
            parts = list(core_parts)
            if geo_group:
                parts.append(geo_group)
            if pop_group:
                parts.append(pop_group)
            base_t1b = " AND ".join(parts)
            if landmark_clause and cond_group:
                return f"({landmark_clause} OR ({base_t1b}))"
            return base_t1b

        elif tier_str in ("2", "2.0"):
            parts = list(core_parts)
            if pop_group:
                parts.append(pop_group)
            base_t2 = " AND ".join(parts)
            if landmark_clause and cond_group:
                return f"({landmark_clause} OR ({base_t2}))"
            return base_t2

        elif tier_str in ("3", "3.0"):
            base_t3 = " AND ".join(core_parts)
            if landmark_clause and cond_group:
                return f"({landmark_clause} OR ({base_t3}))"
            return base_t3

        return None

    def search_ncbi_esearch(self, pubmed_query: str, retmax: int = 100, timeout: int = 15) -> List[str]:
        """Execute live NCBI Entrez ESearch query and retrieve authentic PMIDs."""
        params = {
            "db": "pubmed",
            "term": pubmed_query,
            "retmode": "json",
            "retmax": retmax,
            "sort": "relevance",
            "tool": "fact",
            "email": "info@wonkproject.com"
        }
        resp = resilient_request(self.ncbi_esearch_url, params=params, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            id_list = data.get("esearchresult", {}).get("idlist", [])
            return [str(pid).strip() for pid in id_list if str(pid).strip()]
        return []

    def fetch_pubmed_metadata(self, pmids: List[str], timeout: int = 25) -> List[Dict[str, Any]]:
        """
        Retrieve official XML metadata via NCBI EFetch in chunks of 50.
        Extracts structured abstract sections, verbatim title, authors, year, and canonical URL.
        """
        if not pmids:
            return []

        candidates = []
        chunk_size = 50

        for i in range(0, len(pmids), chunk_size):
            chunk = pmids[i:i + chunk_size]
            time.sleep(0.35)  # Respect NCBI 3 req/sec rate limit

            params = {
                "db": "pubmed",
                "id": ",".join(chunk),
                "retmode": "xml",
                "tool": "fact",
                "email": "info@wonkproject.com"
            }
            try:
                resp = resilient_request(self.ncbi_efetch_url, method="POST", params=params, timeout=timeout)
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)
                for article in root.findall(".//PubmedArticle"):
                    pmid_el = article.find(".//MedlineCitation/PMID")
                    pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""
                    if not pmid:
                        continue

                    title_el = article.find(".//ArticleTitle")
                    title = "".join(title_el.itertext()).strip() if title_el is not None else f"PubMed Article {pmid}"

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

                    authors = []
                    for author in article.findall(".//AuthorList/Author"):
                        last = author.find("LastName")
                        init = author.find("Initials")
                        if last is not None and last.text:
                            name = last.text.strip()
                            if init is not None and init.text:
                                name += f" {init.text.strip()}"
                            authors.append(name)

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

                    title_node = article.find(".//Journal/Title")
                    iso_node = article.find(".//Journal/ISOAbbreviation")
                    journal_el = title_node if title_node is not None else iso_node
                    journal = journal_el.text.strip() if journal_el is not None and journal_el.text else "PubMed Indexed Journal"

                    pmcid = None
                    doi = None
                    for aid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
                        id_type = aid.attrib.get("IdType")
                        val = aid.text.strip() if aid.text else ""
                        if not val:
                            continue
                        if id_type == "pmc":
                            pmcid = val if val.upper().startswith("PMC") else f"PMC{val}"
                        elif id_type == "doi" and not doi:
                            doi = val

                    has_full_text = bool(pmcid)
                    pmc_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else None

                    candidates.append({
                        "pmid": pmid,
                        "title": title,
                        "year": year,
                        "authors": authors,
                        "journal": journal,
                        "abstract": abstract_text,
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "pmcid": pmcid,
                        "doi": doi,
                        "has_full_text": has_full_text,
                        "pmc_url": pmc_url,
                        "source": "PubMed",
                        "is_fallback": False
                    })
            except Exception as e:
                print(f"[Finder:XML] Error parsing NCBI EFetch XML chunk: {str(e)}")

        return candidates

    def search_europe_pmc(self, entities: Dict[str, Any], retmax: int = 25, timeout: int = 12) -> List[Dict[str, Any]]:
        """
        Query Europe PMC REST API using MEDLINE/PMC filtering to retrieve high-relevance peer-reviewed candidates.
        Enforces resultType=core so abstractText is included for subsequent qualification.
        """
        terms = []
        # 1. Interventions (include primary agents and parent classes)
        int_terms = entities.get("intervention", [])
        if not int_terms and entities.get("parent_classes"):
            int_terms = entities.get("parent_classes", [])
        if int_terms:
            int_clean = [
                f'"{t.replace(chr(34), "")}"'
                for t in int_terms[:3]
                if t.lower() not in SEARCH_STOPWORDS and t.lower() not in AMBIGUOUS_ACRONYMS
            ]
            if int_clean:
                terms.append(f"({' OR '.join(int_clean)})")

        # 2. Condition
        cond_terms = entities.get("condition", [])
        if cond_terms:
            cond_clean = [
                f'"{c.replace(chr(34), "")}"'
                for c in cond_terms[:2]
                if c.lower() not in SEARCH_STOPWORDS
            ]
            if cond_clean:
                terms.append(f"({' OR '.join(cond_clean)})")

        # 3. Known study names
        study_names = entities.get("known_study_names", [])
        if study_names:
            study_clean = [f'"{s.replace(chr(34), "")}"' for s in study_names[:2]]
            if study_clean:
                terms.append(f"({' OR '.join(study_clean)})")

        if not terms:
            return []

        core_query = " AND ".join(terms)
        full_query = f"(src:med OR src:pmc) AND ({core_query})"
        params = {
            "query": full_query,
            "resultType": "core",
            "pageSize": min(retmax, 50),
            "format": "json"
        }

        candidates = []
        try:
            resp = resilient_request(self.europe_pmc_search_url, method="GET", params=params, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("resultList", {}).get("result", [])
                for item in results:
                    title = (item.get("title") or "").rstrip(".")
                    abstract = (item.get("abstractText") or "").strip()
                    if not title or len(abstract) < 40:
                        continue

                    pmid = str(item.get("pmid") or "").strip()
                    if not pmid.isdigit():
                        pmid = None

                    doi = item.get("doi")
                    pmcid = item.get("pmcid")
                    if pmcid and not str(pmcid).upper().startswith("PMC"):
                        pmcid = f"PMC{pmcid}"

                    year = str(item.get("pubYear") or "Unknown")
                    journal = item.get("journalTitle") or "Europe PMC Indexed Journal"
                    author_str = item.get("authorString") or ""
                    authors = [a.strip() for a in author_str.split(",") if a.strip()]

                    has_full_text = item.get("isOpenAccess") == "Y" or bool(pmcid)
                    pmc_url = f"https://europepmc.org/articles/{pmcid}" if pmcid else None
                    if not pmc_url and pmid:
                        pmc_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

                    candidate = {
                        "pmid": pmid,
                        "title": title,
                        "year": year,
                        "authors": authors,
                        "journal": journal,
                        "abstract": abstract,
                        "url": pmc_url or (f"https://doi.org/{doi}" if doi else f"https://europepmc.org/abstract/MED/{pmid or item.get('id')}"),
                        "pmcid": pmcid,
                        "doi": doi,
                        "has_full_text": has_full_text,
                        "pmc_url": pmc_url,
                        "source": "Europe PMC",
                        "is_fallback": False
                    }
                    candidates.append(candidate)
        except Exception as e:
            print(f"[Finder:EuropePMC] Error querying Europe PMC search: {e}")

        return candidates

    def search_semantic_scholar_fallback(self, entities: Dict[str, Any], retmax: int = 15, timeout: int = 15) -> List[Dict[str, Any]]:
        """Tier 4 Fallback: Query Semantic Scholar API when PubMed yields zero candidates."""
        int_agents = [a.get("agent", "") for a in entities.get("intervention_agents", []) if a.get("agent")]
        if not int_agents:
            int_agents = entities.get("intervention", [])[:2]
        cond_terms = entities.get("condition", [])
        if not int_agents or not cond_terms:
            return []

        query_str = f"{' '.join(int_agents[:3])} {' '.join(cond_terms[:2])}".strip()
        params = {
            "query": query_str,
            "fields": "title,year,authors,abstract,externalIds,url,venue,isOpenAccess,openAccessPdf",
            "limit": retmax
        }

        try:
            resp = resilient_request(self.s2_search_url, params=params, timeout=timeout)
            if resp.status_code != 200:
                return []

            data = resp.json()
            raw_papers = data.get("data", [])
            valid_candidates = []

            for p in raw_papers:
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

                pmcid = None
                if ext_ids.get("PubMedCentral"):
                    raw_pmc = str(ext_ids["PubMedCentral"]).strip()
                    pmcid = raw_pmc if raw_pmc.upper().startswith("PMC") else f"PMC{raw_pmc}"

                is_oa = bool(p.get("isOpenAccess") or p.get("openAccessPdf"))
                has_full_text = bool(pmcid or is_oa)
                pmc_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else None

                if pmid:
                    verified_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                elif doi:
                    verified_url = f"https://doi.org/{doi}"
                elif p.get("url"):
                    verified_url = p.get("url")
                else:
                    continue

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
                    "pmcid": pmcid,
                    "doi": doi,
                    "has_full_text": has_full_text,
                    "pmc_url": pmc_url,
                    "source": "Semantic Scholar Fallback",
                    "is_fallback": True
                })

            return valid_candidates
        except Exception as e:
            print(f"[Finder:S2] Semantic Scholar fallback search error: {str(e)}")
            return []

    def _candidate_prefilter(self, candidate: Dict[str, Any], entities: Dict[str, Any]) -> bool:
        """
        Deterministic zero-token pre-filter: rapidly reject candidates that do not mention
        required combination agents before invoking LLM verification.
        """
        text = f"{candidate.get('title', '')} {candidate.get('abstract', '')}".lower()
        if not text.strip():
            return False

        if entities.get("is_combination") and entities.get("intervention_agents"):
            for agent_obj in entities["intervention_agents"]:
                terms = [agent_obj.get("agent", "")] + agent_obj.get("synonyms", []) + agent_obj.get("parent_classes", [])
                clean_terms = [t.lower() for t in terms if t and t.lower() not in SEARCH_STOPWORDS and t.lower() not in AMBIGUOUS_ACRONYMS]
                if clean_terms:
                    if not any(t in text for t in clean_terms):
                        return False
            return True

        return True

    def _score_clinical_priority(self, candidate: Dict[str, Any], entities: Dict[str, Any], query_str: str = "") -> int:
        """
        Score clinical priority to elevate foundational RCTs and primary hard-endpoint trials.
        Dynamically exempts biomarker penalties if the biomarker is part of the query/entities.
        """
        title = (candidate.get("title") or "").lower()
        abstract = (candidate.get("abstract") or "").lower()
        score = 0
        cond_terms = entities.get("condition", [])
        endpoint_terms = entities.get("endpoints", [])

        # Hard clinical endpoint explicitly featured in title or abstract
        if any(c.lower() in title for c in cond_terms if len(c) > 3):
            score += 50
        elif any(c.lower() in abstract for c in cond_terms if len(c) > 3):
            score += 25

        if endpoint_terms and any(e.lower() in title for e in endpoint_terms if len(e) > 3):
            score += 25
        elif endpoint_terms and any(e.lower() in abstract for e in endpoint_terms if len(e) > 3):
            score += 15

        if any(w in title for w in ["mortality", "survival", "death", "deaths"]):
            score += 30
        if any(w in title for w in ["progression", "proliferat", "recurrence", "resistant", "resistance"]):
            score += 25
        if any(w in title for w in ["randomised", "randomized", "placebo-controlled", "trial", "clinical trial"]):
            score += 15
        if any(w in title for w in ["cohort", "nationwide", "population-based", "prospective", "registry"]):
            score += 15

        # Recency boost
        try:
            yr = int(candidate.get("year", 0))
            if yr >= 2022:
                score += 15
            elif yr >= 2018:
                score += 10
            elif yr >= 2012:
                score += 5
        except (ValueError, TypeError):
            pass

        # Biomarker penalty: ONLY apply if the user query/entities do NOT involve this biomarker
        query_and_entities_text = f"{query_str} {' '.join(entities.get('intervention', []))} {' '.join(entities.get('parent_classes', []))} {' '.join(cond_terms)} {' '.join(endpoint_terms)}".lower()
        for b in SURROGATE_BIOMARKER_TERMS:
            if b in query_and_entities_text:
                continue
            if b in title:
                score -= 40
                break

        return score

    def _prerank_and_select_candidates(
        self,
        candidates: List[Dict[str, Any]],
        entities: Dict[str, Any],
        user_query: str,
        total_limit: int = 20,
        class_quota_ratio: float = 0.35
    ) -> List[Dict[str, Any]]:
        """
        Pre-ranks candidates and reserves slots for class-only matches (e.g. 'thyroid hormone' / 'THRT')
        so they are not crowded out by specific drug matches before batch LLM verification.
        """
        if not candidates:
            return []

        specific_terms = set()
        for a in entities.get("intervention_agents", []):
            if a.get("agent"):
                specific_terms.add(a["agent"].lower())
            for s in a.get("synonyms", []):
                specific_terms.add(s.lower())
        for t in entities.get("intervention", []):
            specific_terms.add(t.lower())

        class_terms = set()
        for a in entities.get("intervention_agents", []):
            for p in a.get("parent_classes", []):
                class_terms.add(p.lower())
        for p in entities.get("parent_classes", []):
            class_terms.add(p.lower())

        clean_spec = {t for t in specific_terms if t not in SEARCH_STOPWORDS and t not in AMBIGUOUS_ACRONYMS}
        clean_class = {t for t in class_terms if t not in SEARCH_STOPWORDS and t not in AMBIGUOUS_ACRONYMS}

        specific_cands = []
        class_only_cands = []

        for c in candidates:
            abstract = c.get("abstract")
            if not abstract or len(abstract.strip()) < 40:
                continue
            if not self._candidate_prefilter(c, entities):
                continue

            c["priority_score"] = self._score_clinical_priority(c, entities, user_query)
            text = f"{c.get('title', '')} {abstract}".lower()

            has_spec = any(t in text for t in clean_spec) if clean_spec else False
            has_class = any(t in text for t in clean_class) if clean_class else False

            c["is_class_only"] = has_class and not has_spec
            if c["is_class_only"]:
                class_only_cands.append(c)
            else:
                specific_cands.append(c)

        specific_cands.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        class_only_cands.sort(key=lambda x: x.get("priority_score", 0), reverse=True)

        class_slots = int(total_limit * class_quota_ratio)
        selected_class = class_only_cands[:class_slots]
        remaining_slots = total_limit - len(selected_class)
        selected_spec = specific_cands[:remaining_slots]

        if len(selected_spec) < remaining_slots and len(class_only_cands) > class_slots:
            extra_class = class_only_cands[class_slots: class_slots + (remaining_slots - len(selected_spec))]
            selected_class.extend(extra_class)

        combined = selected_spec + selected_class
        combined.sort(key=lambda x: x.get("priority_score", 0), reverse=True)
        return combined[:total_limit]

    def verify_and_score_candidate(
        self,
        candidate: Dict[str, Any],
        entities: Dict[str, Any],
        user_query: str
    ) -> Optional[Dict[str, Any]]:
        """Enforces the Strict Binary Clinical Gate for a single candidate."""
        abstract = candidate.get("abstract")
        if not abstract or len(abstract.strip()) < 40:
            return None

        if not self._candidate_prefilter(candidate, entities):
            return None

        is_combo = bool(entities.get("is_combination", False))
        required_agents = [a.get("agent") for a in entities.get("intervention_agents", []) if a.get("agent")]
        if not required_agents and entities.get("intervention"):
            required_agents = entities.get("intervention", [])[:2]

        system_instruction = (
            "You are a precision clinical methodology verifier. Evaluate candidate studies against user criteria.\n"
            "MANDATORY CLINICAL DIRECTIVE:\n"
            "You MUST apply a strict BINARY CLINICAL GATE:\n"
            "Question 1: Does this study explicitly evaluate the Target Intervention(s) or validated Parent Class? (true/false)\n"
            "  * PARENT CLASS RULE: If the target intervention is a specific drug (e.g. levothyroxine) and the paper studies its broader validated therapeutic class (e.g. 'thyroid hormone replacement therapy', 'exogenous thyroid hormone', 'THRT'), Question 1 is TRUE.\n"
            "  * COMBINATION RULE: If the user query specifies a combination of multiple distinct agents (e.g. CoQ10 AND selenium), ALL required agents must be evaluated in combination. Monotherapy fails.\n"
            "Question 2: Does this study explicitly evaluate the Target Condition, clinical outcome, or overall malignancy cohort? (true/false)\n"
            "  * COHORT RULE: If the paper is a multi-site subsequent primary cancer or nationwide cohort analyzing overall cancer risk/progression, Question 2 is TRUE.\n"
            "If EITHER Question 1 OR Question 2 is false, match_score MUST BE 0.\n"
            "If BOTH are true: Base score 50% + secondary alignment (up to 100%).\n"
            "Respond strictly in JSON matching this schema:\n"
            "{\n"
            '  "matches_intervention": bool,\n'
            '  "matches_condition": bool,\n'
            '  "binary_gate_passed": bool,\n'
            '  "population_match": bool,\n'
            '  "geography_match": bool,\n'
            '  "study_design_match": bool,\n'
            '  "match_score": int,\n'
            '  "grounded_summary": "1-2 concise sentences summarizing findings based STRICTLY on the abstract"\n'
            "}"
        )

        user_prompt = (
            f"USER QUERY: \"{user_query}\"\n"
            f"TARGET ENTITIES:\n"
            f"- Is Combination: {is_combo}\n"
            f"- Required Intervention Agents: {json.dumps(required_agents)}\n"
            f"- Parent Classes: {json.dumps(entities.get('parent_classes', []))}\n"
            f"- Condition: {json.dumps(entities.get('condition', []))}\n"
            f"- Endpoints: {json.dumps(entities.get('endpoints', []))}\n\n"
            f"STUDY TITLE: {candidate.get('title')}\n"
            f"STUDY ABSTRACT:\n{abstract}"
        )

        try:
            thinking_level = self.determine_thinking_level(user_query, entities)
            raw_json, _ = self._invoke_gemini(user_prompt, system_instruction, json_mode=True, thinking_level=thinking_level, timeout=25)
            res = json.loads(raw_json)

            score = int(res.get("match_score", 0))
            gate_passed = bool(res.get("binary_gate_passed", False))

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
            print(f"[Finder:Verify] Single verify error: {e}")
            return None

    def _verify_sub_batch(
        self,
        sub_batch: List[Dict[str, Any]],
        entities: Dict[str, Any],
        user_query: str,
        timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """Verify a bounded sub-batch (up to 10 candidates) with strict JSON schema."""
        if not sub_batch:
            return []

        is_combo = bool(entities.get("is_combination", False))
        required_agents = [a.get("agent") for a in entities.get("intervention_agents", []) if a.get("agent")]
        if not required_agents and entities.get("intervention"):
            required_agents = entities.get("intervention", [])[:2]

        system_instruction = (
            "You are a precision clinical methodology verifier. Evaluate candidate studies against user criteria.\n"
            "MANDATORY CLINICAL DIRECTIVE:\n"
            "You MUST apply a strict BINARY CLINICAL GATE for EACH candidate study:\n"
            "- matches_intervention: Does this study explicitly evaluate the Target Intervention(s) or validated Parent Class? (true/false)\n"
            "  * PARENT CLASS RULE: If the target intervention is a specific drug (e.g. levothyroxine) and the paper studies its validated therapeutic umbrella class (e.g. 'thyroid hormone replacement therapy', 'exogenous thyroid hormone', 'THRT'), matches_intervention is TRUE.\n"
            "  * COMBINATION RULE: If the query specifies multiple distinct agents (e.g. CoQ10 AND selenium), ALL must be evaluated in combination. Monotherapy fails.\n"
            "- matches_condition: Does this study evaluate the Target Condition or clinical outcome? (true/false)\n"
            "  * COHORT RULE: If the paper is a multi-site subsequent primary cancer or nationwide cohort analyzing overall cancer risk/progression, matches_condition is TRUE.\n"
            "- binary_gate_passed: true ONLY if both matches_intervention AND matches_condition are true. Otherwise false.\n"
            "- match_score: 0 if binary_gate_passed is false; 50-100 if true.\n"
            "  * Assign highest scores (90-100) to foundational trials, survival endpoints, and direct clinical interactions.\n"
            "- grounded_summary: 1-2 concise sentences summarizing findings based strictly on the abstract.\n\n"
            "Respond strictly with a JSON array of evaluation objects matching this schema:\n"
            "[\n"
            "  {\n"
            '    "candidate_index": int,\n'
            '    "matches_intervention": bool,\n'
            '    "matches_condition": bool,\n'
            '    "binary_gate_passed": bool,\n'
            '    "population_match": bool,\n'
            '    "geography_match": bool,\n'
            '    "study_design_match": bool,\n'
            '    "match_score": int,\n'
            '    "grounded_summary": "1-2 concise sentences"\n'
            "  }\n"
            "]"
        )

        prompt_candidates = []
        for i, c in enumerate(sub_batch):
            prompt_candidates.append({
                "candidate_index": i,
                "title": c.get("title"),
                "year": c.get("year"),
                "abstract": c.get("abstract")
            })

        user_prompt = (
            f"USER QUERY: \"{user_query}\"\n"
            f"TARGET ENTITIES:\n"
            f"- Is Combination: {is_combo}\n"
            f"- Required Intervention Agents: {json.dumps(required_agents)}\n"
            f"- Parent Classes: {json.dumps(entities.get('parent_classes', []))}\n"
            f"- Condition: {json.dumps(entities.get('condition', []))}\n"
            f"- Endpoints: {json.dumps(entities.get('endpoints', []))}\n\n"
            f"CANDIDATES TO EVALUATE:\n"
            f"{json.dumps(prompt_candidates)}"
        )

        try:
            thinking_level = self.determine_thinking_level(user_query, entities)
            raw_json, _ = self._invoke_gemini(user_prompt, system_instruction, json_mode=True, thinking_level=thinking_level, timeout=timeout)
            evals = json.loads(raw_json)
            if not isinstance(evals, list):
                if isinstance(evals, dict) and "evaluations" in evals:
                    evals = evals["evaluations"]
                else:
                    evals = []

            eval_map = {e.get("candidate_index"): e for e in evals if isinstance(e, dict)}
            verified = []

            for i, cand in enumerate(sub_batch):
                ev = eval_map.get(i)
                if not ev:
                    continue
                score = int(ev.get("match_score", 0))
                gate_passed = bool(ev.get("binary_gate_passed", False))
                if gate_passed and score >= 50:
                    cand["match_score"] = score
                    cand["matches_intervention"] = bool(ev.get("matches_intervention", False))
                    cand["matches_condition"] = bool(ev.get("matches_condition", False))
                    cand["population_match"] = bool(ev.get("population_match", False))
                    cand["geography_match"] = bool(ev.get("geography_match", False))
                    cand["study_design_match"] = bool(ev.get("study_design_match", False))
                    cand["grounded_summary"] = (ev.get("grounded_summary") or "").strip()
                    verified.append(cand)
            return verified
        except Exception as e:
            print(f"[Finder:SubBatch] Sub-batch evaluation failed: {e}")
            return []

    def batch_verify_candidates(
        self,
        candidates: List[Dict[str, Any]],
        entities: Dict[str, Any],
        user_query: str,
        total_eval_limit: int = 20,
        sub_batch_size: int = 10,
        remaining_budget: float = 40.0
    ) -> List[Dict[str, Any]]:
        """
        Verify candidates using deterministic pre-ranking (with reserved class slots)
        and concurrent parallel sub-batches (2x10) to mitigate token truncation and latency.
        """
        if not candidates:
            return []

        eval_batch = self._prerank_and_select_candidates(
            candidates,
            entities,
            user_query,
            total_limit=total_eval_limit,
            class_quota_ratio=0.35
        )

        if not eval_batch:
            return []

        batches = [eval_batch[i:i + sub_batch_size] for i in range(0, len(eval_batch), sub_batch_size)]
        sub_timeout = min(30, max(12, int(remaining_budget * 0.7)))

        verified_papers = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, len(batches))) as executor:
            future_to_batch = {
                executor.submit(self._verify_sub_batch, b, entities, user_query, sub_timeout): b
                for b in batches
            }
            for fut in concurrent.futures.as_completed(future_to_batch):
                try:
                    res = fut.result()
                    verified_papers.extend(res)
                except Exception as e:
                    print(f"[Finder:ParallelBatch] Batch future error: {e}")

        # If parallel batch failed completely, fallback to bounded parallel single evaluation
        if not verified_papers and eval_batch and remaining_budget > 10.0:
            print("[Finder:BatchVerify] Batch verification returned empty; falling back to top candidates...")
            fallback_cands = eval_batch[:min(6, len(eval_batch))]
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = [executor.submit(self.verify_and_score_candidate, c, entities, user_query) for c in fallback_cands]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        res = f.result()
                        if res:
                            verified_papers.append(res)
                    except Exception as fe:
                        print(f"[Finder:SingleVerify] Fallback candidate error: {fe}")

        return verified_papers

    def find_papers(self, query: str, max_results: int = 10, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Execute the modernized relaxation ladder with parent-class expansion, strict time-budgeting (70s),
        PMID pool merging across tiers, deterministic pre-ranking, and degraded-state handling.
        """
        start_time = time.time()
        TOTAL_TIME_BUDGET = 70.0  # seconds
        CASCADE_VERIFIED_THRESHOLD = 5

        def remaining_budget() -> float:
            return max(3.0, TOTAL_TIME_BUDGET - (time.time() - start_time))

        query_clean = query.strip()
        if not query_clean:
            return {
                "status": "error",
                "message": "Query string is empty.",
                "qualifying_papers": [],
                "formatted_output": "Search Failed: Empty query."
            }

        # Step 0: Cache Check
        cached = self.cache.get(query_clean, force_refresh=force_refresh)
        if cached:
            cached_copy = dict(cached)
            all_qualifying = cached_copy.get("qualifying_papers", [])
            cached_copy["qualifying_papers"] = all_qualifying[:max_results]
            cached_copy["qualifying_count"] = len(cached_copy["qualifying_papers"])
            cached_copy["from_cache"] = True
            return cached_copy

        # Step 1: Entity Extraction with Bidirectional Expansion
        try:
            entities = self.extract_clinical_entities(query_clean)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Clinical entity extraction failed: {str(e)}",
                "qualifying_papers": [],
                "formatted_output": "Search Failed: Entity extraction error."
            }

        has_geo = bool(entities.get("geography"))
        has_pop = bool(entities.get("population"))
        has_parent_class = bool(entities.get("parent_classes"))
        has_endpoints = bool(entities.get("endpoints"))

        tier_used_label = "Tier 1 (Strict Specific + Europe PMC)"
        source_db = "PubMed"
        is_fallback = False
        is_degraded = False

        # Cumulative verified papers store enforcing canonical deduplication (DOI > PMID > PMCID > Title Hash)
        verified_store = CanonicalPaperStore()
        candidate_store = CanonicalPaperStore()

        # Step 2: Modernized Relaxation Ladder Execution
        # --- TIER 1 & 1b: Primary Candidate Retrieval (Specific + Europe PMC + Parent-Class Expansion) ---
        pubmed_pmids = []
        epmc_candidates = []

        if remaining_budget() > 20.0:
            t1_query = self.build_pubmed_query(entities, tier=1, field_tag="[tw]")
            # Concurrent execution of NCBI esearch and Europe PMC search
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                fut_pubmed = None
                if t1_query:
                    fut_pubmed = executor.submit(self.search_ncbi_esearch, t1_query, 60, min(12, int(remaining_budget())))
                fut_epmc = executor.submit(self.search_europe_pmc, entities, 30, min(12, int(remaining_budget())))

                if fut_pubmed:
                    try:
                        pubmed_pmids = fut_pubmed.result() or []
                    except Exception as pe:
                        print(f"[Finder:Tier1] PubMed esearch error: {pe}")
                try:
                    epmc_candidates = fut_epmc.result() or []
                except Exception as ee:
                    print(f"[Finder:Tier1] Europe PMC search error: {ee}")

        # Ingest Europe PMC candidates directly into candidate_store
        for c in epmc_candidates:
            candidate_store.add_or_merge(c)

        # Include Tier 1b (Semantic Expansion) into candidate pool whenever parent classes exist
        if has_parent_class and remaining_budget() > 20.0:
            tier_used_label = "Tier 1b (Specific + Parent Classes + Europe PMC)"
            t1b_query = self.build_pubmed_query(entities, tier="1b", field_tag="[tw]")
            if t1b_query:
                try:
                    pmids_1b = self.search_ncbi_esearch(t1b_query, retmax=100, timeout=min(15, int(remaining_budget())))
                    pubmed_pmids.extend([p for p in pmids_1b if p not in pubmed_pmids])
                except Exception as e1b:
                    print(f"[Finder:Tier1b] PubMed esearch error: {e1b}")

        # Ingest PubMed candidates
        if pubmed_pmids and remaining_budget() > 20.0:
            # Filter out PMIDs that are already fully present in candidate_store
            pmids_to_fetch = [
                pid for pid in pubmed_pmids
                if not candidate_store.contains({"pmid": pid})
            ]
            if pmids_to_fetch:
                try:
                    pubmed_meta = self.fetch_pubmed_metadata(pmids_to_fetch, timeout=min(22, int(remaining_budget())))
                    for c in pubmed_meta:
                        candidate_store.add_or_merge(c)
                except Exception as pfe:
                    print(f"[Finder:Tier1] PubMed metadata fetch error: {pfe}")

        # Batch verify all unique candidates across PubMed and Europe PMC
        all_tier1_candidates = candidate_store.get_all()
        if all_tier1_candidates and remaining_budget() > 18.0:
            verified = self.batch_verify_candidates(
                all_tier1_candidates,
                entities,
                query_clean,
                total_eval_limit=25,
                remaining_budget=remaining_budget()
            )
            for p in verified:
                p["tier_used"] = "1b" if p.get("is_class_only") else 1
                verified_store.add_or_merge(p)

        # --- TIER 2: Relax Geography ---
        if len(verified_store.get_all()) < CASCADE_VERIFIED_THRESHOLD and has_geo and remaining_budget() > 18.0:
            print("[Finder:Ladder] Cascading to Tier 2 (Relax Geography)...")
            tier_used_label = "Tier 2 (Relax Geography)"
            t2_query = self.build_pubmed_query(entities, tier=2, field_tag="[tw]")
            if t2_query:
                pmids_2 = self.search_ncbi_esearch(t2_query, retmax=60, timeout=min(12, int(remaining_budget())))
                new_pmids = [pid for pid in pmids_2 if not candidate_store.contains({"pmid": pid})]
                if new_pmids:
                    candidates_2 = self.fetch_pubmed_metadata(new_pmids, timeout=min(18, int(remaining_budget())))
                    for c in candidates_2:
                        candidate_store.add_or_merge(c)
                    verified_2 = self.batch_verify_candidates(candidates_2, entities, query_clean, total_eval_limit=15, remaining_budget=remaining_budget())
                    for p in verified_2:
                        p["tier_used"] = 2
                        verified_store.add_or_merge(p)

        # --- TIER 3: Relax Population / Endpoints (Core Clinical Only) ---
        if len(verified_store.get_all()) < CASCADE_VERIFIED_THRESHOLD and (has_pop or has_endpoints) and remaining_budget() > 16.0:
            print("[Finder:Ladder] Cascading to Tier 3 (Core Clinical Only)...")
            tier_used_label = "Tier 3 (Core Clinical Only)"
            t3_query = self.build_pubmed_query(entities, tier=3, field_tag="[tw]")
            if t3_query:
                pmids_3 = self.search_ncbi_esearch(t3_query, retmax=60, timeout=min(12, int(remaining_budget())))
                new_pmids = [pid for pid in pmids_3 if not candidate_store.contains({"pmid": pid})]
                if new_pmids:
                    candidates_3 = self.fetch_pubmed_metadata(new_pmids, timeout=min(18, int(remaining_budget())))
                    for c in candidates_3:
                        candidate_store.add_or_merge(c)
                    verified_3 = self.batch_verify_candidates(candidates_3, entities, query_clean, total_eval_limit=15, remaining_budget=remaining_budget())
                    for p in verified_3:
                        p["tier_used"] = 3
                        verified_store.add_or_merge(p)

        # --- TIER 4: Semantic Scholar Fallback (Only if PubMed and Europe PMC yielded 0 verified papers) ---
        if len(verified_store.get_all()) == 0 and remaining_budget() > 14.0:
            print("[Finder:Ladder] PubMed and Europe PMC yielded 0 verified results. Cascading to Tier 4 (Semantic Scholar Fallback)...")
            tier_used_label = "Tier 4 (Semantic Scholar Fallback)"
            source_db = "Semantic Scholar Fallback"
            is_fallback = True
            raw_s2 = self.search_semantic_scholar_fallback(entities, retmax=20, timeout=min(12, int(remaining_budget())))
            if raw_s2:
                verified_s2 = self.batch_verify_candidates(raw_s2, entities, query_clean, total_eval_limit=15, remaining_budget=remaining_budget())
                for p in verified_s2:
                    p["tier_used"] = 4
                    p["is_fallback"] = True
                    verified_store.add_or_merge(p)

        # Check if time budget triggered degraded state
        all_verified = verified_store.get_all()
        if remaining_budget() <= 5.0 and len(all_verified) < CASCADE_VERIFIED_THRESHOLD:
            is_degraded = True

        # Determine source database label based on surviving verified papers
        if not is_fallback:
            sources = {p.get("source", "") for p in all_verified}
            if any("Europe PMC" in s for s in sources) and any("PubMed" in s for s in sources):
                source_db = "PubMed / Europe PMC"
            elif any("Europe PMC" in s for s in sources):
                source_db = "Europe PMC"
            else:
                source_db = "PubMed"

        if not all_verified:
            return {
                "status": "not_found",
                "message": "Search Failed: No literature candidates matching clinical criteria located across PubMed, Europe PMC, and Semantic Scholar.",
                "query": query_clean,
                "entities": entities,
                "tier_used": tier_used_label,
                "source_database": source_db,
                "is_fallback": is_fallback,
                "is_degraded": is_degraded,
                "qualifying_papers": [],
                "formatted_output": "Search Failed"
            }

        # Sort combined candidate pool by Match Score & Clinical Priority
        all_verified.sort(
            key=lambda x: (
                x.get("match_score", 0),
                x.get("priority_score", 0)
            ),
            reverse=True
        )
        final_papers = all_verified[:max_results]

        # Construct Strict Formatted Output
        formatted_blocks = []
        for p in final_papers:
            source_url = p.get("pmc_url") if (p.get("has_full_text") and p.get("pmc_url")) else p.get("url")
            block = (
                f"Title: {p.get('title')} Year: {p.get('year')}\n"
                f"Summary: {p.get('grounded_summary')}\n"
                f"Source: {source_url}"
            )
            formatted_blocks.append(block)

        strict_formatted_output = "\n\n".join(formatted_blocks)
        thinking_level = self.determine_thinking_level(query_clean, entities)

        result = {
            "status": "success",
            "query": query_clean,
            "entities": entities,
            "tier_used": tier_used_label,
            "source_database": source_db,
            "is_fallback": is_fallback,
            "is_degraded": is_degraded,
            "total_evaluated": len(candidate_store.get_all()),
            "qualifying_count": len(final_papers),
            "qualifying_papers": final_papers,
            "formatted_output": strict_formatted_output,
            "model_designation": MODEL_DESIGNATION,
            "model_endpoint": PRIMARY_MODEL,
            "thinking_level": thinking_level,
            "from_cache": False
        }

        # Store in SQLite Query Cache if not degraded and not partial
        if not is_degraded:
            self.cache.set(query_clean, result)

        return result
