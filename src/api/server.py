from __future__ import annotations
import os
import sys
import shutil
import io
import time
import json
import urllib.parse
import re
from typing import Optional, Dict, List, Any
from pydantic import BaseModel

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import pymupdf
from PIL import Image

from src.ingestion.indexer import parse_and_index_pdf, IndexedDocument
from src.ingestion.fetcher import PaperFetcher
from src.appraisal.generator import SynthesisEngine, PRIMARY_MODEL, PRO_REASONING_MODEL
from src.appraisal.qa import PaperQAEngine
from src.appraisal.commentary import CommentaryAndQCEngine
from src.finder.searcher import PaperFinder, MODEL_DESIGNATION as FINDER_MODEL_DESIGNATION
from src.summarizer.engine import PaperSummarizer, MODEL_DESIGNATION as SUMMARIZER_MODEL_DESIGNATION
from src.telemetry.tracker import log_usage, get_aggregated_usage, get_recent_usage_logs

app = FastAPI(
    title="F.A.C.T. - Find · Analyze · Contextualize · Talk",
    description="Deterministic Clinical Research Analyzer with Inline Coordinate Grounding",
    version="1.0.0"
)

# Enable CORS for local frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.getenv("RESEARCH_EVAL_DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
PUBLIC_DIR = os.path.join(PROJECT_ROOT, "Public") if os.path.exists(os.path.join(PROJECT_ROOT, "Public")) else os.path.join(PROJECT_ROOT, "public")
ICONS_DIR = os.path.join(PUBLIC_DIR, "icons") if os.path.exists(os.path.join(PUBLIC_DIR, "icons")) else os.path.join(STATIC_DIR, "icons")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if os.path.exists(PUBLIC_DIR):
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")

if os.path.exists(ICONS_DIR):
    app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")

@app.get("/manifest.json")
def get_manifest():
    for m in [os.path.join(PUBLIC_DIR, "manifest.json"), os.path.join(STATIC_DIR, "manifest.json")]:
        if os.path.exists(m):
            return FileResponse(
                m,
                media_type="application/manifest+json",
                headers={"Cache-Control": "no-cache, must-revalidate"}
            )
    raise HTTPException(status_code=404, detail="Manifest not found")

@app.get("/FACT-Elf.jpeg")
@app.get("/FAST-Elf.jpeg")
@app.get("/elf-thinker.png")
@app.get("/fast-elf.png")
def get_fast_elf_image():
    for candidate in [
        os.path.join(PUBLIC_DIR, "FACT-Elf.jpeg"),
        os.path.join(PUBLIC_DIR, "FAST-Elf.jpeg"),
        os.path.join(STATIC_DIR, "FACT-Elf.jpeg"),
        os.path.join(STATIC_DIR, "elf-thinker.png"),
        os.path.join(STATIC_DIR, "fast-elf.png")
    ]:
        if os.path.exists(candidate):
            mtype = "image/png" if candidate.endswith(".png") else "image/jpeg"
            return FileResponse(candidate, media_type=mtype)
    raise HTTPException(status_code=404, detail="Elf thinker logo not found")

@app.get("/FACT Elf Thinker PWA Logo.png")
@app.get("/FACT Elf Thinker PWA Logo.jpeg")
@app.get("/FACT-Elf-Thinker-PWA-Logo.png")
@app.get("/FACT-Elf-Thinker-PWA-Logo.jpeg")
def get_pwa_logo_image():
    for candidate in [
        os.path.join(PUBLIC_DIR, "FACT Elf Thinker PWA Logo.png"),
        os.path.join(PUBLIC_DIR, "FACT Elf Thinker PWA Logo.jpeg"),
        os.path.join(PUBLIC_DIR, "icons", "icon-512.png")
    ]:
        if os.path.exists(candidate):
            mtype = "image/png" if candidate.endswith(".png") else "image/jpeg"
            return FileResponse(candidate, media_type=mtype)
    raise HTTPException(status_code=404, detail="PWA logo not found")

@app.get("/logo.png")
def get_logo():
    for candidate in [
        os.path.join(PUBLIC_DIR, "icons", "icon-512.png"),
        os.path.join(PUBLIC_DIR, "FACT Elf Thinker PWA Logo.png"),
        os.path.join(STATIC_DIR, "elf-thinker.png"),
        os.path.join(STATIC_DIR, "fast-elf.png"),
        os.path.join(PUBLIC_DIR, "FACT-Elf.jpeg"),
        os.path.join(PUBLIC_DIR, "FAST-Elf.jpeg")
    ]:
        if os.path.exists(candidate):
            mtype = "image/png" if candidate.endswith(".png") else "image/jpeg"
            return FileResponse(candidate, media_type=mtype)
    raise HTTPException(status_code=404, detail="Logo not found")

@app.get("/favicon.ico")
def get_favicon():
    for f in [os.path.join(PUBLIC_DIR, "favicon.ico"), os.path.join(STATIC_DIR, "favicon.ico")]:
        if os.path.exists(f):
            return FileResponse(f, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")
    raise HTTPException(status_code=404, detail="Favicon not found")

def prune_ephemeral_uploads(max_age_hours: int = 24):
    """Purge temporary PDF and abstract files older than max_age_hours to prevent copyright retention."""
    if not os.path.exists(UPLOAD_DIR):
        return
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    purged = 0
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith("."):
            continue
        fpath = os.path.join(UPLOAD_DIR, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                purged += 1
        except Exception as e:
            print(f"[StorageCleaner] Warning removing {fname}: {e}")
    if purged > 0:
        print(f"[StorageCleaner] Ephemeral pruning complete: {purged} file(s) removed.")

# Run initial pruning on server module initialization
prune_ephemeral_uploads(24)

engine = SynthesisEngine(DATA_DIR)
fetcher = PaperFetcher(UPLOAD_DIR)

# In-memory session cache of the most recently indexed document
CACHED_INDEX: Dict[str, IndexedDocument] = {}

finder = PaperFinder()
summarizer = PaperSummarizer()
qa_engine = PaperQAEngine()
commentary_engine = CommentaryAndQCEngine()


class FinderSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10
    force_refresh: Optional[bool] = False
    user_uid: Optional[str] = "anonymous"
    user_email: Optional[str] = "unauthenticated"


class SummarizerGenerateRequest(BaseModel):
    urls: List[str]
    max_batch_size: Optional[int] = 10
    user_uid: Optional[str] = "anonymous"
    user_email: Optional[str] = "unauthenticated"


@app.post("/api/finder/search")
def api_finder_search(req: FinderSearchRequest):
    """Execute Zero-Trust 4-tier relaxation search and binary clinical gate verification with SQLite query caching."""
    try:
        res = finder.find_papers(
            query=req.query,
            max_results=req.max_results or 10,
            force_refresh=bool(req.force_refresh)
        )
        try:
            log_usage(
                uid=req.user_uid or "anonymous",
                email=req.user_email or "unauthenticated",
                feature="finder",
                model=FINDER_MODEL_DESIGNATION,
                prompt_tokens=420,
                candidates_tokens=380
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/summarizer/generate")
def api_summarizer_generate(req: SummarizerGenerateRequest):
    """Execute sequential structured multi-paper lay science communicator briefing."""
    try:
        res = summarizer.summarize_batch(raw_inputs=req.urls, max_batch_size=req.max_batch_size or 10)
        try:
            log_usage(
                uid=req.user_uid or "anonymous",
                email=req.user_email or "unauthenticated",
                feature="contextualizer",
                model=SUMMARIZER_MODEL_DESIGNATION,
                prompt_tokens=1800 * max(1, len(req.urls)),
                candidates_tokens=1200 * max(1, len(req.urls))
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class TelemetryLogRequest(BaseModel):
    user_uid: Optional[str] = "anonymous"
    user_email: Optional[str] = "unauthenticated"
    feature: str
    model: str
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    latency_ms: Optional[int] = None

@app.get("/api/admin/usage")
def api_admin_usage():
    """Retrieve aggregated usage telemetry per user for the Admin User Management panel."""
    try:
        usage = get_aggregated_usage()
        return {"success": True, "usage": usage}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/telemetry/log")
def api_telemetry_log(req: TelemetryLogRequest):
    """Log LLM token usage and estimated cost."""
    try:
        cost = log_usage(
            uid=req.user_uid or "anonymous",
            email=req.user_email or "unauthenticated",
            feature=req.feature,
            model=req.model,
            prompt_tokens=req.prompt_tokens,
            candidates_tokens=req.candidates_tokens,
            latency_ms=req.latency_ms
        )
        return {"success": True, "estimated_cost_usd": cost}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/firebase-applet-config.json")
def get_firebase_config():
    cfg_file = os.path.join(PROJECT_ROOT, "firebase-applet-config.json")
    if os.path.exists(cfg_file):
        return FileResponse(cfg_file, media_type="application/json")
    raise HTTPException(status_code=404, detail="firebase-applet-config.json not found")

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "data_dir": DATA_DIR,
        "primary_model": PRIMARY_MODEL,
        "pro_model": PRO_REASONING_MODEL,
        "has_api_key": bool(engine.api_key)
    }

@app.get("/knowledge-bases")
def get_knowledge_bases():
    return {
        "frameworks_count": len(engine.schemadb),
        "rules_count": len(engine.rulesdb),
        "lexicon_terms_count": len(engine.lexicondb),
        "triage_definitions": engine.triage_engine.triage_matrix
    }

@app.post("/check-url")
def check_paper_url(url: str = Form(...)):
    """Check PubMed/PMC/DOI availability and report whether free full text or abstract only is present."""
    return fetcher.check_url_availability(url)

@app.post("/resolve-url")
def resolve_paper_url(url: str = Form(...)):
    """Fetch URL/PMC/PMID/DOI and determine whether full text or abstract is available."""
    res = fetcher.resolve_url(url)
    return res

@app.post("/analyze-fetched")
@app.post("/appraise-fetched")
def analyze_fetched_paper(
    filename: str = Form(...),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    user_uid: Optional[str] = Form("anonymous"),
    user_email: Optional[str] = Form("unauthenticated")
):
    """Run full appraisal pipeline on an already-resolved paper or abstract."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Resolved file not found on server.")
        
    try:
        indexed = parse_and_index_pdf(file_path)
        CACHED_INDEX[filename] = indexed
        
        eval_engine = SynthesisEngine(DATA_DIR, api_key=api_key) if api_key else engine
        result = eval_engine.generate_appraisal(indexed, model_override=model_override)
        
        anchor_data = {}
        for aid, meta in indexed.anchor_metadata.items():
            anchor_data[aid] = {
                "anchor_id": aid,
                "page": meta.page_number,
                "page_width": meta.page_width,
                "page_height": meta.page_height,
                "section": meta.section,
                "text": meta.text[:250],
                "bbox": meta.bbox,
                "has_overflow": bool(meta.overflow_page)
            }
            
        result["filename"] = filename
        result["total_anchors_indexed"] = len(indexed.all_anchors)
        result["sections_detected"] = list(indexed.sections.keys())
        result["document_header"] = indexed.doc_header
        result["anchor_index"] = anchor_data
        try:
            _d = pymupdf.open(file_path)
            result["total_pages"] = len(_d)
            _d.close()
        except Exception:
            result["total_pages"] = max((m["page"] for m in anchor_data.values()), default=1)
        
        try:
            log_usage(
                uid=user_uid or "anonymous",
                email=user_email or "unauthenticated",
                feature="appraisal",
                model=model_override or PRIMARY_MODEL,
                prompt_tokens=4500,
                candidates_tokens=3200
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ask-paper")
async def ask_paper(
    filename: str = Form(...),
    question: str = Form(...),
    history: Optional[str] = Form(None),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    user_uid: Optional[str] = Form("anonymous"),
    user_email: Optional[str] = Form("unauthenticated")
):
    """Answers clinical questions about a loaded manuscript with coordinate grounding."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested manuscript file not found on server.")
        
    try:
        # Retrieve or index document
        indexed = CACHED_INDEX.get(filename)
        if not indexed:
            indexed = parse_and_index_pdf(file_path)
            CACHED_INDEX[filename] = indexed
            
        conv_history = []
        if history:
            try:
                conv_history = json.loads(history)
            except Exception:
                conv_history = []
                
        engine_instance = PaperQAEngine(api_key=api_key) if api_key else qa_engine
        result = engine_instance.ask(
            indexed_doc=indexed,
            question=question,
            filename=filename,
            conversation_history=conv_history,
            model_override=model_override
        )
        
        try:
            log_usage(
                uid=user_uid or "anonymous",
                email=user_email or "unauthenticated",
                feature="ask_paper",
                model=model_override or PRIMARY_MODEL,
                prompt_tokens=2200,
                candidates_tokens=900
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-commentary")
async def generate_commentary_endpoint(
    filename: str = Form(...),
    appraisal_markdown: str = Form(...),
    voice_profile: Optional[str] = Form(None),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    user_uid: Optional[str] = Form("anonymous"),
    user_email: Optional[str] = Form("unauthenticated")
):
    """Generates clinician commentary grounded in the study appraisal and personalized by voice profile."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested manuscript file not found on server.")

    try:
        indexed = CACHED_INDEX.get(filename)
        if not indexed:
            indexed = parse_and_index_pdf(file_path)
            CACHED_INDEX[filename] = indexed

        profile_data = {}
        if voice_profile:
            try:
                profile_data = json.loads(voice_profile)
            except Exception:
                profile_data = {}

        engine_inst = CommentaryAndQCEngine(api_key=api_key) if api_key else commentary_engine
        result = engine_inst.generate_commentary(
            indexed_doc=indexed,
            appraisal_markdown=appraisal_markdown,
            voice_profile=profile_data,
            model_override=model_override
        )

        try:
            log_usage(
                uid=user_uid or "anonymous",
                email=user_email or "unauthenticated",
                feature="generate_commentary",
                model=model_override or PRIMARY_MODEL,
                prompt_tokens=2500,
                candidates_tokens=1200
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/audit-commentary")
async def audit_commentary_endpoint(
    filename: str = Form(...),
    appraisal_markdown: str = Form(...),
    commentary_text: str = Form(...),
    triage: Optional[str] = Form(None),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    user_uid: Optional[str] = Form("anonymous"),
    user_email: Optional[str] = Form("unauthenticated")
):
    """Independent adversarial QC audit of appraisal and commentary against manuscript coordinates."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Requested manuscript file not found on server.")

    try:
        indexed = CACHED_INDEX.get(filename)
        if not indexed:
            indexed = parse_and_index_pdf(file_path)
            CACHED_INDEX[filename] = indexed

        triage_data = {}
        if triage:
            try:
                triage_data = json.loads(triage)
            except Exception:
                triage_data = {}

        engine_inst = CommentaryAndQCEngine(api_key=api_key) if api_key else commentary_engine
        result = engine_inst.audit_appraisal_and_commentary(
            indexed_doc=indexed,
            appraisal_markdown=appraisal_markdown,
            commentary_text=commentary_text,
            triage_data=triage_data,
            model_override=model_override
        )

        try:
            log_usage(
                uid=user_uid or "anonymous",
                email=user_email or "unauthenticated",
                feature="audit_commentary",
                model=model_override or PRIMARY_MODEL,
                prompt_tokens=4500,
                candidates_tokens=1500
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze")
@app.post("/appraise")
async def analyze_paper(
    file: UploadFile = File(...),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    user_uid: Optional[str] = Form("anonymous"),
    user_email: Optional[str] = Form("unauthenticated")
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are currently supported.")
    
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        indexed = parse_and_index_pdf(file_path)
        
        # Cache for interactive anchor viewing
        CACHED_INDEX[file.filename] = indexed
        
        eval_engine = SynthesisEngine(DATA_DIR, api_key=api_key) if api_key else engine
        result = eval_engine.generate_appraisal(indexed, model_override=model_override)
        
        # Attach indexed anchor metadata for UI
        anchor_data = {}
        for aid, meta in indexed.anchor_metadata.items():
            anchor_data[aid] = {
                "anchor_id": aid,
                "page": meta.page_number,
                "page_width": meta.page_width,
                "page_height": meta.page_height,
                "section": meta.section,
                "text": meta.text[:250],
                "bbox": meta.bbox,
                "has_overflow": bool(meta.overflow_page)
            }
            
        result["filename"] = file.filename
        result["total_anchors_indexed"] = len(indexed.all_anchors)
        result["sections_detected"] = list(indexed.sections.keys())
        result["document_header"] = indexed.doc_header
        result["anchor_index"] = anchor_data
        try:
            _d = pymupdf.open(file_path)
            result["total_pages"] = len(_d)
            _d.close()
        except Exception:
            result["total_pages"] = max((m["page"] for m in anchor_data.values()), default=1)
        
        try:
            log_usage(
                uid=user_uid or "anonymous",
                email=user_email or "unauthenticated",
                feature="appraisal",
                model=model_override or PRIMARY_MODEL,
                prompt_tokens=4500,
                candidates_tokens=3200
            )
        except Exception as te:
            print(f"[Telemetry] Logging warning: {te}")
            
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def resolve_anchor(indexed: IndexedDocument, anchor_str: str) -> Optional[Any]:
    """
    Resolve an anchor identifier to a CoordinateAnchor object.
    Supports exact match, multi-paragraph citations (e.g. '[Results, Para 2, 8]'),
    paragraph ranges (e.g. '[Abstract, Para 1-3]'), compound citations (e.g. '[Methods, Para 5, Results, Para 2]'),
    and fuzzy section matching.
    """
    if not indexed or not anchor_str:
        return None

    anchor_clean = urllib.parse.unquote(anchor_str).strip()

    # 1. Exact match
    if anchor_clean in indexed.anchor_metadata:
        return indexed.anchor_metadata[anchor_clean]

    # Also test with/without enclosing brackets
    if not anchor_clean.startswith("[") and f"[{anchor_clean}]" in indexed.anchor_metadata:
        return indexed.anchor_metadata[f"[{anchor_clean}]"]

    # 2. Extract first section and first paragraph reference
    para_match = re.search(r'\[?\s*([A-Za-z\s&]+?)\s*,\s*Para\s+(\d+)', anchor_clean, re.IGNORECASE)
    if para_match:
        section = para_match.group(1).strip()
        p_num = int(para_match.group(2))

        canonical = f"[{section}, Para {p_num}]"
        if canonical in indexed.anchor_metadata:
            return indexed.anchor_metadata[canonical]

        for k, meta in indexed.anchor_metadata.items():
            if meta.item_type == 'para' and meta.index == p_num:
                if section.lower() in meta.section.lower() or meta.section.lower() in section.lower():
                    return meta

        for k, meta in indexed.anchor_metadata.items():
            if meta.item_type == 'para' and meta.index == p_num:
                return meta

    # 3. Table, Figure, or Box matching: '[Results, Table 1]', '[Results, TableNote 2]', '[Discussion, Fig 2]', '[Methods, Box 1]'
    tbl_fig_match = re.search(r'\[?\s*([A-Za-z\s&]+?)\s*,\s*(Table(?:Note)?|Fig(?:Legend)?|Box)\s*(\d+)', anchor_clean, re.IGNORECASE)
    if tbl_fig_match:
        section = tbl_fig_match.group(1).strip()
        raw_type = tbl_fig_match.group(2)
        item_type = raw_type[0].upper() + raw_type[1:]
        num = int(tbl_fig_match.group(3))

        canonical = f"[{section}, {item_type} {num}]"
        if canonical in indexed.anchor_metadata:
            return indexed.anchor_metadata[canonical]

        for k, meta in indexed.anchor_metadata.items():
            if (meta.item_type or "").lower() == item_type.lower() and meta.index == num:
                return meta

    # 4. Structured abstract subsection matching (e.g. '[Abstract, Results]', '[Abs, Results]')
    abs_sub_match = re.search(r'\[?\s*(?:Abstract|Abs)\s*,\s*(Objective|Aims?|Methods?|Results?|Conclusions?)\b', anchor_clean, re.IGNORECASE)
    if abs_sub_match:
        sub_word = abs_sub_match.group(1).lower()
        for k, meta in indexed.anchor_metadata.items():
            if (meta.section or "").lower() == "abstract":
                if sub_word in k.lower() or (meta.text and sub_word in meta.text[:80].lower()):
                    return meta

    # 5. Fallback: match any single paragraph number in the anchor string
    any_num = re.search(r'\bPara\s*(\d+)\b', anchor_clean, re.IGNORECASE)
    if any_num:
        p_num = int(any_num.group(1))
        for k, meta in indexed.anchor_metadata.items():
            if meta.item_type == 'para' and meta.index == p_num:
                return meta

    return None

@app.get("/view-anchor-image")
def view_anchor_image(
    filename: str = Query(...),
    anchor: str = Query(...)
):
    """Render a continuous image showing the anchor page plus the subsequent page if there is an overflow."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Source PDF file not found.")
        
    indexed = CACHED_INDEX.get(filename)
    if not indexed:
        indexed = parse_and_index_pdf(file_path)
        CACHED_INDEX[filename] = indexed
        
    anchor_clean = urllib.parse.unquote(anchor).strip()
    meta = resolve_anchor(indexed, anchor_clean)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Anchor {anchor_clean} not found.")
        
    doc = pymupdf.open(file_path)
    page_idx = max(0, min(len(doc) - 1, meta.page_number - 1))
    page = doc[page_idx]
    
    # Highlight on current page
    if meta.bbox and len(meta.bbox) == 4:
        rect = pymupdf.Rect(meta.bbox[0], meta.bbox[1], meta.bbox[2], meta.bbox[3])
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(1.0, 0.85, 0.0))  # Vivid golden amber highlight
        annot.update()
        
    pix1 = page.get_pixmap(dpi=150)
    img1 = Image.open(io.BytesIO(pix1.tobytes("png")))
    
    # Check if this paragraph overflows to next page OR if user should see the adjacent page for context
    overflow_p = meta.overflow_page
    next_page_idx = page_idx + 1 if (overflow_p or page_idx + 1 < len(doc)) else None
    
    if next_page_idx is not None and next_page_idx < len(doc):
        page_next = doc[next_page_idx]
        if meta.overflow_bbox and len(meta.overflow_bbox) == 4:
            rect2 = pymupdf.Rect(meta.overflow_bbox[0], meta.overflow_bbox[1], meta.overflow_bbox[2], meta.overflow_bbox[3])
            annot2 = page_next.add_highlight_annot(rect2)
            annot2.set_colors(stroke=(1.0, 0.85, 0.0))
            annot2.update()
            
        pix2 = page_next.get_pixmap(dpi=150)
        img2 = Image.open(io.BytesIO(pix2.tobytes("png")))
        
        # Stitch pages vertically with a clean divider
        divider_h = 16
        stitched_w = max(img1.width, img2.width)
        stitched_h = img1.height + img2.height + divider_h
        stitched = Image.new("RGB", (stitched_w, stitched_h), (226, 232, 240)) # slate-200 divider
        stitched.paste(img1, (0, 0))
        stitched.paste(img2, (0, img1.height + divider_h))
        
        buf = io.BytesIO()
        stitched.save(buf, format="PNG")
        doc.close()
        return Response(content=buf.getvalue(), media_type="image/png")
    else:
        buf = io.BytesIO()
        img1.save(buf, format="PNG")
        doc.close()
        return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/view-pdf-page")
def view_pdf_page(filename: str = Query(...), page: int = Query(1, ge=1)):
    """Render an individual page of a PDF as PNG at 150 DPI for continuous document scrolling."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Source PDF file not found.")
    doc = pymupdf.open(file_path)
    if page < 1 or page > len(doc):
        doc.close()
        raise HTTPException(status_code=400, detail=f"Page {page} out of bounds (1..{len(doc)})")
    pix = doc[page - 1].get_pixmap(dpi=150)
    buf = io.BytesIO(pix.tobytes("png"))
    doc.close()
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/pdf-manifest")
def get_pdf_manifest(filename: str = Query(...)):
    """Return total page count and page dimensions for continuous document scrolling."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Source PDF file not found.")
    doc = pymupdf.open(file_path)
    pages = []
    for i, p in enumerate(doc):
        pages.append({
            "page": i + 1,
            "width": float(p.rect.width),
            "height": float(p.rect.height)
        })
    total = len(doc)
    doc.close()
    return {"filename": filename, "total_pages": total, "pages": pages}


@app.post("/api/init-pdf-viewer")
async def init_pdf_viewer(file: UploadFile = File(...)):
    """Save uploaded PDF and immediately return page manifest so the user can scroll through the entire paper while analysis executes."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    doc = pymupdf.open(file_path)
    pages = [{"page": i + 1, "width": float(p.rect.width), "height": float(p.rect.height)} for i, p in enumerate(doc)]
    total = len(doc)
    doc.close()
    return {"filename": file.filename, "total_pages": total, "pages": pages}


@app.get("/view-anchor-crop")
def view_anchor_crop(
    filename: str = Query(...),
    anchor: str = Query(...)
):
    """Render the full paragraph crop, stitching both pages if the sentence overflows."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Source PDF file not found.")
        
    indexed = CACHED_INDEX.get(filename)
    if not indexed:
        indexed = parse_and_index_pdf(file_path)
        CACHED_INDEX[filename] = indexed
        
    anchor_clean = urllib.parse.unquote(anchor).strip()
    meta = resolve_anchor(indexed, anchor_clean)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Anchor {anchor_clean} not found.")
        
    doc = pymupdf.open(file_path)
    page_idx = max(0, min(len(doc) - 1, meta.page_number - 1))
    page = doc[page_idx]
    
    crops = []
    
    if meta.bbox and len(meta.bbox) == 4:
        rect = pymupdf.Rect(meta.bbox[0], meta.bbox[1], meta.bbox[2], meta.bbox[3])
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(1.0, 0.9, 0.2))
        annot.update()
        
        # Enforce sensible minimum height (at least 75 pt) and horizontal width for readable crops
        raw_h = rect.height
        raw_w = rect.width
        v_pad = max(18.0, (75.0 - raw_h) / 2.0 if raw_h < 75.0 else 18.0)
        h_pad = 20.0
        
        crop_rect = pymupdf.Rect(
            max(0, rect.x0 - h_pad),
            max(0, rect.y0 - v_pad),
            min(page.rect.width, rect.x1 + h_pad),
            min(page.rect.height, rect.y1 + v_pad)
        )
        pix1 = page.get_pixmap(clip=crop_rect, dpi=250)
        crops.append(Image.open(io.BytesIO(pix1.tobytes("png"))))
        
    # If it overflowed onto next page, crop the continuation block too!
    if meta.overflow_page and meta.overflow_bbox and len(meta.overflow_bbox) == 4:
        p_next_idx = meta.overflow_page - 1
        if p_next_idx < len(doc):
            p_next = doc[p_next_idx]
            rect2 = pymupdf.Rect(meta.overflow_bbox[0], meta.overflow_bbox[1], meta.overflow_bbox[2], meta.overflow_bbox[3])
            annot2 = p_next.add_highlight_annot(rect2)
            annot2.set_colors(stroke=(1.0, 0.9, 0.2))
            annot2.update()
            crop_rect2 = pymupdf.Rect(
                max(0, rect2.x0 - 16),
                max(0, rect2.y0 - 10),
                min(p_next.rect.width, rect2.x1 + 16),
                min(p_next.rect.height, rect2.y1 + 10)
            )
            pix2 = p_next.get_pixmap(clip=crop_rect2, dpi=300)
            crops.append(Image.open(io.BytesIO(pix2.tobytes("png"))))
            
    doc.close()
    
    if not crops:
        pix = page.get_pixmap(dpi=200)
        return Response(content=pix.tobytes("png"), media_type="image/png")
        
    if len(crops) == 1:
        buf = io.BytesIO()
        crops[0].save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")
    else:
        # Stitch both parts together vertically with an indicator line
        w = max(c.width for c in crops)
        h = sum(c.height for c in crops) + 24
        stitched = Image.new("RGB", (w, h), (255, 255, 255))
        y_offset = 0
        for i, c in enumerate(crops):
            stitched.paste(c, (0, y_offset))
            y_offset += c.height + 24
            
        buf = io.BytesIO()
        stitched.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

@app.get("/view-pdf")
def view_pdf(filename: str = Query(...)):
    """Guarded endpoint: raw binary PDF downloads are disabled for publisher copyright isolation."""
    raise HTTPException(
        status_code=403,
        detail="Direct raw PDF binary download is disabled for publisher copyright and sandbox protection. Use /view-pdf-page for rendered page views."
    )

@app.get("/", response_class=HTMLResponse)
def index_page():
    return r"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>F.A.C.T. — Find · Analyze · Contextualize · Talk</title>
        
        <!-- PWA Meta Tags & Web Manifest -->
        <link rel="manifest" href="/manifest.json?v=3">
        <meta name="theme-color" id="pwaThemeColor" content="#d97706">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="default">
        <meta name="apple-mobile-web-app-title" content="F.A.C.T.">
        
        <!-- Icons -->
        <link rel="icon" type="image/x-icon" href="/favicon.ico?v=2">
        <link rel="icon" type="image/png" sizes="16x16" href="/icons/favicon-16x16.png?v=2">
        <link rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32x32.png?v=2">
        <link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192.png?v=2">
        <link rel="icon" type="image/png" sizes="512x512" href="/icons/icon-512.png?v=2">
        <link rel="apple-touch-icon" sizes="180x180" href="/icons/apple-touch-icon.png?v=2">
        <script src="https://cdn.tailwindcss.com"></script>
        <script>
            tailwind.config = {
                darkMode: 'class'
            };
        </script>
        <script>
            // Anti-FOUC instantaneous theme & highlight accent initializer
            (function() {
                try {
                    const savedMode = localStorage.getItem('fact_theme_mode');
                    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
                    const isDark = savedMode === 'dark' || (!savedMode && prefersDark);
                    if (isDark) {
                        document.documentElement.classList.add('dark');
                    } else {
                        document.documentElement.classList.remove('dark');
                    }
                    const savedColor = localStorage.getItem('fact_highlight_color') || 'amber';
                    const palettes = {
                        amber: { 
                            primary: '#d97706', primaryHover: '#b45309', 
                            textLight: '#b45309', textDark: '#fbbf24', 
                            ring: 'rgba(217, 119, 6, 0.4)', 
                            borderLight: 'rgba(217, 119, 6, 0.3)', borderDark: 'rgba(217, 119, 6, 0.45)',
                            softBgLight: 'rgba(245, 158, 11, 0.12)', softBgDark: 'rgba(245, 158, 11, 0.22)',
                            border: '#d97706', bg: 'rgba(245, 158, 11, 0.28)', ringGlow: 'rgba(251, 191, 36, 0.5)', 
                            glow: 'rgba(245, 158, 11, 0.4)', ringPulse: 'rgba(251, 191, 36, 0.8)', glowPulse: 'rgba(245, 158, 11, 0.9)', 
                            pillBg: '#d97706', pillBorder: '#b45309', hex: '#d97706' 
                        },
                        emerald: { 
                            primary: '#059669', primaryHover: '#047857', 
                            textLight: '#047857', textDark: '#34d399', 
                            ring: 'rgba(5, 150, 105, 0.4)', 
                            borderLight: 'rgba(5, 150, 105, 0.3)', borderDark: 'rgba(5, 150, 105, 0.45)',
                            softBgLight: 'rgba(16, 185, 129, 0.12)', softBgDark: 'rgba(16, 185, 129, 0.22)',
                            border: '#059669', bg: 'rgba(16, 185, 129, 0.26)', ringGlow: 'rgba(52, 211, 153, 0.5)', 
                            glow: 'rgba(16, 185, 129, 0.4)', ringPulse: 'rgba(52, 211, 153, 0.8)', glowPulse: 'rgba(16, 185, 129, 0.9)', 
                            pillBg: '#059669', pillBorder: '#047857', hex: '#059669' 
                        },
                        teal: { 
                            primary: '#0d9488', primaryHover: '#0f766e', 
                            textLight: '#0f766e', textDark: '#2dd4bf', 
                            ring: 'rgba(13, 148, 136, 0.4)', 
                            borderLight: 'rgba(13, 148, 136, 0.3)', borderDark: 'rgba(13, 148, 136, 0.45)',
                            softBgLight: 'rgba(20, 184, 166, 0.12)', softBgDark: 'rgba(20, 184, 166, 0.22)',
                            border: '#0d9488', bg: 'rgba(20, 184, 166, 0.26)', ringGlow: 'rgba(45, 212, 191, 0.5)', 
                            glow: 'rgba(20, 184, 166, 0.4)', ringPulse: 'rgba(45, 212, 191, 0.8)', glowPulse: 'rgba(20, 184, 166, 0.9)', 
                            pillBg: '#0d9488', pillBorder: '#0f766e', hex: '#0d9488' 
                        },
                        blue: { 
                            primary: '#0284c7', primaryHover: '#0369a1', 
                            textLight: '#0369a1', textDark: '#38bdf8', 
                            ring: 'rgba(2, 132, 199, 0.4)', 
                            borderLight: 'rgba(2, 132, 199, 0.3)', borderDark: 'rgba(2, 132, 199, 0.45)',
                            softBgLight: 'rgba(2, 132, 199, 0.12)', softBgDark: 'rgba(2, 132, 199, 0.22)',
                            border: '#0284c7', bg: 'rgba(2, 132, 199, 0.25)', ringGlow: 'rgba(56, 189, 248, 0.5)', 
                            glow: 'rgba(2, 132, 199, 0.4)', ringPulse: 'rgba(56, 189, 248, 0.8)', glowPulse: 'rgba(2, 132, 199, 0.9)', 
                            pillBg: '#0284c7', pillBorder: '#0369a1', hex: '#0284c7' 
                        },
                        indigo: { 
                            primary: '#4f46e5', primaryHover: '#4338ca', 
                            textLight: '#4338ca', textDark: '#818cf8', 
                            ring: 'rgba(79, 70, 229, 0.4)', 
                            borderLight: 'rgba(79, 70, 229, 0.3)', borderDark: 'rgba(79, 70, 229, 0.45)',
                            softBgLight: 'rgba(79, 70, 229, 0.12)', softBgDark: 'rgba(79, 70, 229, 0.22)',
                            border: '#4f46e5', bg: 'rgba(79, 70, 229, 0.25)', ringGlow: 'rgba(129, 140, 248, 0.5)', 
                            glow: 'rgba(79, 70, 229, 0.4)', ringPulse: 'rgba(129, 140, 248, 0.8)', glowPulse: 'rgba(79, 70, 229, 0.9)', 
                            pillBg: '#4f46e5', pillBorder: '#4338ca', hex: '#4f46e5' 
                        },
                        violet: { 
                            primary: '#7c3aed', primaryHover: '#6d28d9', 
                            textLight: '#6d28d9', textDark: '#a78bfa', 
                            ring: 'rgba(124, 58, 237, 0.4)', 
                            borderLight: 'rgba(124, 58, 237, 0.3)', borderDark: 'rgba(124, 58, 237, 0.45)',
                            softBgLight: 'rgba(124, 58, 237, 0.12)', softBgDark: 'rgba(124, 58, 237, 0.22)',
                            border: '#7c3aed', bg: 'rgba(124, 58, 237, 0.25)', ringGlow: 'rgba(167, 139, 250, 0.5)', 
                            glow: 'rgba(124, 58, 237, 0.4)', ringPulse: 'rgba(167, 139, 250, 0.8)', glowPulse: 'rgba(124, 58, 237, 0.9)', 
                            pillBg: '#7c3aed', pillBorder: '#6d28d9', hex: '#7c3aed' 
                        },
                        rose: { 
                            primary: '#e11d48', primaryHover: '#be123c', 
                            textLight: '#be123c', textDark: '#fb7185', 
                            ring: 'rgba(225, 29, 72, 0.4)', 
                            borderLight: 'rgba(225, 29, 72, 0.3)', borderDark: 'rgba(225, 29, 72, 0.45)',
                            softBgLight: 'rgba(225, 29, 72, 0.12)', softBgDark: 'rgba(225, 29, 72, 0.22)',
                            border: '#e11d48', bg: 'rgba(225, 29, 72, 0.25)', ringGlow: 'rgba(251, 113, 133, 0.5)', 
                            glow: 'rgba(225, 29, 72, 0.4)', ringPulse: 'rgba(251, 113, 133, 0.8)', glowPulse: 'rgba(225, 29, 72, 0.9)', 
                            pillBg: '#e11d48', pillBorder: '#be123c', hex: '#e11d48' 
                        },
                        slate: { 
                            primary: '#475569', primaryHover: '#334155', 
                            textLight: '#334155', textDark: '#94a3b8', 
                            ring: 'rgba(71, 85, 105, 0.4)', 
                            borderLight: 'rgba(71, 85, 105, 0.3)', borderDark: 'rgba(71, 85, 105, 0.45)',
                            softBgLight: 'rgba(71, 85, 105, 0.12)', softBgDark: 'rgba(71, 85, 105, 0.22)',
                            border: '#475569', bg: 'rgba(71, 85, 105, 0.3)', ringGlow: 'rgba(148, 163, 184, 0.5)', 
                            glow: 'rgba(71, 85, 105, 0.4)', ringPulse: 'rgba(148, 163, 184, 0.8)', glowPulse: 'rgba(71, 85, 105, 0.9)', 
                            pillBg: '#475569', pillBorder: '#334155', hex: '#475569' 
                        }
                    };
                    const p = palettes[savedColor] || palettes.amber;
                    const r = document.documentElement;
                    r.style.setProperty('--accent-primary', p.primary);
                    r.style.setProperty('--accent-hover', p.primaryHover);
                    r.style.setProperty('--accent-text', isDark ? p.textDark : p.textLight);
                    r.style.setProperty('--accent-ring', p.ring);
                    r.style.setProperty('--accent-border', isDark ? p.borderDark : p.borderLight);
                    r.style.setProperty('--accent-soft-bg', isDark ? p.softBgDark : p.softBgLight);
                    r.style.setProperty('--highlight-border', p.border);
                    r.style.setProperty('--highlight-bg', p.bg);
                    r.style.setProperty('--highlight-ring', p.ringGlow);
                    r.style.setProperty('--highlight-glow', p.glow);
                    r.style.setProperty('--highlight-ring-pulse', p.ringPulse);
                    r.style.setProperty('--highlight-glow-pulse', p.glowPulse);
                    r.style.setProperty('--highlight-pill-bg', p.pillBg);
                    r.style.setProperty('--highlight-pill-border', p.pillBorder);
                    r.style.setProperty('--highlight-hex', p.hex);

                    // Instantaneous PWA title bar color initialization
                    const metaThemeColor = document.getElementById('pwaThemeColor') || document.querySelector('meta[name="theme-color"]');
                    if (metaThemeColor && p.primary) {
                        metaThemeColor.setAttribute('content', p.primary);
                    }
                } catch(e) {}
            })();
        </script>
        <!-- Marked.js for rich markdown rendering -->
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <!-- Firebase 10.12.0 Compat SDKs -->
        <script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
        <script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore-compat.js"></script>
        <style>
            :root {
                --accent-primary: #d97706;
                --accent-hover: #b45309;
                --accent-text: #b45309;
                --accent-ring: rgba(217, 119, 6, 0.4);
                --accent-border: rgba(217, 119, 6, 0.3);
                --accent-soft-bg: rgba(245, 158, 11, 0.12);
                --highlight-border: #d97706;
                --highlight-bg: rgba(245, 158, 11, 0.28);
                --highlight-ring: rgba(251, 191, 36, 0.5);
                --highlight-glow: rgba(245, 158, 11, 0.4);
                --highlight-ring-pulse: rgba(251, 191, 36, 0.8);
                --highlight-glow-pulse: rgba(245, 158, 11, 0.9);
                --highlight-pill-bg: #d97706;
                --highlight-pill-border: #b45309;
                --highlight-hex: #d97706;
            }
            html.dark {
                --accent-text: #fbbf24;
                --accent-border: rgba(217, 119, 6, 0.45);
                --accent-soft-bg: rgba(245, 158, 11, 0.22);
            }
            /* Dynamic Accent Color Utility Classes linked to Highlight Palette */
            .btn-primary-accent,
            button#runBtn,
            button#resolveBtn,
            button#finderSubmitBtn,
            button#summarizerSubmitBtn,
            button#askSubmitBtn,
            button#signInHeaderBtn,
            button#preApproveBtn,
            button#authSubmitBtn,
            button#settingsDoneBtn,
            #abstractModal button.bg-sky-600 {
                background-color: var(--accent-primary, #0284c7) !important;
                color: #ffffff !important;
                border-color: var(--accent-primary, #0284c7) !important;
                cursor: pointer;
            }
            .btn-primary-accent:hover,
            button#runBtn:hover,
            button#resolveBtn:hover,
            button#finderSubmitBtn:hover,
            button#summarizerSubmitBtn:hover,
            button#askSubmitBtn:hover,
            button#signInHeaderBtn:hover,
            button#preApproveBtn:hover,
            button#authSubmitBtn:hover,
            button#settingsDoneBtn:hover,
            #abstractModal button.bg-sky-600:hover {
                background-color: var(--accent-hover, #0369a1) !important;
                border-color: var(--accent-hover, #0369a1) !important;
            }

            #pdfFile::file-selector-button {
                background-color: var(--accent-primary, #0284c7) !important;
                color: #ffffff !important;
                border: 0 !important;
                cursor: pointer;
                font-weight: 600;
                font-size: 0.75rem;
                padding: 0.25rem 0.75rem;
                border-radius: 0.25rem;
                margin-right: 0.625rem;
                transition: background-color 0.15s ease;
            }
            #pdfFile::file-selector-button:hover {
                background-color: var(--accent-hover, #0369a1) !important;
            }

            .fact-brand-title {
                color: var(--accent-text, #0369a1) !important;
            }

            .tab-active-accent {
                color: var(--accent-text, #0369a1) !important;
                font-weight: 700 !important;
            }

            #paperUrl:focus,
            #finderSearchInput:focus,
            #summarizerUrlsInput:focus,
            #askQuestionInput:focus,
            #preApproveEmailInput:focus,
            #adminSearchInput:focus {
                outline: none !important;
                border-color: var(--accent-primary, #0284c7) !important;
                box-shadow: 0 0 0 2px var(--accent-ring, rgba(2, 132, 199, 0.4)) !important;
            }

            #summarizerBatchBadge {
                background-color: var(--accent-primary, #0284c7) !important;
            }
            .anchor-pill {
                cursor: pointer;
                transition: all 0.15s ease-in-out;
            }
            .anchor-pill:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            }
            .anchor-pill.active {
                background-color: var(--highlight-pill-bg, #0284c7) !important;
                color: #ffffff !important;
                border-color: var(--highlight-pill-border, #0369a1) !important;
            }
            /* Rich Typography for Clinical Analysis Markdown */
            #outputMarkdown h1 {
                font-size: 1.35rem !important;
                font-weight: 800 !important;
                color: #0f172a !important; /* slate-900 */
                line-height: 1.3 !important;
                margin-top: 0 !important;
                margin-bottom: 0.85rem !important;
                letter-spacing: -0.015em !important;
            }
            #outputMarkdown h2 {
                font-size: 1.125rem !important;
                font-weight: 700 !important;
                color: var(--accent-text, #0369a1) !important;
                margin-top: 1.25rem !important;
                margin-bottom: 0.5rem !important;
                letter-spacing: -0.01em !important;
            }
            #outputMarkdown h3 {
                font-size: 1.0rem !important;
                font-weight: 700 !important;
                color: #1e293b !important; /* slate-800 */
                margin-top: 1rem !important;
                margin-bottom: 0.35rem !important;
            }
            /* Classic Live Hyperlink Style for DOI & External Links */
            #outputMarkdown a, .doi-link {
                color: #0000ee !important;
                text-decoration: underline !important;
                font-weight: 500;
                cursor: pointer;
                transition: font-weight 0.1s ease, color 0.1s ease;
            }
            #outputMarkdown a:hover, .doi-link:hover {
                color: #0000cc !important;
                font-weight: 700 !important;
                text-decoration: underline !important;
            }
            /* Dark Mode Overrides for Rich Markdown & Document UI */
            html.dark #outputMarkdown {
                color: #e2e8f0 !important;
            }
            html.dark #outputMarkdown h1 {
                color: #f8fafc !important;
            }
            html.dark #outputMarkdown h2 {
                color: var(--accent-text, #38bdf8) !important;
            }
            html.dark #outputMarkdown h3 {
                color: #cbd5e1 !important;
            }
            html.dark #outputMarkdown strong {
                color: #f1f5f9 !important;
            }
            html.dark #outputMarkdown a, html.dark .doi-link {
                color: #60a5fa !important;
            }
            html.dark #outputMarkdown a:hover, html.dark .doi-link:hover {
                color: #93c5fd !important;
            }
            html.dark .resizer {
                background-color: #334155 !important;
            }
            html.dark .resizer:hover, html.dark .resizer.resizing {
                background-color: var(--accent-primary, #38bdf8) !important;
            }
            html.dark #sectionPopup {
                background: #0f172a !important;
                border-color: var(--accent-primary, #0284c7) !important;
                color: #f8fafc !important;
            }
            html.dark #popupHeader {
                background: var(--accent-hover, #1e293b) !important;
                border-bottom: 1px solid #334155 !important;
            }
            html.dark #popupTitle {
                color: #f8fafc !important;
            }
            html.dark #popupScrollContainer {
                background: #0f172a !important;
            }
            html.dark #popupScrollContainer::-webkit-scrollbar-track {
                background: #0f172a !important;
            }
            html.dark #popupScrollContainer::-webkit-scrollbar-thumb {
                background-color: #475569 !important;
            }
            html.dark #popupScrollContainer::-webkit-scrollbar-thumb:hover {
                background-color: #64748b !important;
            }
            /* Draggable resizer styling */
            .resizer {
                width: 8px;
                cursor: col-resize;
                background-color: #cbd5e1;
                transition: background-color 0.2s;
                position: relative;
                flex-shrink: 0;
                border-radius: 4px;
            }
            .resizer:hover, .resizer.resizing {
                background-color: var(--accent-primary, #0284c7) !important;
            }
            /* Hover highlight popover box on the manuscript page */
            #imageContainer {
                position: relative;
            }
            #highlightHitbox {
                position: absolute;
                cursor: zoom-in;
                border: 2px solid var(--highlight-border, #d97706);
                background-color: var(--highlight-bg, rgba(245, 158, 11, 0.28));
                border-radius: 4px;
                box-shadow: 0 0 0 2px var(--highlight-ring, rgba(251, 191, 36, 0.5)), 0 0 15px var(--highlight-glow, rgba(245, 158, 11, 0.4));
                z-index: 25;
                pointer-events: auto;
                transition: top 0.15s ease-out, left 0.15s ease-out, width 0.15s ease-out, height 0.15s ease-out;
            }
            @keyframes highlightPulse {
                0% { box-shadow: 0 0 0 2px var(--highlight-ring-pulse, rgba(251, 191, 36, 0.8)), 0 0 20px var(--highlight-glow-pulse, rgba(245, 158, 11, 0.9)); }
                50% { box-shadow: 0 0 0 5px var(--highlight-ring-pulse, rgba(251, 191, 36, 1.0)), 0 0 30px var(--highlight-glow-pulse, rgba(245, 158, 11, 1.0)); }
                100% { box-shadow: 0 0 0 2px var(--highlight-ring, rgba(251, 191, 36, 0.5)), 0 0 15px var(--highlight-glow, rgba(245, 158, 11, 0.4)); }
            }
            .hitbox-pulse {
                animation: highlightPulse 0.8s ease-in-out;
            }
            #sectionPopup {
                position: fixed;
                display: none;
                flex-direction: column;
                z-index: 9999;
                width: 740px;
                min-width: 320px;
                min-height: 180px;
                max-width: calc(100vw - 20px);
                max-height: calc(100vh - 20px);
                background: #ffffff;
                border: 2px solid var(--accent-primary, #0284c7);
                border-radius: 12px;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.45), 0 10px 20px -5px rgba(0, 0, 0, 0.2);
                overflow: hidden;
                pointer-events: auto;
                animation: popIn 0.15s ease-out;
            }
            #popupHeader {
                cursor: grab;
                user-select: none;
                flex-shrink: 0;
            }
            #popupHeader:active {
                cursor: grabbing;
            }
            .popup-resizer {
                position: absolute;
                z-index: 40;
                user-select: none;
            }
            .popup-resizer.edge-r {
                top: 0;
                right: 0;
                width: 8px;
                height: 100%;
                cursor: ew-resize;
            }
            .popup-resizer.edge-b {
                bottom: 0;
                left: 0;
                width: 100%;
                height: 8px;
                cursor: ns-resize;
            }
            .popup-resizer.edge-l {
                top: 0;
                left: 0;
                width: 8px;
                height: 100%;
                cursor: ew-resize;
            }
            .popup-resizer.edge-t {
                top: 0;
                left: 0;
                width: 100%;
                height: 6px;
                cursor: ns-resize;
            }
            .popup-resizer.corner-br {
                bottom: 0;
                right: 0;
                width: 20px;
                height: 20px;
                cursor: nwse-resize;
                display: flex;
                align-items: flex-end;
                justify-content: flex-end;
                padding: 2px;
            }
            .popup-resizer.corner-bl {
                bottom: 0;
                left: 0;
                width: 14px;
                height: 14px;
                cursor: nesw-resize;
            }
            .popup-resizer.corner-tr {
                top: 0;
                right: 0;
                width: 14px;
                height: 14px;
                cursor: nesw-resize;
            }
            .popup-resizer.corner-tl {
                top: 0;
                left: 0;
                width: 14px;
                height: 14px;
                cursor: nwse-resize;
            }
            .popup-resizer.corner-br:hover svg {
                color: #0284c7;
            }
            #popupScrollContainer::-webkit-scrollbar {
                width: 8px;
                height: 8px;
            }
            #popupScrollContainer::-webkit-scrollbar-track {
                background: #f1f5f9;
            }
            #popupScrollContainer::-webkit-scrollbar-thumb {
                background-color: #94a3b8;
                border-radius: 4px;
            }
            #popupScrollContainer::-webkit-scrollbar-thumb:hover {
                background-color: #64748b;
            }
            @keyframes popIn {
                from { opacity: 0; transform: scale(0.96); }
                to { opacity: 1; transform: scale(1); }
            }

            /* Sleek tooltip styling for Study Badge */
            .study-badge-container {
                position: relative;
                display: inline-flex;
                align-items: center;
            }
            .study-badge-tooltip {
                visibility: hidden;
                opacity: 0;
                position: absolute;
                top: calc(100% + 8px);
                right: 0;
                width: 320px;
                background-color: #0f172a;
                color: #f8fafc;
                border-radius: 8px;
                padding: 12px 14px;
                font-size: 12px;
                line-height: 1.45;
                box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3), 0 8px 10px -6px rgba(0,0,0,0.2);
                z-index: 100;
                transition: opacity 0.2s ease, visibility 0.2s ease, transform 0.2s ease;
                transform: translateY(-4px);
                pointer-events: none;
            }
            .study-badge-tooltip::before {
                content: '';
                position: absolute;
                bottom: 100%;
                right: 20px;
                border-width: 6px;
                border-style: solid;
                border-color: transparent transparent #0f172a transparent;
            }
            .study-badge-container:hover .study-badge-tooltip {
                visibility: visible;
                opacity: 1;
                transform: translateY(0);
            }
        </style>
    </head>
    <body class="bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 min-h-screen p-4 transition-colors">
        <div class="max-w-[1700px] mx-auto space-y-3">
            <!-- Compact Header & Input Bar (Option 1) -->
            <header class="bg-white dark:bg-slate-900 px-5 py-3 rounded-lg border border-slate-200 dark:border-slate-800 shadow-xs flex flex-wrap items-center justify-between gap-4 transition-colors">
                <!-- Left: Logo & App Title -->
                <div class="flex items-center gap-3 shrink-0">
                    <div class="relative z-30 group shrink-0">
                        <div class="w-10 h-10 rounded-lg bg-white dark:bg-slate-800 flex items-center justify-center overflow-hidden border border-slate-200 dark:border-slate-700 shadow-2xs transition-all duration-300 ease-out origin-top-left group-hover:scale-[3.5] group-hover:rounded-xl group-hover:shadow-2xl group-hover:border-sky-300 group-hover:ring-4 group-hover:ring-sky-500/15 cursor-pointer">
                            <img 
                                src="/FACT-Elf.jpeg" 
                                alt="F.A.C.T. Logo" 
                                class="w-full h-full object-cover"
                            />
                        </div>
                    </div>
                    <div class="flex flex-col items-center text-center">
                        <div class="flex items-center gap-1.5">
                            <h1 class="text-xl font-bold fact-brand-title tracking-tight leading-none text-center">F.A.C.T.</h1>
                            <span class="px-1.5 py-0.5 rounded text-[10px] font-bold font-mono bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300 border border-sky-200 dark:border-sky-800 tracking-tight leading-none">v1.1</span>
                        </div>
                        <p class="text-slate-500 dark:text-slate-400 text-[11px] font-medium mt-1 text-center whitespace-nowrap">Find<span class="text-slate-400 dark:text-slate-600 font-bold px-1">·</span>Analyze<span class="text-slate-400 dark:text-slate-600 font-bold px-1">·</span>Contextualize<span class="text-slate-400 dark:text-slate-600 font-bold px-1">·</span>Talk</p>
                    </div>
                </div>

                <!-- Master 3-Mode Navigation Switcher: F.A.C.T. (Find -> Analyze -> Summarize/Check Trials) -->
                <div class="flex items-center bg-slate-100 dark:bg-slate-800 p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold gap-1 shrink-0">
                    <button id="masterTabFinder" onclick="switchMasterMode('finder')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>🔍</span> <span>Find</span>
                    </button>
                    <button id="masterTabAppraisal" onclick="switchMasterMode('appraisal')" class="px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs">
                        <span>🔬</span> <span>Analyze</span>
                    </button>
                    <button id="masterTabSummarizer" onclick="switchMasterMode('summarizer')" class="px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium">
                        <span>📝</span> <span>Contextualize</span>
                        <span id="summarizerBatchBadge" class="hidden ml-1 px-1.5 py-0.2 bg-sky-600 text-white rounded-full text-[10px] font-bold">0</span>
                    </button>
                </div>

                <!-- Center: Compact Unified Input (PDF or URL) -->
                <div class="flex items-center gap-2 bg-slate-50 dark:bg-slate-850 p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 flex-1 max-w-2xl">
                    <!-- Mode Switch Buttons -->
                    <div class="flex bg-slate-200/80 dark:bg-slate-800 p-0.5 rounded text-xs font-medium shrink-0">
                        <button id="tabPdfBtn" onclick="switchInputTab('pdf')" class="px-2.5 py-1 rounded bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-semibold transition">📄 PDF</button>
                        <button id="tabUrlBtn" onclick="switchInputTab('url')" class="px-2.5 py-1 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition">🔗 Link / PMID</button>
                    </div>

                    <!-- PDF Input Control -->
                    <div id="tabPdf" class="flex items-center gap-2 flex-1">
                        <input type="file" id="pdfFile" accept=".pdf" class="block w-full text-xs text-slate-600 dark:text-slate-300 cursor-pointer bg-white dark:bg-slate-900 px-2 py-1 rounded border border-slate-200 dark:border-slate-700"/>
                        <button onclick="startAppraisal()" id="runBtn" class="btn-primary-accent text-white font-semibold text-xs px-4 py-1.5 rounded transition shadow-xs shrink-0">Analyze</button>
                    </div>

                    <!-- URL / PMID Input Control -->
                    <div id="tabUrl" class="hidden flex items-center gap-2 flex-1">
                        <input type="text" id="paperUrl" placeholder="Paste PubMed URL, PMID (e.g. 37726553), PMC ID, or DOI" class="block w-full text-xs text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 px-3 py-1.5 rounded border border-slate-200 dark:border-slate-700 focus:outline-none"/>
                        <button onclick="startUrlResolution()" id="resolveBtn" class="btn-primary-accent text-white font-semibold text-xs px-4 py-1.5 rounded transition shadow-xs shrink-0">Fetch & Analyze</button>
                    </div>
                </div>

                <!-- Right: Study Type Badge with Rich Tooltip (Hidden until appraisal loaded) -->
                <div class="flex items-center gap-3 shrink-0">
                    <!-- Live Loading Spinner -->
                    <div id="statusBox" class="hidden flex items-center gap-2 text-xs font-medium text-sky-700 bg-sky-50 dark:bg-sky-950 dark:text-sky-300 px-3 py-1.5 rounded-md border border-sky-200 dark:border-sky-800">
                        <div id="spinner" class="animate-spin rounded-full h-3.5 w-3.5 border-2 border-sky-600 border-t-transparent"></div>
                        <span id="statusText">Processing...</span>
                    </div>

                    <!-- Study Wonk Framework Badge with Hover Tooltip -->
                    <div id="studyBadgeWrapper" class="hidden study-badge-container cursor-help">
                        <div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-sky-100 dark:bg-sky-950/80 text-sky-900 dark:text-sky-300 border border-sky-300 dark:border-sky-800 text-xs font-semibold shadow-2xs hover:bg-sky-200 dark:hover:bg-sky-900 transition">
                            <span class="w-2 h-2 rounded-full bg-sky-600"></span>
                            <span id="studyBadgeText">Biomarker Study</span>
                            <span class="text-sky-500 font-normal ml-0.5 text-[10px]">ℹ</span>
                        </div>
                        <!-- Tooltip Container -->
                        <div class="study-badge-tooltip">
                            <div class="font-bold text-sky-300 mb-1 flex items-center justify-between border-b border-slate-700 pb-1">
                                <span id="tooltipFwId">Study Design</span>
                                <span id="tooltipRulesCount" class="text-amber-300 font-normal text-[11px]">0 Rules</span>
                            </div>
                            <p id="tooltipFwDesc" class="text-slate-300 text-[11px] mb-2 leading-relaxed">Framework description</p>
                            <div class="text-[11px] text-slate-400">
                                <span class="font-semibold text-slate-200">Applicable Methodological Rules:</span>
                                <ul id="tooltipRulesList" class="mt-1 list-disc list-inside space-y-0.5 text-[10px] text-slate-300">
                                    <li>Grounded Analysis Rules</li>
                                </ul>
                            </div>
                        </div>
                    </div>

                    <!-- Auth & User Access Header Area -->
                    <div id="authHeaderArea" class="flex items-center gap-2 pl-2 border-l border-slate-200 dark:border-slate-800">
                        <!-- Settings Gear Button (Always Accessible) -->
                        <button id="settingsBtn" onclick="openSettingsModal()" class="relative p-2 rounded-lg bg-slate-50 hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer" title="Display & Highlight Settings" aria-label="Settings">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
                            <!-- Highlight Color indicator dot -->
                            <span id="settingsHighlightDot" class="absolute top-1 right-1 w-2 h-2 rounded-full ring-1 ring-white dark:ring-slate-900" style="background-color: var(--highlight-hex, #d97706);"></span>
                        </button>

                        <!-- Sign In Button (Shown when unauthenticated) -->
                        <button id="signInHeaderBtn" onclick="openAuthModal()" class="btn-primary-accent px-3 py-1.5 rounded-lg text-white font-semibold text-xs shadow-xs transition flex items-center gap-1.5">
                            <span>🔑</span> <span>Sign In</span>
                        </button>

                        <!-- User Profile Area (Shown when signed in) -->
                        <div id="userProfileHeader" class="hidden flex items-center gap-2">
                            <!-- Admin Shield & Live Pending Counter (Master Admin drbiernd@gmail.com only) -->
                            <button id="adminUserMgmtBtn" onclick="openUserManagementModal()" class="hidden relative p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-slate-700 transition" title="User Access & Token Governance">
                                <span class="text-sm">🛡️</span>
                                <span id="adminPendingBadge" class="hidden absolute -top-1 -right-1 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-rose-500 text-white text-[10px] font-bold leading-none shadow-xs">
                                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                                    <span id="adminPendingCountText" class="relative">0</span>
                                </span>
                            </button>

                            <!-- User Avatar (Google Photo or Initial Badge) with Hover Tooltip -->
                            <div id="userProfilePill" class="relative group flex items-center cursor-pointer" title="">
                                <img id="userAvatarImg" 
                                     class="hidden w-7 h-7 rounded-full object-cover border border-slate-300 dark:border-slate-700 shadow-2xs hover:ring-2 hover:ring-sky-400 transition" 
                                     referrerpolicy="no-referrer" 
                                     alt="Profile Avatar"
                                     onerror="this.classList.add('hidden'); const c = document.getElementById('userAvatarCircle'); if(c) c.classList.remove('hidden');" />
                                <div id="userAvatarCircle" 
                                     class="w-7 h-7 rounded-full bg-sky-700 text-white font-bold text-xs flex items-center justify-center uppercase shadow-2xs hover:ring-2 hover:ring-sky-400 transition">
                                    U
                                </div>
                                <!-- Floating Hover Card (Reveals user name & email on hover) -->
                                <div class="hidden group-hover:flex absolute right-0 top-full mt-2 z-50 flex-col items-start whitespace-nowrap bg-slate-900/95 backdrop-blur-xs text-white text-[11px] py-1.5 px-3 rounded-lg shadow-xl border border-slate-700 pointer-events-none transition-all">
                                    <span id="userTooltipName" class="font-semibold text-slate-100"></span>
                                    <span id="userTooltipEmail" class="text-slate-300 font-mono text-[10px]"></span>
                                </div>
                            </div>

                            <!-- Sign Out Button -->
                            <button onclick="handleSignOut()" class="p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition" title="Sign Out">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"></path></svg>
                            </button>
                        </div>
                    </div>
                </div>
            </header>

            <!-- Abstract-Only Confirmation Dialog Modal -->
            <div id="abstractModal" class="hidden fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div class="bg-white rounded-xl border border-slate-200 shadow-xl max-w-lg w-full p-6 space-y-4">
                    <div class="flex items-center gap-3 text-amber-600">
                        <svg class="w-6 h-6 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                        <h3 id="abstractModalTitle" class="text-lg font-bold text-slate-900">Full Text Unavailable (Abstract Only)</h3>
                    </div>
                    <p id="abstractModalDesc" class="text-sm text-slate-600 leading-relaxed">
                        The requested URL or identifier does not have a free full-text manuscript available (likely behind a journal paywall). We retrieved the official published abstract.
                    </p>
                    <div id="publisherLinkBox" class="hidden p-3 bg-sky-50 rounded-md border border-sky-200 text-xs text-sky-950 space-y-1.5">
                        <div class="font-semibold flex items-center gap-1.5 text-sky-900">
                            <span>📄</span> <span>Direct Manuscript Download Available:</span>
                        </div>
                        <p class="text-[11px] text-sky-800">
                            The publisher restricts automated API downloading, but you can download the full-text PDF directly in your browser:
                        </p>
                        <a id="publisherDirectLink" href="#" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-xs font-semibold text-sky-700 hover:text-sky-900 underline font-mono break-all pt-0.5">
                            Open Paper on PubMed Central ↗
                        </a>
                    </div>
                    <!-- Alternate Open-Access / Google Scholar Version Finder Box -->
                    <div id="scholarAlternateBox" class="p-3 bg-slate-50 dark:bg-slate-800/60 rounded-md border border-slate-200 dark:border-slate-700 text-xs text-slate-800 dark:text-slate-200 flex items-center justify-between gap-3">
                        <div class="space-y-0.5">
                            <div class="font-semibold flex items-center gap-1.5 text-slate-900 dark:text-slate-100">
                                <span>🎓</span> <span>Check Google Scholar for Alternate Free PDF:</span>
                            </div>
                            <p class="text-[11px] text-slate-500 dark:text-slate-400">
                                Find author-deposited institutional pre-prints or open university repositories:
                            </p>
                        </div>
                        <a id="scholarSearchLink" href="#" target="_blank" rel="noopener noreferrer" class="shrink-0 px-3 py-1.5 rounded-md bg-white dark:bg-slate-700 hover:bg-sky-50 dark:hover:bg-slate-600 text-sky-700 dark:text-sky-300 border border-slate-300 dark:border-slate-600 font-semibold text-xs transition flex items-center gap-1 shadow-2xs">
                            <span>🔍 Find on Scholar ↗</span>
                        </a>
                    </div>
                    <div class="p-3 bg-amber-50 rounded-md border border-amber-200 text-xs text-amber-900 max-h-36 overflow-y-auto font-serif italic" id="modalAbstractSnippet"></div>
                    <p id="abstractModalPrompt" class="text-xs font-semibold text-slate-700">Would you like to manually upload the PDF or analyze the abstract only?</p>
                    <div class="flex flex-wrap items-center justify-between gap-3 pt-2">
                        <button onclick="closeAbstractModal()" class="px-3.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-md transition">Cancel</button>
                        <div class="flex items-center gap-2">
                            <button id="modalUploadBtn" onclick="switchToManualUpload()" class="hidden px-3.5 py-2 text-xs font-semibold text-sky-700 hover:text-sky-900 bg-sky-100 hover:bg-sky-200 rounded-md border border-sky-300 transition">
                                📤 Upload PDF Manually
                            </button>
                            <button onclick="proceedWithAbstractOnly()" class="btn-primary-accent px-4 py-2 text-xs font-semibold text-white rounded-md transition shadow">Analyze Abstract Only</button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Authentication Modal (Sign In / Register / Reset) -->
            <div id="authModal" class="hidden fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div class="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-md w-full p-6 space-y-5 animate-in fade-in zoom-in-95 duration-150">
                    <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                        <div class="flex items-center gap-2">
                            <span class="text-xl">🔐</span>
                            <h3 id="authModalTitle" class="text-base font-bold text-slate-900">Sign in to F.A.C.T.</h3>
                        </div>
                        <button onclick="closeAuthModal()" class="text-slate-400 hover:text-slate-600 text-sm font-bold p-1">✕</button>
                    </div>

                    <div id="authErrorBox" class="hidden p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg text-xs leading-relaxed"></div>
                    <div id="authSuccessBox" class="hidden p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg text-xs leading-relaxed"></div>

                    <!-- Google 1-Tap / Popup Button -->
                    <button id="googleSignInBtn" onclick="handleGoogleSignIn()" class="w-full flex items-center justify-center gap-3 bg-white hover:bg-slate-50 text-slate-700 font-semibold text-xs py-2.5 px-4 rounded-xl border border-slate-300 shadow-2xs hover:shadow-xs transition">
                        <svg class="w-4 h-4" viewBox="0 0 24 24">
                            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
                            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
                        </svg>
                        <span>Continue with Google</span>
                    </button>

                    <div class="flex items-center gap-3">
                        <div class="h-px bg-slate-200 flex-1"></div>
                        <span class="text-[11px] text-slate-400 font-medium uppercase tracking-wider">or with email</span>
                        <div class="h-px bg-slate-200 flex-1"></div>
                    </div>

                    <!-- Email & Password Form -->
                    <form id="authEmailForm" onsubmit="handleEmailAuth(event)" class="space-y-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-700 mb-1">Email address</label>
                            <input type="email" id="authEmailInput" required placeholder="doctor@hospital.org" class="w-full text-xs bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500 transition"/>
                        </div>

                        <div id="passwordFieldGroup">
                            <label class="block text-xs font-semibold text-slate-700 mb-1">Password</label>
                            <input type="password" id="authPasswordInput" placeholder="••••••••" class="w-full text-xs bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500 transition"/>
                        </div>

                        <button type="submit" id="authSubmitBtn" class="btn-primary-accent w-full text-white font-semibold text-xs py-2.5 px-4 rounded-xl shadow-xs transition flex items-center justify-center gap-2">
                            <span id="authSubmitText">Sign In</span>
                        </button>
                    </form>

                    <!-- Auth Mode Toggle Links -->
                    <div class="flex items-center justify-between text-xs text-slate-500 pt-2 border-t border-slate-100">
                        <button type="button" id="authToggleModeBtn" onclick="toggleAuthMode()" class="text-sky-600 hover:text-sky-800 font-semibold transition">Need an account? Create one</button>
                        <button type="button" id="authForgotBtn" onclick="toggleForgotMode()" class="text-slate-400 hover:text-slate-600 transition">Forgot password?</button>
                    </div>
                </div>
            </div>

            <!-- Access Pending Approval Gatekeeper Modal -->
            <div id="pendingApprovalModal" class="hidden fixed inset-0 bg-slate-900/70 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div class="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-lg w-full p-6 text-center space-y-4 animate-in fade-in zoom-in-95 duration-150">
                    <div class="w-14 h-14 mx-auto rounded-full bg-amber-100 border border-amber-200 flex items-center justify-center text-2xl shadow-xs">
                        ⏳
                    </div>
                    <div class="space-y-1">
                        <h3 class="text-lg font-bold text-slate-900" id="pendingModalTitle">Access Authorization Pending</h3>
                        <p class="text-xs text-slate-500" id="pendingModalUserEmail">Signed in as user@example.com</p>
                    </div>
                    <div class="bg-amber-50/80 border border-amber-200/80 rounded-xl p-4 text-xs text-amber-900 leading-relaxed text-left space-y-2">
                        <p class="font-medium" id="pendingModalMessage">
                            Your account has been registered in the F.A.C.T. clinician registry. An administrator must approve your account before you can analyze manuscripts or run searches.
                        </p>
                        <div class="flex items-center gap-2 text-[11px] text-amber-700 font-semibold pt-1 border-t border-amber-200/60">
                            <span class="inline-block w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
                            <span>Live sync active: This screen unlocks automatically once approved.</span>
                        </div>
                    </div>
                    <div class="flex items-center justify-center gap-3 pt-2">
                        <button onclick="checkUserStatusManual()" class="px-4 py-2 text-xs font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 border border-sky-200 rounded-lg transition">Check Status</button>
                        <button onclick="handleSignOut()" class="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-lg transition">Sign Out</button>
                    </div>
                </div>
            </div>

            <!-- Master Admin User Access & Token Governance Modal (drbiernd@gmail.com only) -->
            <div id="userManagementModal" class="hidden fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div class="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-4xl w-full max-h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
                    <!-- Modal Header -->
                    <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/50 shrink-0">
                        <div class="flex items-center gap-3">
                            <div class="w-9 h-9 rounded-lg bg-sky-100 border border-sky-200 flex items-center justify-center text-lg">🛡️</div>
                            <div>
                                <h3 class="text-sm font-bold text-slate-900">User Access & Token Governance</h3>
                                <p class="text-xs text-slate-500">Manage clinician approval gates and inspect live LLM token telemetry.</p>
                            </div>
                        </div>
                        <button onclick="closeUserManagementModal()" class="text-slate-400 hover:text-slate-600 text-sm font-bold p-1.5 rounded-lg hover:bg-slate-100 transition">✕</button>
                    </div>

                    <!-- Pre-Approval Whitelist Bar -->
                    <div class="px-6 py-3 bg-sky-50/50 border-b border-sky-100 flex items-center gap-2 shrink-0">
                        <span class="text-xs font-semibold text-sky-900 shrink-0">Pre-Approve Colleague:</span>
                        <input type="email" id="preApproveEmailInput" placeholder="colleague@clinic.org" class="flex-1 text-xs bg-white border border-slate-200 rounded-lg px-3 py-1.5 text-slate-800 focus:outline-none focus:ring-1 focus:ring-sky-500"/>
                        <button onclick="handlePreapproveEmail()" id="preApproveBtn" class="btn-primary-accent text-white font-semibold text-xs px-3.5 py-1.5 rounded-lg transition shadow-2xs shrink-0 flex items-center gap-1 cursor-pointer">
                            <span>➕</span> <span>Pre-Approve</span>
                        </button>
                    </div>

                    <!-- Tabs & Search Filter -->
                    <div class="px-6 py-2.5 border-b border-slate-200 bg-white flex flex-wrap items-center justify-between gap-3 shrink-0">
                        <div class="flex items-center gap-1.5 text-xs font-medium">
                            <button id="adminTabPending" onclick="switchAdminTab('pending')" class="px-3 py-1.5 rounded-lg bg-sky-100 text-sky-800 font-bold transition flex items-center gap-1.5">
                                <span>Pending</span>
                                <span id="adminTabPendingCount" class="px-1.5 py-0.2 rounded-full bg-rose-500 text-white text-[10px] font-bold">0</span>
                            </button>
                            <button id="adminTabApproved" onclick="switchAdminTab('approved')" class="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition flex items-center gap-1.5">
                                <span>Approved</span>
                                <span id="adminTabApprovedCount" class="px-1.5 py-0.2 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-semibold">0</span>
                            </button>
                            <button id="adminTabDenied" onclick="switchAdminTab('denied-revoked')" class="px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition flex items-center gap-1.5">
                                <span>Denied / Revoked</span>
                                <span id="adminTabDeniedCount" class="px-1.5 py-0.2 rounded-full bg-slate-200 text-slate-700 text-[10px] font-semibold">0</span>
                            </button>
                        </div>
                        <div class="relative">
                            <input type="text" id="adminSearchInput" oninput="filterAdminUserList()" placeholder="Filter by email or UID..." class="text-xs bg-slate-50 border border-slate-200 rounded-lg pl-7 pr-3 py-1.2 text-slate-800 focus:bg-white focus:outline-none focus:ring-1 focus:ring-sky-500"/>
                            <span class="absolute left-2.5 top-1.5 text-slate-400 text-xs">🔍</span>
                        </div>
                    </div>

                    <!-- User Cards Scrollable Container -->
                    <div id="adminUserListContainer" class="p-6 overflow-y-auto space-y-3 flex-1 bg-slate-50/40 dark:bg-slate-950/40">
                        <div class="text-center py-8 text-xs text-slate-400">Loading user registry...</div>
                    </div>
                </div>
            </div>

            <!-- Display & Appearance Settings Modal (Modeled after HomeoWonk) -->
            <div id="settingsModal" class="hidden fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 z-50 transition-opacity" onclick="if(event.target===this) closeSettingsModal();">
                <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl max-w-xl w-full flex flex-col max-h-[92vh] overflow-hidden text-slate-900 dark:text-slate-100 transition-colors">
                    <!-- Modal Header -->
                    <div class="px-5 py-4 border-b border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/90 flex items-center justify-between">
                        <div class="flex items-center gap-3">
                            <div class="p-2 rounded-lg bg-sky-100 dark:bg-sky-950 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800">
                                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"></path></svg>
                            </div>
                            <div>
                                <h2 class="text-base font-bold leading-tight">Settings &amp; Preferences</h2>
                                <p class="text-xs text-slate-500 dark:text-slate-400">Personalize appearance, default startup view, and highlight colors</p>
                            </div>
                        </div>
                        <button onclick="closeSettingsModal()" class="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition cursor-pointer" title="Close Settings">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                        </button>
                    </div>

                    <!-- Modal Body -->
                    <div class="p-5 sm:p-6 overflow-y-auto space-y-6 text-xs sm:text-sm">
                        <!-- Section 1: Appearance Mode -->
                        <section class="space-y-3">
                            <div class="flex items-center justify-between">
                                <div>
                                    <h3 class="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">1. Appearance Mode</h3>
                                    <p class="text-xs text-slate-600 dark:text-slate-300 mt-0.5">Choose light or dark surfaces for optimal reading comfort.</p>
                                </div>
                            </div>

                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                <!-- Light Mode Option -->
                                <button type="button" onclick="setThemeMode('light')" id="themeBtnLight" class="p-4 rounded-xl border text-left flex items-start space-x-3 transition cursor-pointer border-amber-400 bg-white shadow-xs ring-2 ring-amber-400/30">
                                    <div class="p-2.5 rounded-lg bg-amber-100 text-amber-900 border border-amber-300 shrink-0">
                                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path></svg>
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center justify-between">
                                            <span class="font-bold text-sm text-slate-900 dark:text-slate-100">Light Mode</span>
                                            <span id="themeCheckLight" class="w-5 h-5 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-800 dark:text-emerald-300 flex items-center justify-center text-xs font-bold border border-emerald-300 dark:border-emerald-700">✓</span>
                                        </div>
                                        <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">Crisp daylight readability. Zero dark-panel fatigue.</p>
                                    </div>
                                </button>

                                <!-- Dark Mode Option -->
                                <button type="button" onclick="setThemeMode('dark')" id="themeBtnDark" class="p-4 rounded-xl border text-left flex items-start space-x-3 transition cursor-pointer border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300">
                                    <div class="p-2.5 rounded-lg bg-indigo-950 text-indigo-300 border border-indigo-700 shrink-0">
                                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center justify-between">
                                            <span class="font-bold text-sm text-slate-900 dark:text-slate-100">Dark Mode</span>
                                            <span id="themeCheckDark" class="hidden w-5 h-5 rounded-full bg-indigo-600 text-white flex items-center justify-center text-xs font-bold">✓</span>
                                        </div>
                                        <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">Muted charcoal surfaces designed for evening and clinic use.</p>
                                    </div>
                                </button>
                            </div>
                        </section>

                        <!-- Section 2: Default Startup View -->
                        <section class="space-y-3">
                            <div class="flex items-center justify-between">
                                <div>
                                    <h3 class="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">2. Default Startup View</h3>
                                    <p class="text-xs text-slate-600 dark:text-slate-300 mt-0.5">Select which tool opens automatically when loading F.A.C.T.</p>
                                </div>
                            </div>

                            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                <!-- Find Option -->
                                <button type="button" onclick="setDefaultStartupMode('finder')" id="defaultModeBtnFinder" class="p-3.5 rounded-xl border text-left flex flex-col justify-between transition cursor-pointer border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300">
                                    <div>
                                        <div class="flex items-center justify-between">
                                            <span class="text-lg">🔍</span>
                                            <span id="defaultModeCheckFinder" class="hidden w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold border">✓</span>
                                        </div>
                                        <div class="font-bold text-sm text-slate-900 dark:text-slate-100 mt-2">Find</div>
                                        <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-snug">Verified Literature Finder</p>
                                    </div>
                                </button>

                                <!-- Analyze Option -->
                                <button type="button" onclick="setDefaultStartupMode('appraisal')" id="defaultModeBtnAppraisal" class="p-3.5 rounded-xl border text-left flex flex-col justify-between transition cursor-pointer border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300">
                                    <div>
                                        <div class="flex items-center justify-between">
                                            <span class="text-lg">🔬</span>
                                            <span id="defaultModeCheckAppraisal" class="hidden w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold border">✓</span>
                                        </div>
                                        <div class="font-bold text-sm text-slate-900 dark:text-slate-100 mt-2">Analyze</div>
                                        <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-snug">Clinical Manuscript Appraisal</p>
                                    </div>
                                </button>

                                <!-- Contextualize Option -->
                                <button type="button" onclick="setDefaultStartupMode('summarizer')" id="defaultModeBtnSummarizer" class="p-3.5 rounded-xl border text-left flex flex-col justify-between transition cursor-pointer border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300">
                                    <div>
                                        <div class="flex items-center justify-between">
                                            <span class="text-lg">📝</span>
                                            <span id="defaultModeCheckSummarizer" class="hidden w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold border">✓</span>
                                        </div>
                                        <div class="font-bold text-sm text-slate-900 dark:text-slate-100 mt-2">Contextualize</div>
                                        <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-snug">Multi-Study Evidence Synthesis</p>
                                    </div>
                                </button>
                            </div>
                        </section>

                        <!-- Section 3: Highlight Accent Color -->
                        <section class="space-y-3">
                            <div class="flex items-center justify-between">
                                <div>
                                    <h3 class="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">
                                        3. Highlight Color (Currently: <span id="activeHighlightName">Warm Amber</span>)
                                    </h3>
                                    <p class="text-xs text-slate-600 dark:text-slate-300 mt-0.5">
                                        Colors the PDF manuscript crop box, viewport pulse glow, and coordinate citation pills.
                                    </p>
                                </div>
                                <span id="activeHighlightBadge" class="text-xs px-2.5 py-0.5 rounded-full font-semibold bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300 border border-amber-300 dark:border-amber-700">
                                    Active
                                </span>
                            </div>

                            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5" id="highlightColorGrid"></div>
                        </section>

                        <!-- Section 4: Live Preview -->
                        <section class="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/60 space-y-2">
                            <span class="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">Live Preview</span>
                            <div class="flex flex-wrap items-center gap-3">
                                <span class="text-xs text-slate-600 dark:text-slate-300">Active Pill:</span>
                                <button class="anchor-pill active px-2.5 py-1 text-xs font-semibold rounded shadow-2xs leading-none">[Res, p6]</button>
                                <button class="anchor-pill px-2.5 py-1 text-xs font-semibold rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-850 text-slate-700 dark:text-slate-300 leading-none">[Disc, p1]</button>
                                <div class="flex items-center gap-2 pl-3 border-l border-slate-300 dark:border-slate-700">
                                    <span class="text-xs text-slate-600 dark:text-slate-300">Hitbox Glow:</span>
                                    <div id="previewHitbox" class="px-3 py-1 rounded text-xs font-mono border" style="border-color: var(--highlight-border); background-color: var(--highlight-bg); box-shadow: 0 0 0 2px var(--highlight-ring), 0 0 10px var(--highlight-glow);">
                                        Manuscript Excerpt
                                    </div>
                                </div>
                            </div>
                        </section>

                        <!-- Section 5: Clinician Voice Profile & Exemplars (Dual Firestore / Local Sync) -->
                        <section id="settingsVoiceSection" class="space-y-4 pt-3 border-t border-slate-200 dark:border-slate-800">
                            <div class="flex items-center justify-between">
                                <div>
                                    <h3 class="font-bold text-xs uppercase tracking-wider text-slate-500 dark:text-slate-400">5. Clinician Voice Profile &amp; Exemplars</h3>
                                    <p class="text-xs text-slate-600 dark:text-slate-300 mt-0.5">Calibrate editorial commentary voice, clinical philosophy, and past writing exemplars.</p>
                                </div>
                                <span id="voiceSyncBadge" class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                                    Rev 0 · Local
                                </span>
                            </div>

                            <!-- Editorial Philosophy -->
                            <div class="space-y-1.5">
                                <div class="flex justify-between items-center text-xs">
                                    <label class="font-semibold text-slate-700 dark:text-slate-300">Core Clinical Philosophy</label>
                                    <span class="text-[11px] text-slate-400 font-mono" id="voicePhilCount">0/500</span>
                                </div>
                                <textarea id="voicePhilosophyInput" maxlength="500" oninput="updateVoiceFieldCounts()" rows="3" class="w-full text-xs bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg p-2.5 text-slate-800 dark:text-slate-200 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-1 focus:ring-sky-500" placeholder="e.g. Prioritize natural therapies and nutritional interventions when safety profiles favor them; focus on absolute risk reductions over relative risk spin."></textarea>
                            </div>

                            <!-- Preferred & Prohibited Phrasing -->
                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                                <div class="space-y-1.5">
                                    <div class="flex justify-between items-center">
                                        <label class="font-semibold text-slate-700 dark:text-slate-300">Preferred Terms / Concepts</label>
                                        <span class="text-[11px] text-slate-400 font-mono" id="voicePrefCount">0/300</span>
                                    </div>
                                    <input type="text" id="voicePreferredInput" maxlength="300" oninput="updateVoiceFieldCounts()" class="w-full text-xs bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg px-2.5 py-2 text-slate-800 dark:text-slate-200 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-1 focus:ring-sky-500" placeholder="e.g. absolute risk reduction, confounding, clinical relevance"/>
                                </div>
                                <div class="space-y-1.5">
                                    <div class="flex justify-between items-center">
                                        <label class="font-semibold text-slate-700 dark:text-slate-300">Prohibited Boilerplate</label>
                                        <span class="text-[11px] text-slate-400 font-mono" id="voiceProhCount">0/300</span>
                                    </div>
                                    <input type="text" id="voiceProhibitedInput" maxlength="300" oninput="updateVoiceFieldCounts()" class="w-full text-xs bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg px-2.5 py-2 text-slate-800 dark:text-slate-200 focus:bg-white dark:focus:bg-slate-900 focus:outline-none focus:ring-1 focus:ring-sky-500" placeholder="e.g. more research is needed, delve, crucial to note"/>
                                </div>
                            </div>

                            <!-- Exemplar Writing Library -->
                            <div class="space-y-2 pt-2">
                                <div class="flex items-center justify-between text-xs">
                                    <div class="flex items-center gap-1.5">
                                        <span class="font-semibold text-slate-700 dark:text-slate-300">Past Writing Exemplars</span>
                                        <span class="text-[11px] text-slate-400">(Max 3 active, max 1,500 chars each)</span>
                                    </div>
                                    <button type="button" onclick="toggleNewExemplarForm()" class="text-xs text-sky-600 dark:text-sky-400 hover:underline font-semibold cursor-pointer">
                                        + Add Exemplar
                                    </button>
                                </div>

                                <!-- Add New Exemplar Box (Collapsible) -->
                                <div id="newExemplarBox" class="hidden p-3 rounded-lg border border-sky-200 dark:border-sky-800 bg-sky-50/50 dark:bg-sky-950/30 space-y-2">
                                    <input type="text" id="newExemplarTitle" placeholder="Exemplar Title (e.g. Statin vs Red Yeast Rice post)" class="w-full text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-md px-2.5 py-1.5 text-slate-800 dark:text-slate-200 focus:outline-none"/>
                                    <div class="relative">
                                        <textarea id="newExemplarText" maxlength="1500" oninput="updateNewExemplarCharCount()" rows="4" placeholder="Paste 1-3 paragraphs of your authentic writing style here..." class="w-full text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-md p-2.5 text-slate-800 dark:text-slate-200 focus:outline-none"></textarea>
                                        <span id="newExemplarCharCount" class="absolute bottom-2 right-2 text-[10px] text-slate-400 font-mono">0/1500</span>
                                    </div>
                                    <div class="flex justify-end gap-2">
                                        <button type="button" onclick="toggleNewExemplarForm()" class="px-2.5 py-1 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">Cancel</button>
                                        <button type="button" onclick="saveNewExemplar()" class="btn-primary-accent px-3 py-1 rounded text-xs text-white font-semibold">Save to Library</button>
                                    </div>
                                </div>

                                <!-- Exemplars List Container -->
                                <div id="exemplarsList" class="space-y-2 max-h-48 overflow-y-auto"></div>
                            </div>

                            <div class="flex justify-end pt-2">
                                <button type="button" onclick="saveVoiceProfileAndNotify()" class="btn-primary-accent text-white font-semibold text-xs px-4 py-2 rounded-lg transition shadow-xs cursor-pointer flex items-center gap-1.5">
                                    <span>💾</span> <span>Save Voice Profile</span>
                                </button>
                            </div>
                        </section>
                    </div>

                    <!-- Modal Footer -->
                    <div class="px-5 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/90 flex items-center justify-between">
                        <span class="text-[11px] font-mono text-slate-400 dark:text-slate-500">F.A.C.T. v1.0.0</span>
                        <button id="settingsDoneBtn" onclick="closeSettingsModal()" class="btn-primary-accent px-4 py-2 rounded-lg text-white font-semibold text-xs shadow-xs transition cursor-pointer">
                            Done
                        </button>
                    </div>
                </div>
            </div>

            <!-- Sibling Container 1: Paper Finder Mode -->
            <div id="finderContainer" class="hidden w-full overflow-y-auto space-y-4" style="height: calc(100vh - 105px);">
                <div class="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 shadow-xs max-w-5xl mx-auto space-y-5 text-slate-800 dark:text-slate-100">
                    <!-- Header & Directive -->
                    <div class="border-b border-slate-100 dark:border-slate-800 pb-4">
                        <div>
                            <h2 class="text-base font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
                                <span>🔍</span> Verified Literature Finder
                            </h2>
                            <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                Search PubMed & Europe PMC studies using natural language. Every result is verified against the published abstract.
                            </p>
                        </div>
                    </div>

                    <!-- Search Input -->
                    <div class="space-y-2">
                        <div class="flex gap-2">
                            <div class="relative flex-1">
                                <input 
                                    type="text" 
                                    id="finderSearchInput" 
                                    placeholder="e.g. Paper showing CoQ10 reduced heart attacks in women, done in a Scandinavian country..." 
                                    class="w-full text-xs bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg px-4 py-3 text-slate-800 dark:text-slate-100 focus:bg-white focus:dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500 transition shadow-2xs"
                                    onkeydown="if(event.key === 'Enter') executeFinderSearch();"
                                />
                                <button onclick="clearFinderSearch()" class="absolute right-3 top-3 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 text-xs font-bold" title="Clear search">✕</button>
                            </div>
                            <button 
                                id="finderSubmitBtn" 
                                onclick="executeFinderSearch()" 
                                class="btn-primary-accent text-white font-semibold text-xs px-5 py-3 rounded-lg transition shadow-xs flex items-center gap-2 shrink-0 cursor-pointer"
                            >
                                <span id="finderBtnIcon">🔍</span>
                                <span id="finderBtnText">Find Verified Papers</span>
                            </button>
                        </div>
                        <!-- Quick Example Chips & Cache Toggle -->
                        <div class="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] text-slate-500 dark:text-slate-400">
                            <div class="flex flex-wrap items-center gap-2">
                                <span class="font-medium">Try example query:</span>
                                <button onclick="setFinderQuery('CoQ10 reduced cardiovascular mortality in elderly Swedish cohort, 5 year follow up')" class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 hover:bg-sky-100 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 transition">
                                    CoQ10 cardiovascular mortality in Swedish cohort
                                </button>
                                <button onclick="setFinderQuery('Curcumin osteoarthritis randomized trial knee pain and inflammatory biomarkers')" class="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 hover:bg-sky-100 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 transition">
                                    Curcumin knee osteoarthritis RCT
                                </button>
                            </div>
                            <label class="flex items-center gap-1.5 cursor-pointer select-none text-[11px] text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200" title="Bypass the 24-hour cache and query PubMed / Europe PMC fresh">
                                <input type="checkbox" id="finderForceRefresh" class="rounded text-sky-600 focus:ring-sky-500 w-3.5 h-3.5"/>
                                <span>Bypass 24h Cache (Force Refresh)</span>
                            </label>
                        </div>
                    </div>

                    <!-- Search Status / Metadata Banner -->
                    <div id="finderStatusBanner" class="hidden rounded-lg p-3 text-xs flex items-center justify-between border"></div>

                    <!-- Verified Study Results List -->
                    <div id="finderResultsList" class="space-y-4 pt-1">
                        <div class="text-center py-12 text-slate-400 text-xs">
                            Enter your clinical inquiry or paper recollection above to find real, verified studies with zero URL hallucination.
                        </div>
                    </div>
                </div>
            </div>

            <!-- Sibling Container 2: Multi-Paper Summarizer Mode -->
            <div id="summarizerContainer" class="hidden w-full overflow-y-auto space-y-4" style="height: calc(100vh - 105px);">
                <div class="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-6 shadow-xs max-w-5xl mx-auto space-y-5 text-slate-800 dark:text-slate-100">
                    <!-- Header & Directive -->
                    <div class="border-b border-slate-100 dark:border-slate-800 pb-4">
                        <div>
                            <h2 class="text-base font-bold text-slate-800 dark:text-slate-100 flex items-center gap-2">
                                <span>📝</span> Multi-Study Evidence Synthesis
                            </h2>
                            <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">
                                Paste 3–10 PubMed URLs, PMIDs, or DOIs. Synthesizes structured abstracts across multiple studies into a unified clinical briefing.
                            </p>
                        </div>
                    </div>

                    <!-- Batch URLs Input -->
                    <div class="space-y-2">
                        <div class="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 font-medium">
                            <span>Enter PubMed URLs, PMIDs, or DOIs (one per line):</span>
                            <div class="flex items-center gap-3">
                                <button onclick="clearSummarizerInput()" class="text-rose-600 hover:text-rose-700 font-semibold text-[11px]">Clear All</button>
                            </div>
                        </div>
                        <textarea 
                            id="summarizerUrlsInput" 
                            rows="5" 
                            placeholder="https://pubmed.ncbi.nlm.nih.gov/23843810/&#10;https://pubmed.ncbi.nlm.nih.gov/30302302/&#10;29188837"
                            class="w-full text-xs font-mono bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg p-3 text-slate-800 dark:text-slate-100 focus:bg-white focus:dark:bg-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500 transition shadow-2xs leading-relaxed"
                            oninput="updateSummarizerBatchCount()"
                        ></textarea>
                        <div class="flex items-center justify-between pt-1">
                            <span id="summarizerBatchCounter" class="text-[11px] text-slate-400">Batch size: 0 / 10 papers</span>
                            <button 
                                id="summarizerSubmitBtn" 
                                onclick="executeSummarizerBatch()" 
                                class="btn-primary-accent text-white font-semibold text-xs px-5 py-2.5 rounded-lg transition shadow-xs flex items-center gap-2 cursor-pointer"
                            >
                                <span id="summarizerBtnIcon">🚀</span>
                                <span id="summarizerBtnText">Generate Science Briefing</span>
                            </button>
                        </div>
                    </div>

                    <!-- Summarizer Status Banner -->
                    <div id="summarizerStatusBanner" class="hidden rounded-lg p-3 text-xs flex items-center justify-between border"></div>

                    <!-- Generated Science Summary Output -->
                    <div id="summarizerOutputContainer" class="hidden space-y-4 pt-1">
                        <div class="bg-slate-50 dark:bg-slate-950/50 rounded-xl border border-slate-200 dark:border-slate-800 p-5 space-y-4">
                            <div class="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-3">
                                <div class="flex items-center gap-2">
                                    <span class="text-sm font-bold text-slate-800 dark:text-slate-100">📄 Synthesized Briefing Document</span>
                                    <span id="summarizerMetaBadge" class="text-[11px] bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded font-mono"></span>
                                </div>
                                <div class="flex items-center gap-2">
                                    <button onclick="copySummarizerMarkdown()" id="copySummaryBtn" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white dark:bg-slate-850 border border-slate-300 dark:border-slate-700 hover:border-slate-400 dark:hover:border-slate-600 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white text-xs font-medium transition shadow-2xs cursor-pointer">
                                        <span>📋</span> <span id="copySummaryBtnText">Copy to Clipboard</span>
                                    </button>
                                </div>
                            </div>
                            <!-- Rendered Markdown Content -->
                            <div id="summarizerRenderedContent" class="text-xs leading-relaxed space-y-4 text-slate-800 dark:text-slate-200"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Results Section: Split Screen -->
            <div id="resultBox" class="hidden">
                <!-- Draggable Split Container: Left Appraisal | Resizer | Right Source Inspector -->
                <div id="splitContainer" class="flex flex-row w-full gap-0 select-none items-stretch rounded-lg border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden bg-white dark:bg-slate-900" style="height: calc(100vh - 105px); min-height: 650px;">
                    <!-- Left: Clinical Analysis & Show Thinking Tab Switcher (Behavior 3) -->
                    <div id="leftPane" class="bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 select-text flex flex-col h-full overflow-hidden" style="width: 55%; min-width: 25%; max-width: 75%;">
                        <!-- Fixed Header Bar: Tabs & Action Buttons (never scrolled or overlapped) -->
                        <div class="flex-shrink-0 bg-white dark:bg-slate-900 z-10 px-6 pt-5 pb-3 border-b border-slate-200 dark:border-slate-800 flex flex-wrap justify-between items-center gap-2">
                            <div class="flex items-center gap-2">
                                <div class="flex bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-medium">
                                    <button id="leftTabAppraisalBtn" onclick="switchLeftTab('appraisal')" class="px-3 py-1 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-semibold transition flex items-center gap-1.5 cursor-pointer">
                                        <span>📄</span> <span>Clinical Analysis</span>
                                    </button>
                                    <button id="leftTabAskBtn" onclick="switchLeftTab('ask')" class="px-3 py-1 rounded-md text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition flex items-center gap-1.5 cursor-pointer">
                                        <span>💬</span> <span>Ask</span>
                                    </button>
                                    <button id="leftTabThinkingBtn" onclick="switchLeftTab('thinking')" class="px-3 py-1 rounded-md text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition flex items-center gap-1.5 cursor-pointer">
                                        <span>🧠</span> <span>Show Thinking / Audit</span>
                                    </button>
                                    <button id="leftTabCommentaryBtn" onclick="switchLeftTab('commentary')" class="px-3 py-1 rounded-md text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition flex items-center gap-1.5 cursor-pointer">
                                        <span>✍️</span> <span>Commentary &amp; QC</span>
                                    </button>
                                </div>
                            </div>
                            <div class="flex items-center gap-2">
                                <span id="leftPaneHint" class="text-xs text-slate-400 italic hidden lg:inline">Click any pill to inspect</span>
                                
                                <!-- Consolidated Export & Copy Dropdown -->
                                <div class="relative inline-block text-left" id="exportDropdownWrapper">
                                    <button type="button" onclick="toggleExportMenu(event)" id="exportMenuBtn" class="flex items-center gap-1.5 px-3 py-1 rounded-md bg-white dark:bg-slate-850 border border-slate-300 dark:border-slate-700 hover:border-slate-400 dark:hover:border-slate-600 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white text-xs font-semibold transition shadow-2xs cursor-pointer">
                                        <span>📤</span>
                                        <span id="exportMenuBtnText">Export / Copy</span>
                                        <svg class="w-3.5 h-3.5 ml-0.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                                    </button>
                                    
                                    <div id="exportMenuDropdown" class="hidden absolute right-0 mt-1.5 w-72 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl z-50 text-xs py-2 divide-y divide-slate-100 dark:divide-slate-800 animate-in fade-in zoom-in-95 duration-100">
                                        <!-- WordPress Formats -->
                                        <div class="p-1.5 space-y-0.5">
                                            <div class="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-400 flex items-center gap-1">
                                                <span>🌐</span> <span>WordPress Formats</span>
                                            </div>
                                            <button type="button" onclick="handleExportAction('wp_visual')" class="w-full text-left px-2.5 py-2 rounded-lg hover:bg-indigo-50 dark:hover:bg-indigo-950/40 text-slate-800 dark:text-slate-200 flex items-start gap-2.5 transition cursor-pointer">
                                                <span class="text-base leading-none">✨</span>
                                                <div class="flex-1">
                                                    <div class="font-bold text-slate-900 dark:text-slate-100 flex items-center justify-between">
                                                        <span>Copy for WordPress (Visual)</span>
                                                        <span class="text-[9px] px-1.5 py-0.2 rounded bg-indigo-100 text-indigo-800 font-bold">Recommended</span>
                                                    </div>
                                                    <div class="text-[11px] text-slate-500 dark:text-slate-400 leading-snug mt-0.5">Paste directly into Gutenberg. Preserves purple headers &amp; blue coordinate badge pills.</div>
                                                </div>
                                            </button>
                                            <button type="button" onclick="handleExportAction('wp_html')" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 flex items-start gap-2.5 transition cursor-pointer">
                                                <span class="text-base leading-none">🏷️</span>
                                                <div class="flex-1">
                                                    <div class="font-bold text-slate-900 dark:text-slate-100">Copy WordPress HTML Code</div>
                                                    <div class="text-[11px] text-slate-500 dark:text-slate-400 leading-snug">Formatted HTML for WordPress Custom HTML block.</div>
                                                </div>
                                            </button>
                                            <button type="button" onclick="handleExportAction('wp_download')" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 flex items-center gap-2.5 transition cursor-pointer">
                                                <span class="text-base leading-none">⬇️</span>
                                                <span class="font-medium">Download WordPress HTML (.html)</span>
                                            </button>
                                        </div>

                                        <!-- Markdown & Plain Text -->
                                        <div class="p-1.5 space-y-0.5">
                                            <div class="px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 flex items-center gap-1">
                                                <span>📋</span> <span>Markdown &amp; Text</span>
                                            </div>
                                            <button type="button" onclick="handleExportAction('copy_markdown')" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 flex items-center gap-2.5 transition cursor-pointer">
                                                <span class="text-base leading-none">📋</span>
                                                <span class="font-semibold text-slate-900 dark:text-slate-100">Copy Clean Markdown</span>
                                            </button>
                                            <button type="button" onclick="handleExportAction('copy_text')" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 flex items-center gap-2.5 transition cursor-pointer">
                                                <span class="text-base leading-none">📄</span>
                                                <span class="font-medium">Copy Plain Text</span>
                                            </button>
                                            <button type="button" onclick="handleExportAction('download_markdown')" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 flex items-center gap-2.5 transition cursor-pointer">
                                                <span class="text-base leading-none">⬇️</span>
                                                <span class="font-medium">Download Markdown (.md)</span>
                                            </button>
                                        </div>

                                        <!-- Optional Commentary Inclusion -->
                                        <div class="p-2.5 bg-slate-50 dark:bg-slate-950/60 rounded-b-xl border-t border-slate-100 dark:border-slate-800">
                                            <label class="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 cursor-pointer select-none">
                                                <input type="checkbox" id="exportIncludeCommentary" class="rounded text-sky-600 focus:ring-sky-500 cursor-pointer"/>
                                                <span class="font-medium">Include Clinician Commentary</span>
                                            </label>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Scrollable Body Content -->
                        <div class="flex-1 overflow-y-auto p-6 min-h-0 flex flex-col">
                            <div id="outputMarkdown" class="prose max-w-none text-slate-800 dark:text-slate-200 bg-slate-50 dark:bg-slate-950/70 p-6 rounded-lg border border-slate-200 dark:border-slate-800 text-sm leading-relaxed flex-1"></div>
                            <!-- Ask Tab Container (Conversational QA Interrogation) -->
                            <div id="askContainer" class="hidden flex-1 flex flex-col min-h-0 space-y-3">
                                <!-- Quick Clinical Inquiries -->
                                <div class="flex-shrink-0 bg-slate-50 dark:bg-slate-950/70 p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 space-y-1.5">
                                    <span class="text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 block">Quick Inquiries:</span>
                                    <div class="flex flex-wrap gap-1.5">
                                        <button onclick="askQuickChip('How many total participants were randomized or enrolled in the study?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">👥 Total Sample Size</button>
                                        <button onclick="askQuickChip('What was the primary endpoint, and was it statistically significant?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">🎯 Primary Endpoint</button>
                                        <button onclick="askQuickChip('Does the study report Overall Survival (OS) or MACE outcomes? What were the hazard ratios?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">📈 Survival / MACE</button>
                                        <button onclick="askQuickChip('What adverse events or safety signals were significantly different between groups?')" class="text-[11px] bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 hover:border-sky-300 px-2.5 py-1 rounded-md shadow-2xs transition font-medium cursor-pointer">⚠️ Safety & Harms</button>
                                    </div>
                                </div>

                                <!-- Chat Message History Feed -->
                                <div id="askChatFeed" class="flex-1 bg-slate-50 dark:bg-slate-950/70 p-4 rounded-lg border border-slate-200 dark:border-slate-800 overflow-y-auto space-y-4 text-xs leading-relaxed min-h-[300px]">
                                    <div class="text-center p-6 text-slate-400 my-auto">
                                        <span class="text-2xl block mb-1">💬</span>
                                        <p class="font-semibold text-slate-600 dark:text-slate-400 text-xs">Ask anything about this manuscript</p>
                                        <p class="text-[11px] text-slate-400 dark:text-slate-500 mt-1 max-w-sm mx-auto">Answers cite coordinate anchors that jump directly to the source paragraph in the viewer on the right.</p>
                                    </div>
                                </div>

                                <!-- Question Input Box -->
                                <div class="flex-shrink-0 flex gap-2 pt-1">
                                    <input type="text" id="askQuestionInput" onkeydown="if(event.key==='Enter') executeAskQuery();" placeholder="Ask a question about this paper (e.g. 'What was the blinding method?')..." class="flex-1 text-xs text-slate-800 dark:text-slate-100 bg-white dark:bg-slate-900 px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-2xs"/>
                                    <button id="askSubmitBtn" onclick="executeAskQuery()" class="btn-primary-accent px-4 py-2 text-white font-semibold text-xs rounded-lg transition shadow-2xs flex items-center gap-1.5 cursor-pointer shrink-0">
                                        <span>Send</span> <span>➤</span>
                                    </button>
                                </div>
                            </div>
                            <div id="thinkingContainer" class="hidden flex-1 space-y-4"></div>

                            <!-- Commentary & Adversarial QC Tab Container -->
                            <div id="commentaryContainer" class="hidden flex-1 flex flex-col min-h-0 space-y-4">
                                <!-- Commentary Header Toolbar -->
                                <div class="flex-shrink-0 bg-slate-50 dark:bg-slate-950/70 p-3 rounded-lg border border-slate-200 dark:border-slate-800 flex flex-wrap items-center justify-between gap-2">
                                    <div class="flex items-center gap-2">
                                        <span class="text-sm font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                                            <span>✍️</span> <span>Clinician Editorial Commentary</span>
                                        </span>
                                        <span id="commentaryVoiceBadge" class="text-[11px] font-mono px-2 py-0.5 rounded bg-sky-50 dark:bg-sky-950 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800">Voice Calibrated</span>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <button onclick="openSettingsModal('voice')" class="text-xs text-sky-600 hover:text-sky-800 dark:text-sky-400 dark:hover:text-sky-300 font-medium transition cursor-pointer flex items-center gap-1">
                                            <span>⚙️</span> <span>Calibrate Voice</span>
                                        </button>
                                        <button id="generateCommentaryBtn" onclick="generateClinicalCommentary()" class="btn-primary-accent text-white font-semibold text-xs px-3.5 py-1.5 rounded-md transition shadow-2xs flex items-center gap-1.5 cursor-pointer">
                                            <span>✨</span> <span id="generateCommentaryBtnText">Generate Commentary</span>
                                        </button>
                                    </div>
                                </div>

                                <!-- Editable Draft Commentary Panel -->
                                <div class="flex flex-col bg-slate-50 dark:bg-slate-950/70 p-4 rounded-lg border border-slate-200 dark:border-slate-800 space-y-2.5">
                                    <div class="flex items-center justify-between text-xs border-b border-slate-200 dark:border-slate-800 pb-2">
                                        <div class="flex items-center gap-2">
                                            <span class="font-bold text-slate-700 dark:text-slate-300">Draft Post (Editable)</span>
                                            <span class="text-[11px] text-slate-400 dark:text-slate-500 font-sans">Ready to copy for colleagues or newsletters</span>
                                        </div>
                                        <button onclick="copyCommentaryToClipboard()" id="copyCommentaryBtn" class="flex items-center gap-1 text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white px-2 py-1 rounded bg-white dark:bg-slate-850 border border-slate-200 dark:border-slate-700 shadow-2xs transition cursor-pointer">
                                            <span>📋</span> <span id="copyCommentaryBtnText">Copy Post</span>
                                        </button>
                                    </div>
                                    <textarea id="commentaryTextarea" oninput="updateCommentaryCharCount()" class="w-full min-h-[160px] text-xs sm:text-sm font-sans leading-relaxed text-slate-900 dark:text-slate-100 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg p-3 focus:outline-none focus:ring-1 focus:ring-sky-500 shadow-2xs resize-y" placeholder="Click 'Generate Commentary' above or write/paste your commentary here to run an adversarial audit..."></textarea>
                                    
                                    <div class="flex items-center justify-between pt-1">
                                        <span class="text-[11px] text-slate-400 font-mono" id="commentaryCharCount">0 characters</span>
                                        <button id="runQCAuditBtn" onclick="runSecondaryQCAudit()" class="px-3.5 py-1.5 rounded-md bg-white dark:bg-slate-850 hover:bg-sky-50 dark:hover:bg-slate-800 text-sky-700 dark:text-sky-300 border border-sky-300 dark:border-sky-700 font-semibold text-xs shadow-2xs transition flex items-center gap-1.5 cursor-pointer">
                                            <span>🛡️</span> <span id="runQCAuditBtnText">Run Adversarial QC Audit</span>
                                        </button>
                                    </div>
                                </div>

                                <!-- QC Audit Results Container -->
                                <div id="qcAuditSection" class="hidden flex-1 flex flex-col space-y-3">
                                    <div id="qcAuditHeaderCard" class="p-3.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/70 flex flex-wrap items-center justify-between gap-2">
                                        <div class="flex items-center gap-2">
                                            <span class="text-xs font-bold text-slate-800 dark:text-slate-100">Adversarial QC Audit</span>
                                            <span id="qcIntegrityBadge" class="px-2.5 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">Verified</span>
                                        </div>
                                        <span id="qcModelBadge" class="text-[11px] font-mono text-slate-500 dark:text-slate-400">Deterministic temp=0.0</span>
                                    </div>
                                    <p id="qcSummaryVerdict" class="text-xs text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-900 p-3 rounded-md border border-slate-200 dark:border-slate-800 leading-relaxed"></p>
                                    <div id="qcDesignCaveatBox" class="hidden p-3 rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/60 text-xs text-amber-950 dark:text-amber-200 leading-relaxed"></div>
                                    <div id="qcDiscrepanciesFeed" class="space-y-3"></div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Draggable Divider Bar -->
                    <div id="dragDivider" class="resizer" title="Drag left or right to resize panels"></div>

                    <!-- Right: Interactive Source Inspector -->
                    <div id="rightPane" class="bg-white dark:bg-slate-900 p-6 flex flex-col space-y-4 select-text h-full overflow-hidden" style="width: 45%; min-width: 25%; max-width: 75%;">
                        <div class="border-b border-slate-200 dark:border-slate-800 pb-3 flex justify-between items-center flex-shrink-0">
                            <div>
                                <h3 class="text-base font-semibold text-slate-800 dark:text-slate-100">Source Evidence Inspector</h3>
                                <p id="inspectSubtitle" class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Select any coordinate pill on the left</p>
                            </div>
                            <div class="flex items-center gap-2">
                                <span id="pageBadge" class="hidden px-2.5 py-1 text-xs font-semibold rounded bg-sky-100 dark:bg-sky-950 text-sky-800 dark:text-sky-300 border border-sky-200 dark:border-sky-800">Page -</span>
                            </div>
                        </div>

                        <!-- Snippet Text Box (Large Readable Typography) -->
                        <div id="snippetBox" class="hidden p-4 rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/60 text-sm text-amber-950 dark:text-amber-200 leading-relaxed shadow-xs flex-shrink-0 max-h-40 overflow-y-auto">
                            <span class="font-bold uppercase tracking-wider text-[11px] text-amber-800 dark:text-amber-400 block mb-1.5 flex items-center gap-1.5">
                                <span>📄 Exact Manuscript Text:</span>
                            </span>
                            <p id="snippetText" class="font-serif italic text-[14px] leading-relaxed text-amber-950 dark:text-amber-200"></p>
                        </div>

                        <!-- Full Paper Continuous Scroll Viewer -->
                        <div id="pageViewer" class="relative bg-slate-100 dark:bg-slate-950 rounded border border-slate-300 dark:border-slate-800 flex-1 min-h-0 overflow-y-auto p-3">
                            <div id="viewerPlaceholder" class="text-center p-8 text-slate-400 my-auto">
                                <svg class="w-12 h-12 mx-auto mb-2 text-slate-300 dark:text-slate-700" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                                <p class="text-sm">Manuscript pages will appear here for continuous full-paper reading.</p>
                            </div>
                            <div id="pagesStack" class="hidden flex flex-col items-center gap-4 w-full"></div>
                            <div id="highlightHitbox" style="display: none;" title="Hover over the highlighted section to pop it up in large print!"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Hover / Click Popup Modal for the Highlighted Section -->
        <div id="sectionPopup">
            <div id="popupHeader" class="bg-sky-700 text-white px-4 py-2 flex justify-between items-center text-xs font-semibold shadow-xs select-none" title="Click and drag to move pop-up">
                <div class="flex items-center gap-2 pointer-events-none">
                    <span class="inline-block w-2.5 h-2.5 rounded-full bg-amber-400"></span>
                    <span id="popupTitle" class="font-mono text-xs font-bold text-sky-100 bg-sky-900/60 px-2.5 py-1 rounded tracking-wide truncate max-w-[280px]">Highlighted Manuscript Section</span>
                    <span class="text-[11px] text-sky-300 font-normal ml-1">⋮⋮ Drag</span>
                </div>
                <div class="flex items-center gap-2">
                    <!-- Zoom Controls -->
                    <div class="flex items-center bg-sky-800/90 rounded border border-sky-600/60 overflow-hidden text-[11px]">
                        <button onclick="adjustPopupZoom(-0.15)" class="px-2 py-0.5 hover:bg-sky-600 font-bold transition" title="Smaller font (Zoom out)">−</button>
                        <span id="popupZoomLevel" onclick="resetPopupZoom()" class="px-2 py-0.5 font-mono text-sky-200 cursor-pointer hover:text-white" title="Click to reset zoom">100%</span>
                        <button onclick="adjustPopupZoom(0.15)" class="px-2 py-0.5 hover:bg-sky-600 font-bold transition" title="Larger font (Zoom in)">+</button>
                    </div>
                    <!-- Pin Button -->
                    <button id="popupPinBtn" onclick="togglePopupPin()" class="flex items-center gap-1 px-2.5 py-1 rounded bg-sky-800/90 hover:bg-sky-600 text-sky-100 hover:text-white text-[11px] font-medium transition border border-sky-600/60" title="Pin / Lock popup open">
                        <span>📌</span> <span id="pinBtnText">Pin</span>
                    </button>
                    <!-- Close Button -->
                    <button onclick="closeSectionPopup()" class="text-white/80 hover:text-white px-2 py-0.5 rounded hover:bg-rose-600 transition text-sm font-bold ml-1" title="Close (or press Esc)">✕</button>
                </div>
            </div>
            <div id="popupScrollContainer" class="p-4 bg-slate-100/70 dark:bg-slate-900/80 overflow-y-auto overflow-x-auto flex flex-col items-center gap-3 flex-1 min-h-0 w-full" style="max-height: calc(100vh - 90px);">
                <img id="popupCropImg" class="rounded border border-slate-200 dark:border-slate-800 shadow-sm bg-white" style="max-width: 100%; height: auto; object-fit: contain; transition: width 0.12s ease;" alt="Manuscript Section Crop"/>
                <div id="popupTranscriptBox" class="w-full bg-white dark:bg-slate-950 p-3 rounded-md border border-slate-200 dark:border-slate-800 shadow-2xs text-left hidden">
                    <div class="flex items-center justify-between mb-1 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                        <span>Extracted Text</span>
                        <span id="popupPageInfo" class="font-mono text-sky-700 dark:text-sky-400"></span>
                    </div>
                    <p id="popupTranscriptText" class="text-xs text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap select-text"></p>
                </div>
            </div>

            <!-- Modal Resize Handles -->
            <div class="popup-resizer edge-r" data-resize="r" title="Drag to resize width"></div>
            <div class="popup-resizer edge-b" data-resize="b" title="Drag to resize height"></div>
            <div class="popup-resizer edge-l" data-resize="l" title="Drag to resize width"></div>
            <div class="popup-resizer edge-t" data-resize="t" title="Drag to resize height"></div>
            <div class="popup-resizer corner-br group" data-resize="br" title="Click and drag to resize pop-up">
                <svg class="w-3.5 h-3.5 text-slate-400 group-hover:text-sky-600 transition pointer-events-none" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M14 14H12V12H14V14ZM14 10H12V8H14V10ZM10 14H8V12H10V14ZM14 6H12V4H14V6ZM6 14H4V12H6V14ZM10 10H8V8H10V10Z"/>
                </svg>
            </div>
            <div class="popup-resizer corner-bl" data-resize="bl" title="Drag to resize"></div>
            <div class="popup-resizer corner-tr" data-resize="tr" title="Drag to resize"></div>
            <div class="popup-resizer corner-tl" data-resize="tl" title="Drag to resize"></div>
        </div>

        <script>
            // --- Firebase Auth & Token Governance Client State ---
            const MASTER_ADMIN_EMAIL = 'drbiernd@gmail.com';
            let fbApp = null;
            let fbAuth = null;
            let fbDb = null;
            let currentUser = null;
            let isApproved = false;
            let isAdmin = false;
            let authMode = 'signin'; // 'signin' | 'signup' | 'forgot'
            let adminUsersList = [];
            let adminUsageStats = {};
            let currentAdminTab = 'pending'; // 'pending' | 'approved' | 'denied-revoked'
            let pendingListenerUnsub = null;
            let userDocListenerUnsub = null;

            const FALLBACK_FIREBASE_CONFIG = {
                apiKey: "AIzaSyD5p8zLS4Wbx36ShxdgqdBOiHE-t3JTHsQ",
                authDomain: "fact-wonk.firebaseapp.com",
                projectId: "fact-wonk",
                storageBucket: "fact-wonk.firebasestorage.app",
                messagingSenderId: "624524249455",
                appId: "1:624524249455:web:7ebb30a4179afd512d009a",
                measurementId: "G-SDB2HK4SPF"
            };

            async function initFirebaseAuth() {
                try {
                    let config = FALLBACK_FIREBASE_CONFIG;
                    try {
                        const r = await fetch('/firebase-applet-config.json');
                        if (r.ok) {
                            const c = await r.json();
                            if (c && c.apiKey) config = c;
                        }
                    } catch (e) {
                        // fallback used
                    }

                    if (window.firebase) {
                        if (!firebase.apps.length) {
                            fbApp = firebase.initializeApp(config);
                        } else {
                            fbApp = firebase.app();
                        }
                        fbAuth = firebase.auth();
                        fbDb = firebase.firestore();

                        fbAuth.onAuthStateChanged(handleAuthStateChanged);
                    } else {
                        console.warn("Firebase SDK not loaded yet.");
                    }
                } catch (err) {
                    console.error("Firebase initialization failed:", err);
                }
            }

            async function handleAuthStateChanged(user) {
                if (userDocListenerUnsub) {
                    userDocListenerUnsub();
                    userDocListenerUnsub = null;
                }
                if (pendingListenerUnsub) {
                    pendingListenerUnsub();
                    pendingListenerUnsub = null;
                }

                currentUser = user;
                const signInHeaderBtn = document.getElementById('signInHeaderBtn');
                const userProfileHeader = document.getElementById('userProfileHeader');
                const adminUserMgmtBtn = document.getElementById('adminUserMgmtBtn');
                const userProfilePill = document.getElementById('userProfilePill');
                const userAvatarImg = document.getElementById('userAvatarImg');
                const userAvatarCircle = document.getElementById('userAvatarCircle');
                const userTooltipName = document.getElementById('userTooltipName');
                const userTooltipEmail = document.getElementById('userTooltipEmail');
                const pendingApprovalModal = document.getElementById('pendingApprovalModal');

                if (!user) {
                    isApproved = false;
                    isAdmin = false;
                    if (signInHeaderBtn) signInHeaderBtn.classList.remove('hidden');
                    if (userProfileHeader) userProfileHeader.classList.add('hidden');
                    if (adminUserMgmtBtn) adminUserMgmtBtn.classList.add('hidden');
                    if (pendingApprovalModal) pendingApprovalModal.classList.add('hidden');
                    return;
                }

                // Authenticated
                if (signInHeaderBtn) signInHeaderBtn.classList.add('hidden');
                if (userProfileHeader) userProfileHeader.classList.remove('hidden');
                
                const emailStr = user.email || 'Clinician';
                const nameStr = user.displayName || '';
                const photoStr = user.photoURL || '';

                if (userProfilePill) {
                    userProfilePill.setAttribute('title', nameStr ? `${nameStr} (${emailStr})` : emailStr);
                }
                if (userTooltipEmail) userTooltipEmail.innerText = emailStr;
                if (userTooltipName) {
                    if (nameStr) {
                        userTooltipName.innerText = nameStr;
                        userTooltipName.classList.remove('hidden');
                    } else {
                        userTooltipName.innerText = '';
                        userTooltipName.classList.add('hidden');
                    }
                }

                if (photoStr && userAvatarImg && userAvatarCircle) {
                    userAvatarImg.src = photoStr;
                    userAvatarImg.classList.remove('hidden');
                    userAvatarCircle.classList.add('hidden');
                } else if (userAvatarCircle) {
                    const initial = (emailStr || 'U').charAt(0).toUpperCase();
                    userAvatarCircle.innerText = initial;
                    userAvatarCircle.classList.remove('hidden');
                    if (userAvatarImg) userAvatarImg.classList.add('hidden');
                }

                const emailLower = (user.email || '').toLowerCase().trim();
                const isMasterAdmin = emailLower === MASTER_ADMIN_EMAIL.toLowerCase();

                if (isMasterAdmin) {
                    isAdmin = true;
                    isApproved = true;
                    if (adminUserMgmtBtn) adminUserMgmtBtn.classList.remove('hidden');
                    if (pendingApprovalModal) pendingApprovalModal.classList.add('hidden');
                    closeAuthModal();

                    try {
                        await fbDb.collection('users').doc(user.uid).set({
                            uid: user.uid,
                            email: user.email,
                            displayName: user.displayName || '',
                            photoURL: user.photoURL || '',
                            approved: true,
                            status: 'approved',
                            role: 'admin',
                            lastLoginAt: new Date().toISOString()
                        }, { merge: true });
                    } catch (e) {
                        console.warn("Admin record sync:", e);
                    }

                    setupPendingUsersListener();
                    syncVoiceProfileWithFirestore(user.uid);
                    return;
                }

                // Standard user: check preapproved whitelist first
                let preapproved = false;
                try {
                    const preDoc = await fbDb.collection('preapproved_emails').doc(emailLower).get();
                    if (preDoc.exists && preDoc.data() && preDoc.data().approved) {
                        preapproved = true;
                    }
                } catch (pe) {
                    console.warn("Preapproval check:", pe);
                }

                if (preapproved) {
                    isApproved = true;
                    isAdmin = false;
                    if (adminUserMgmtBtn) adminUserMgmtBtn.classList.add('hidden');
                    if (pendingApprovalModal) pendingApprovalModal.classList.add('hidden');
                    closeAuthModal();

                    try {
                        await fbDb.collection('users').doc(user.uid).set({
                            uid: user.uid,
                            email: user.email,
                            displayName: user.displayName || '',
                            photoURL: user.photoURL || '',
                            approved: true,
                            status: 'approved',
                            role: 'user',
                            lastLoginAt: new Date().toISOString()
                        }, { merge: true });
                    } catch (e) {
                        console.warn("Preapproved user sync:", e);
                    }
                    syncVoiceProfileWithFirestore(user.uid);
                    return;
                }

                // Standard user: sync and attach reactive onSnapshot listener
                try {
                    const userDocRef = fbDb.collection('users').doc(user.uid);
                    const docSnap = await userDocRef.get();
                    if (!docSnap.exists) {
                        await userDocRef.set({
                            uid: user.uid,
                            email: user.email,
                            displayName: user.displayName || '',
                            photoURL: user.photoURL || '',
                            approved: false,
                            status: 'pending',
                            role: 'user',
                            createdAt: new Date().toISOString()
                        });
                    } else {
                        await userDocRef.set({
                            displayName: user.displayName || '',
                            photoURL: user.photoURL || '',
                            lastLoginAt: new Date().toISOString()
                        }, { merge: true });
                    }

                    userDocListenerUnsub = userDocRef.onSnapshot((snapshot) => {
                        const data = snapshot.data();
                        const approved = Boolean(data && data.approved);
                        const status = (data && data.status) ? data.status : (approved ? 'approved' : 'pending');
                        isApproved = approved;

                        if (isApproved) {
                            if (pendingApprovalModal) pendingApprovalModal.classList.add('hidden');
                            closeAuthModal();
                            syncVoiceProfileWithFirestore(user.uid);
                        } else {
                            if (pendingApprovalModal) {
                                pendingApprovalModal.classList.remove('hidden');
                                const emailEl = document.getElementById('pendingModalUserEmail');
                                const msgEl = document.getElementById('pendingModalMessage');
                                if (emailEl) emailEl.innerText = `Signed in as ${user.email}`;
                                if (msgEl) {
                                    if (status === 'denied' || status === 'revoked') {
                                        msgEl.innerText = 'Your access to F.A.C.T. has been denied or revoked by the system administrator. Please contact drbiernd@gmail.com for access reinstatement.';
                                    } else {
                                        msgEl.innerText = 'Your account has been registered in the F.A.C.T. clinician registry. An administrator must approve your account before you can analyze manuscripts or run precision searches.';
                                    }
                                }
                            }
                        }
                    });
                } catch (ue) {
                    console.error("User listener attachment failed:", ue);
                }
            }

            function setupPendingUsersListener() {
                if (!fbDb || !isAdmin) return;
                try {
                    pendingListenerUnsub = fbDb.collection('users').onSnapshot((snapshot) => {
                        let pendingCount = 0;
                        snapshot.forEach((doc) => {
                            const data = doc.data();
                            const email = (data.email || '').toLowerCase();
                            if (email === MASTER_ADMIN_EMAIL.toLowerCase()) return;
                            const isApp = Boolean(data.approved);
                            const st = data.status || (isApp ? 'approved' : 'pending');
                            if (!isApp && st !== 'denied' && st !== 'revoked') {
                                pendingCount++;
                            }
                        });

                        const badge = document.getElementById('adminPendingBadge');
                        const countText = document.getElementById('adminPendingCountText');
                        const tabPendingCount = document.getElementById('adminTabPendingCount');
                        if (badge && countText) {
                            if (pendingCount > 0) {
                                badge.classList.remove('hidden');
                                countText.innerText = pendingCount;
                            } else {
                                badge.classList.add('hidden');
                            }
                        }
                        if (tabPendingCount) tabPendingCount.innerText = pendingCount;
                    });
                } catch (e) {
                    console.warn("Failed to attach pending listener:", e);
                }
            }

            function openAuthModal() {
                const m = document.getElementById('authModal');
                const errBox = document.getElementById('authErrorBox');
                const succBox = document.getElementById('authSuccessBox');
                if (errBox) errBox.classList.add('hidden');
                if (succBox) succBox.classList.add('hidden');
                if (m) m.classList.remove('hidden');
            }

            function closeAuthModal() {
                const m = document.getElementById('authModal');
                if (m) m.classList.add('hidden');
            }

            function toggleAuthMode() {
                const title = document.getElementById('authModalTitle');
                const submitText = document.getElementById('authSubmitText');
                const toggleBtn = document.getElementById('authToggleModeBtn');
                const pwdGroup = document.getElementById('passwordFieldGroup');
                const forgotBtn = document.getElementById('authForgotBtn');

                if (authMode === 'signin') {
                    authMode = 'signup';
                    if (title) title.innerText = 'Create your F.A.C.T. account';
                    if (submitText) submitText.innerText = 'Create Account';
                    if (toggleBtn) toggleBtn.innerText = 'Already have an account? Sign in';
                    if (pwdGroup) pwdGroup.classList.remove('hidden');
                    if (forgotBtn) forgotBtn.classList.add('hidden');
                } else {
                    authMode = 'signin';
                    if (title) title.innerText = 'Sign in to F.A.C.T.';
                    if (submitText) submitText.innerText = 'Sign In';
                    if (toggleBtn) toggleBtn.innerText = 'Need an account? Create one';
                    if (pwdGroup) pwdGroup.classList.remove('hidden');
                    if (forgotBtn) forgotBtn.classList.remove('hidden');
                }
            }

            function toggleForgotMode() {
                authMode = 'forgot';
                const title = document.getElementById('authModalTitle');
                const submitText = document.getElementById('authSubmitText');
                const toggleBtn = document.getElementById('authToggleModeBtn');
                const pwdGroup = document.getElementById('passwordFieldGroup');
                const forgotBtn = document.getElementById('authForgotBtn');

                if (title) title.innerText = 'Reset your password';
                if (submitText) submitText.innerText = 'Send Reset Email';
                if (toggleBtn) toggleBtn.innerText = 'Back to Sign In';
                if (pwdGroup) pwdGroup.classList.add('hidden');
                if (forgotBtn) forgotBtn.classList.add('hidden');
            }

            async function handleGoogleSignIn() {
                const errBox = document.getElementById('authErrorBox');
                if (errBox) errBox.classList.add('hidden');
                try {
                    const provider = new firebase.auth.GoogleAuthProvider();
                    provider.setCustomParameters({ prompt: 'select_account' });
                    await fbAuth.signInWithPopup(provider);
                    closeAuthModal();
                } catch (err) {
                    console.error("Google sign in error:", err);
                    if (errBox) {
                        errBox.innerText = err.message || 'Google Sign-In failed.';
                        errBox.classList.remove('hidden');
                    }
                }
            }

            async function handleEmailAuth(e) {
                e.preventDefault();
                const emailInput = document.getElementById('authEmailInput');
                const pwdInput = document.getElementById('authPasswordInput');
                const errBox = document.getElementById('authErrorBox');
                const succBox = document.getElementById('authSuccessBox');
                if (errBox) errBox.classList.add('hidden');
                if (succBox) succBox.classList.add('hidden');

                const email = emailInput ? emailInput.value.trim() : '';
                const pwd = pwdInput ? pwdInput.value : '';

                try {
                    if (authMode === 'signin') {
                        await fbAuth.signInWithEmailAndPassword(email, pwd);
                        closeAuthModal();
                    } else if (authMode === 'signup') {
                        await fbAuth.createUserWithEmailAndPassword(email, pwd);
                        closeAuthModal();
                    } else if (authMode === 'forgot') {
                        await fbAuth.sendPasswordResetEmail(email);
                        if (succBox) {
                            succBox.innerText = `Password reset link sent to ${email}. Check your inbox.`;
                            succBox.classList.remove('hidden');
                        }
                    }
                } catch (err) {
                    console.error("Email auth error:", err);
                    if (errBox) {
                        errBox.innerText = err.message || 'Authentication failed.';
                        errBox.classList.remove('hidden');
                    }
                }
            }

            async function handleSignOut() {
                try {
                    if (fbAuth) await fbAuth.signOut();
                } catch (err) {
                    console.error("Sign out error:", err);
                }
            }

            async function checkUserStatusManual() {
                if (currentUser && fbDb) {
                    try {
                        const snap = await fbDb.collection('users').doc(currentUser.uid).get();
                        if (snap.exists && snap.data() && snap.data().approved) {
                            isApproved = true;
                            const pendingModal = document.getElementById('pendingApprovalModal');
                            if (pendingModal) pendingModal.classList.add('hidden');
                        } else {
                            alert('Account is still pending administrator approval.');
                        }
                    } catch (e) {
                        alert('Could not verify status: ' + e.message);
                    }
                }
            }

            // --- Admin Governance & LLM Token Telemetry Modal ---
            async function openUserManagementModal() {
                if (!isAdmin) {
                    alert('Access restricted to Master Administrator (drbiernd@gmail.com).');
                    return;
                }
                const modal = document.getElementById('userManagementModal');
                if (modal) modal.classList.remove('hidden');

                // 1. Fetch live aggregated usage telemetry from SQLite
                try {
                    const usageRes = await fetch('/api/admin/usage');
                    if (usageRes.ok) {
                        const usageData = await usageRes.json();
                        if (usageData && usageData.success && Array.isArray(usageData.usage)) {
                            const map = {};
                            usageData.usage.forEach(u => {
                                if (u.uid) map[u.uid] = u;
                                if (u.email) map[u.email.toLowerCase()] = u;
                            });
                            adminUsageStats = map;
                        }
                    }
                } catch (ue) {
                    console.warn("Telemetry fetch error:", ue);
                }

                // 2. Fetch users from Firestore
                loadAdminUserList();
            }

            function closeUserManagementModal() {
                const modal = document.getElementById('userManagementModal');
                if (modal) modal.classList.add('hidden');
            }

            function switchAdminTab(tab) {
                currentAdminTab = tab;
                const tabPending = document.getElementById('adminTabPending');
                const tabApproved = document.getElementById('adminTabApproved');
                const tabDenied = document.getElementById('adminTabDenied');

                if (tabPending) tabPending.className = tab === 'pending' ?
                    "px-3 py-1.5 rounded-lg bg-sky-100 text-sky-800 font-bold transition flex items-center gap-1.5" :
                    "px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition flex items-center gap-1.5";
                if (tabApproved) tabApproved.className = tab === 'approved' ?
                    "px-3 py-1.5 rounded-lg bg-emerald-100 text-emerald-900 font-bold transition flex items-center gap-1.5" :
                    "px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition flex items-center gap-1.5";
                if (tabDenied) tabDenied.className = tab === 'denied-revoked' ?
                    "px-3 py-1.5 rounded-lg bg-slate-200 text-slate-900 font-bold transition flex items-center gap-1.5" :
                    "px-3 py-1.5 rounded-lg text-slate-600 hover:bg-slate-100 transition flex items-center gap-1.5";

                renderAdminUserList();
            }

            function filterAdminUserList() {
                const searchInput = document.getElementById('adminSearchInput');
                const q = (searchInput ? searchInput.value : '').toLowerCase().trim();
                renderAdminUserList(q);
            }

            async function loadAdminUserList() {
                const container = document.getElementById('adminUserListContainer');
                if (!fbDb) return;
                try {
                    const [usersSnap, preSnap] = await Promise.all([
                        fbDb.collection('users').get(),
                        fbDb.collection('preapproved_emails').get().catch(err => {
                            console.warn("Could not fetch preapproved_emails:", err);
                            return { forEach: () => {} };
                        })
                    ]);

                    const list = [];
                    const seenEmails = new Set();

                    usersSnap.forEach(doc => {
                        const d = doc.data();
                        const email = (d.email || '').toLowerCase().trim();
                        if (email) seenEmails.add(email);
                        list.push({
                            uid: doc.id,
                            email: d.email || 'No Email',
                            displayName: d.displayName || '',
                            photoURL: d.photoURL || '',
                            approved: Boolean(d.approved),
                            status: d.status || (Boolean(d.approved) ? 'approved' : 'pending'),
                            role: d.role || 'user',
                            createdAt: d.createdAt,
                            lastLoginAt: d.lastLoginAt,
                            isPreapprovedOnly: false
                        });
                    });

                    preSnap.forEach(doc => {
                        const d = doc.data();
                        const email = (d.email || doc.id || '').toLowerCase().trim();
                        if (!email) return;
                        if (seenEmails.has(email)) return; // Already present in registered users list

                        const isApproved = d.approved !== false;
                        list.push({
                            uid: `preapproved:${email}`,
                            email: d.email || doc.id,
                            displayName: '',
                            photoURL: '',
                            approved: isApproved,
                            status: isApproved ? 'approved' : (d.status || 'revoked'),
                            role: 'user',
                            createdAt: d.preapprovedAt || d.updatedAt || new Date().toISOString(),
                            lastLoginAt: null,
                            isPreapprovedOnly: true
                        });
                    });

                    adminUsersList = list;
                    updateAdminTabCounts();
                    renderAdminUserList();
                } catch (e) {
                    if (container) container.innerHTML = `<div class="text-rose-600 text-xs p-4 bg-rose-50 rounded-lg">Error loading registry: ${e.message}</div>`;
                }
            }

            function updateAdminTabCounts() {
                let pending = 0;
                let approved = 0;
                let denied = 0;
                adminUsersList.forEach(u => {
                    const email = (u.email || '').toLowerCase();
                    if (email === MASTER_ADMIN_EMAIL.toLowerCase()) return;
                    if (u.approved) {
                        approved++;
                    } else if (u.status === 'denied' || u.status === 'revoked') {
                        denied++;
                    } else {
                        pending++;
                    }
                });

                const pEl = document.getElementById('adminTabPendingCount');
                const aEl = document.getElementById('adminTabApprovedCount');
                const dEl = document.getElementById('adminTabDeniedCount');
                if (pEl) pEl.innerText = pending;
                if (aEl) aEl.innerText = approved;
                if (dEl) dEl.innerText = denied;
            }

            function renderAdminUserList(queryOverride) {
                const container = document.getElementById('adminUserListContainer');
                if (!container) return;

                const searchInput = document.getElementById('adminSearchInput');
                const q = queryOverride !== undefined ? queryOverride : (searchInput ? searchInput.value : '').toLowerCase().trim();

                let filtered = adminUsersList.filter(u => {
                    const email = (u.email || '').toLowerCase();
                    if (email === MASTER_ADMIN_EMAIL.toLowerCase()) return false;
                    if (q) {
                        const matchesQuery = email.includes(q) || u.uid.toLowerCase().includes(q);
                        if (!matchesQuery) return false;
                    }
                    if (currentAdminTab === 'pending') {
                        return !u.approved && u.status !== 'denied' && u.status !== 'revoked';
                    } else if (currentAdminTab === 'approved') {
                        return u.approved;
                    } else if (currentAdminTab === 'denied-revoked') {
                        return !u.approved && (u.status === 'denied' || u.status === 'revoked');
                    }
                    return true;
                });

                if (filtered.length === 0) {
                    container.innerHTML = `
                        <div class="text-center py-10 bg-white rounded-xl border border-dashed border-slate-200">
                            <p class="text-xs font-semibold text-slate-500">No clinicians found in this tab.</p>
                            <p class="text-[11px] text-slate-400 mt-1">Pre-approve an email above or share the link with colleagues.</p>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = filtered.map(u => {
                    const email = u.email || 'No email';
                    const emailKey = email.toLowerCase();
                    const stats = adminUsageStats[u.uid] || adminUsageStats[emailKey] || {
                        total_requests: 0,
                        total_tokens: 0,
                        total_cost: 0.0,
                        last_active_at: null
                    };

                    const reqCount = stats.total_requests || 0;
                    const tokenCount = (stats.total_tokens || 0).toLocaleString();
                    const costFormatted = `$${(stats.total_cost || 0).toFixed(4)}`;
                    const lastActive = stats.last_active_at ? new Date(stats.last_active_at).toLocaleDateString() : 'None';

                    let actionsHtml = '';
                    if (currentAdminTab === 'pending') {
                        actionsHtml = `
                            <button onclick="handleSetUserApproval('${u.uid}', '${email}', true, 'approved')" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs rounded-lg transition shadow-2xs">
                                ✔ Approve
                            </button>
                            <button onclick="handleSetUserApproval('${u.uid}', '${email}', false, 'denied')" class="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 font-semibold text-xs rounded-lg transition">
                                ✕ Deny
                            </button>
                        `;
                    } else if (currentAdminTab === 'approved') {
                        actionsHtml = `
                            <button onclick="handleSetUserApproval('${u.uid}', '${email}', false, 'revoked')" class="px-3 py-1.5 bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-300 font-semibold text-xs rounded-lg transition">
                                Revoke Access
                            </button>
                        `;
                    } else {
                        actionsHtml = `
                            <button onclick="handleSetUserApproval('${u.uid}', '${email}', true, 'approved')" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs rounded-lg transition shadow-2xs">
                                ✔ Re-Approve
                            </button>
                        `;
                    }

                    const userInitial = (email.charAt(0) || 'U').toUpperCase();
                    const avatarHtml = u.photoURL ? 
                        `<img src="${u.photoURL}" class="w-8 h-8 rounded-full object-cover border border-slate-200 shadow-2xs shrink-0" referrerpolicy="no-referrer" alt="${email}" onerror="this.outerHTML='<div class=\\'w-8 h-8 rounded-full bg-sky-700 text-white font-bold text-xs flex items-center justify-center uppercase shadow-2xs shrink-0\\'>${userInitial}</div>'" />` :
                        `<div class="w-8 h-8 rounded-full bg-sky-700 text-white font-bold text-xs flex items-center justify-center uppercase shadow-2xs shrink-0">${userInitial}</div>`;

                    return `
                        <div class="bg-white rounded-xl border border-slate-200 p-4 shadow-2xs flex flex-wrap items-center justify-between gap-4">
                            <div class="flex items-start gap-3 flex-1 min-w-[280px]">
                                ${avatarHtml}
                                <div class="space-y-1.5 flex-1 min-w-0">
                                    <div class="flex items-center gap-2">
                                        <span class="font-bold text-xs text-slate-900 truncate">${u.displayName ? u.displayName + ' · ' : ''}${email}</span>
                                        <span class="text-[10px] px-2 py-0.2 rounded-full font-semibold shrink-0 ${u.approved ? 'bg-emerald-100 text-emerald-800 border border-emerald-200' : (u.status === 'denied' || u.status === 'revoked' ? 'bg-rose-100 text-rose-800 border border-rose-200' : 'bg-amber-100 text-amber-800 border border-amber-200')}">
                                            ${u.isPreapprovedOnly ? (u.approved ? 'Pre-Approved' : 'Revoked') : (u.approved ? 'Approved' : (u.status === 'denied' ? 'Denied' : (u.status === 'revoked' ? 'Revoked' : 'Pending')))}
                                        </span>
                                        ${u.isPreapprovedOnly ? '<span class="text-[9px] px-1.5 py-0.2 rounded bg-amber-50 text-amber-800 border border-amber-200 font-medium">Whitelist (Awaiting Sign-In)</span>' : ''}
                                    </div>
                                    <div class="text-[11px] text-slate-400 font-mono">${u.isPreapprovedOnly ? 'Pre-approved Whitelist · Awaiting initial sign-in' : `UID: ${u.uid}`}</div>
                                    <!-- Live Token & Cost Telemetry Badges -->
                                    <div class="flex flex-wrap items-center gap-2 pt-1">
                                        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-sky-50 border border-sky-100 text-[10px] font-semibold text-sky-800" title="Total API requests">
                                            <span>📊</span> <span>${reqCount} reqs</span>
                                        </span>
                                        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-indigo-50 border border-indigo-100 text-[10px] font-semibold text-indigo-800" title="Total Tokens Consumed">
                                            <span>🪙</span> <span>${tokenCount} tokens</span>
                                        </span>
                                        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-50 border border-emerald-100 text-[10px] font-semibold text-emerald-800" title="Estimated USD Cost">
                                            <span>💵</span> <span>${costFormatted}</span>
                                        </span>
                                        <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-50 border border-slate-100 text-[10px] text-slate-500" title="Last Active">
                                            <span>🕒</span> <span>${lastActive}</span>
                                        </span>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-2 shrink-0">
                                ${actionsHtml}
                            </div>
                        </div>
                    `;
                }).join('');
            }

            async function handleSetUserApproval(targetUid, targetEmail, approved, status) {
                // Optimistic Local State Update (Zero Wipeout Guard)
                const prevList = [...adminUsersList];
                adminUsersList = adminUsersList.map(u => {
                    if (u.uid === targetUid || (targetEmail && u.email && u.email.toLowerCase() === targetEmail.toLowerCase())) {
                        return { ...u, approved, status };
                    }
                    return u;
                });
                updateAdminTabCounts();
                renderAdminUserList();

                try {
                    if (targetUid && !targetUid.startsWith('preapproved:')) {
                        await fbDb.collection('users').doc(targetUid).set({
                            approved,
                            status,
                            role: 'user',
                            updatedAt: new Date().toISOString()
                        }, { merge: true });
                    }

                    if (targetEmail) {
                        await fbDb.collection('preapproved_emails').doc(targetEmail.toLowerCase().trim()).set({
                            email: targetEmail.toLowerCase().trim(),
                            approved,
                            status,
                            updatedAt: new Date().toISOString()
                        }, { merge: true });
                    }
                } catch (err) {
                    console.error("Failed to update user approval:", err);
                    alert("Error saving approval status: " + err.message);
                    adminUsersList = prevList;
                    updateAdminTabCounts();
                    renderAdminUserList();
                }
            }

            async function handlePreapproveEmail() {
                const input = document.getElementById('preApproveEmailInput');
                const btn = document.getElementById('preApproveBtn');
                const email = (input ? input.value : '').toLowerCase().trim();
                if (!email || !email.includes('@')) {
                    alert('Please enter a valid email address.');
                    return;
                }

                if (btn) btn.disabled = true;
                try {
                    await fbDb.collection('preapproved_emails').doc(email).set({
                        email: email,
                        approved: true,
                        status: 'approved',
                        preapprovedAt: new Date().toISOString(),
                        preapprovedBy: MASTER_ADMIN_EMAIL
                    }, { merge: true });

                    // Check if user is already registered in users list
                    const match = adminUsersList.find(u => u.email && u.email.toLowerCase() === email && !u.isPreapprovedOnly);
                    if (match) {
                        await handleSetUserApproval(match.uid, email, true, 'approved');
                    } else {
                        // Immediately add or update in local list under Approved
                        adminUsersList = adminUsersList.filter(u => (u.email || '').toLowerCase() !== email);
                        adminUsersList.unshift({
                            uid: `preapproved:${email}`,
                            email: email,
                            displayName: '',
                            photoURL: '',
                            approved: true,
                            status: 'approved',
                            role: 'user',
                            createdAt: new Date().toISOString(),
                            lastLoginAt: null,
                            isPreapprovedOnly: true
                        });
                        updateAdminTabCounts();
                        switchAdminTab('approved');
                    }
                    if (input) input.value = '';
                } catch (err) {
                    alert('Error pre-approving email: ' + err.message);
                } finally {
                    if (btn) btn.disabled = false;
                }
            }

            // Display & Theme Customization System (modeled after HomeoWonk)
            const HIGHLIGHT_PALETTES = {
                amber: {
                    id: 'amber',
                    name: 'Warm Amber',
                    desc: 'Apothecary ochre',
                    hex: '#d97706',
                    primary: '#d97706',
                    primaryHover: '#b45309',
                    textLight: '#b45309',
                    textDark: '#fbbf24',
                    ring: 'rgba(217, 119, 6, 0.4)',
                    borderLight: 'rgba(217, 119, 6, 0.3)',
                    borderDark: 'rgba(217, 119, 6, 0.45)',
                    softBgLight: 'rgba(245, 158, 11, 0.12)',
                    softBgDark: 'rgba(245, 158, 11, 0.22)',
                    border: '#d97706',
                    bg: 'rgba(245, 158, 11, 0.28)',
                    ringGlow: 'rgba(251, 191, 36, 0.5)',
                    glow: 'rgba(245, 158, 11, 0.4)',
                    ringPulse: 'rgba(251, 191, 36, 0.8)',
                    glowPulse: 'rgba(245, 158, 11, 0.9)',
                    pillBg: '#d97706',
                    pillBorder: '#b45309'
                },
                emerald: {
                    id: 'emerald',
                    name: 'Emerald Green',
                    desc: 'Botanical herbal',
                    hex: '#059669',
                    primary: '#059669',
                    primaryHover: '#047857',
                    textLight: '#047857',
                    textDark: '#34d399',
                    ring: 'rgba(5, 150, 105, 0.4)',
                    borderLight: 'rgba(5, 150, 105, 0.3)',
                    borderDark: 'rgba(5, 150, 105, 0.45)',
                    softBgLight: 'rgba(16, 185, 129, 0.12)',
                    softBgDark: 'rgba(16, 185, 129, 0.22)',
                    border: '#059669',
                    bg: 'rgba(16, 185, 129, 0.26)',
                    ringGlow: 'rgba(52, 211, 153, 0.5)',
                    glow: 'rgba(16, 185, 129, 0.4)',
                    ringPulse: 'rgba(52, 211, 153, 0.8)',
                    glowPulse: 'rgba(16, 185, 129, 0.9)',
                    pillBg: '#059669',
                    pillBorder: '#047857'
                },
                teal: {
                    id: 'teal',
                    name: 'Teal Ocean',
                    desc: 'Medical cyan',
                    hex: '#0d9488',
                    primary: '#0d9488',
                    primaryHover: '#0f766e',
                    textLight: '#0f766e',
                    textDark: '#2dd4bf',
                    ring: 'rgba(13, 148, 136, 0.4)',
                    borderLight: 'rgba(13, 148, 136, 0.3)',
                    borderDark: 'rgba(13, 148, 136, 0.45)',
                    softBgLight: 'rgba(20, 184, 166, 0.12)',
                    softBgDark: 'rgba(20, 184, 166, 0.22)',
                    border: '#0d9488',
                    bg: 'rgba(20, 184, 166, 0.26)',
                    ringGlow: 'rgba(45, 212, 191, 0.5)',
                    glow: 'rgba(20, 184, 166, 0.4)',
                    ringPulse: 'rgba(45, 212, 191, 0.8)',
                    glowPulse: 'rgba(20, 184, 166, 0.9)',
                    pillBg: '#0d9488',
                    pillBorder: '#0f766e'
                },
                blue: {
                    id: 'blue',
                    name: 'Medical Blue',
                    desc: 'Clinical cobalt',
                    hex: '#0284c7',
                    primary: '#0284c7',
                    primaryHover: '#0369a1',
                    textLight: '#0369a1',
                    textDark: '#38bdf8',
                    ring: 'rgba(2, 132, 199, 0.4)',
                    borderLight: 'rgba(2, 132, 199, 0.3)',
                    borderDark: 'rgba(2, 132, 199, 0.45)',
                    softBgLight: 'rgba(2, 132, 199, 0.12)',
                    softBgDark: 'rgba(2, 132, 199, 0.22)',
                    border: '#0284c7',
                    bg: 'rgba(2, 132, 199, 0.25)',
                    ringGlow: 'rgba(56, 189, 248, 0.5)',
                    glow: 'rgba(2, 132, 199, 0.4)',
                    ringPulse: 'rgba(56, 189, 248, 0.8)',
                    glowPulse: 'rgba(2, 132, 199, 0.9)',
                    pillBg: '#0284c7',
                    pillBorder: '#0369a1'
                },
                indigo: {
                    id: 'indigo',
                    name: 'Royal Indigo',
                    desc: 'Scholastic navy',
                    hex: '#4f46e5',
                    primary: '#4f46e5',
                    primaryHover: '#4338ca',
                    textLight: '#4338ca',
                    textDark: '#818cf8',
                    ring: 'rgba(79, 70, 229, 0.4)',
                    borderLight: 'rgba(79, 70, 229, 0.3)',
                    borderDark: 'rgba(79, 70, 229, 0.45)',
                    softBgLight: 'rgba(79, 70, 229, 0.12)',
                    softBgDark: 'rgba(79, 70, 229, 0.22)',
                    border: '#4f46e5',
                    bg: 'rgba(79, 70, 229, 0.25)',
                    ringGlow: 'rgba(129, 140, 248, 0.5)',
                    glow: 'rgba(79, 70, 229, 0.4)',
                    ringPulse: 'rgba(129, 140, 248, 0.8)',
                    glowPulse: 'rgba(79, 70, 229, 0.9)',
                    pillBg: '#4f46e5',
                    pillBorder: '#4338ca'
                },
                violet: {
                    id: 'violet',
                    name: 'Amethyst Violet',
                    desc: 'Diagnostic purple',
                    hex: '#7c3aed',
                    primary: '#7c3aed',
                    primaryHover: '#6d28d9',
                    textLight: '#6d28d9',
                    textDark: '#a78bfa',
                    ring: 'rgba(124, 58, 237, 0.4)',
                    borderLight: 'rgba(124, 58, 237, 0.3)',
                    borderDark: 'rgba(124, 58, 237, 0.45)',
                    softBgLight: 'rgba(124, 58, 237, 0.12)',
                    softBgDark: 'rgba(124, 58, 237, 0.22)',
                    border: '#7c3aed',
                    bg: 'rgba(124, 58, 237, 0.25)',
                    ringGlow: 'rgba(167, 139, 250, 0.5)',
                    glow: 'rgba(124, 58, 237, 0.4)',
                    ringPulse: 'rgba(167, 139, 250, 0.8)',
                    glowPulse: 'rgba(124, 58, 237, 0.9)',
                    pillBg: '#7c3aed',
                    pillBorder: '#6d28d9'
                },
                rose: {
                    id: 'rose',
                    name: 'Rose Coral',
                    desc: 'Vivid crimson',
                    hex: '#e11d48',
                    primary: '#e11d48',
                    primaryHover: '#be123c',
                    textLight: '#be123c',
                    textDark: '#fb7185',
                    ring: 'rgba(225, 29, 72, 0.4)',
                    borderLight: 'rgba(225, 29, 72, 0.3)',
                    borderDark: 'rgba(225, 29, 72, 0.45)',
                    softBgLight: 'rgba(225, 29, 72, 0.12)',
                    softBgDark: 'rgba(225, 29, 72, 0.22)',
                    border: '#e11d48',
                    bg: 'rgba(225, 29, 72, 0.25)',
                    ringGlow: 'rgba(251, 113, 133, 0.5)',
                    glow: 'rgba(225, 29, 72, 0.4)',
                    ringPulse: 'rgba(251, 113, 133, 0.8)',
                    glowPulse: 'rgba(225, 29, 72, 0.9)',
                    pillBg: '#e11d48',
                    pillBorder: '#be123c'
                },
                slate: {
                    id: 'slate',
                    name: 'Monochrome Slate',
                    desc: 'Graphite steel',
                    hex: '#475569',
                    primary: '#475569',
                    primaryHover: '#334155',
                    textLight: '#334155',
                    textDark: '#94a3b8',
                    ring: 'rgba(71, 85, 105, 0.4)',
                    borderLight: 'rgba(71, 85, 105, 0.3)',
                    borderDark: 'rgba(71, 85, 105, 0.45)',
                    softBgLight: 'rgba(71, 85, 105, 0.12)',
                    softBgDark: 'rgba(71, 85, 105, 0.22)',
                    border: '#475569',
                    bg: 'rgba(71, 85, 105, 0.3)',
                    ringGlow: 'rgba(148, 163, 184, 0.5)',
                    glow: 'rgba(71, 85, 105, 0.4)',
                    ringPulse: 'rgba(148, 163, 184, 0.8)',
                    glowPulse: 'rgba(71, 85, 105, 0.9)',
                    pillBg: '#475569',
                    pillBorder: '#334155'
                }
            };

            let currentThemeMode = localStorage.getItem('fact_theme_mode') || 'light';
            let currentHighlightColor = localStorage.getItem('fact_highlight_color') || 'amber';

            function applyThemeMode(mode) {
                currentThemeMode = mode;
                if (mode === 'dark') {
                    document.documentElement.classList.add('dark');
                } else {
                    document.documentElement.classList.remove('dark');
                }
                localStorage.setItem('fact_theme_mode', mode);
                applyHighlightColor(currentHighlightColor);
                updateThemeModalUI();
            }

            function setThemeMode(mode) {
                applyThemeMode(mode);
            }

            function applyHighlightColor(colorId) {
                currentHighlightColor = HIGHLIGHT_PALETTES[colorId] ? colorId : 'amber';
                const p = HIGHLIGHT_PALETTES[currentHighlightColor];
                const isDark = document.documentElement.classList.contains('dark');
                const r = document.documentElement;
                r.style.setProperty('--accent-primary', p.primary);
                r.style.setProperty('--accent-hover', p.primaryHover);
                r.style.setProperty('--accent-text', isDark ? p.textDark : p.textLight);
                r.style.setProperty('--accent-ring', p.ring);
                r.style.setProperty('--accent-border', isDark ? p.borderDark : p.borderLight);
                r.style.setProperty('--accent-soft-bg', isDark ? p.softBgDark : p.softBgLight);
                r.style.setProperty('--highlight-border', p.border);
                r.style.setProperty('--highlight-bg', p.bg);
                r.style.setProperty('--highlight-ring', p.ringGlow || p.ring);
                r.style.setProperty('--highlight-glow', p.glow);
                r.style.setProperty('--highlight-ring-pulse', p.ringPulse);
                r.style.setProperty('--highlight-glow-pulse', p.glowPulse);
                r.style.setProperty('--highlight-pill-bg', p.pillBg);
                r.style.setProperty('--highlight-pill-border', p.pillBorder);
                r.style.setProperty('--highlight-hex', p.hex);

                const dot = document.getElementById('settingsHighlightDot');
                if (dot) dot.style.backgroundColor = p.hex;

                const prevHitbox = document.getElementById('previewHitbox');
                if (prevHitbox) {
                    prevHitbox.style.borderColor = p.border;
                    prevHitbox.style.backgroundColor = p.bg;
                    prevHitbox.style.boxShadow = `0 0 0 2px ${p.ringGlow || p.ring}, 0 0 10px ${p.glow}`;
                }

                // Dynamically update PWA title bar color in Chrome / Edge / Windows / Android
                const metaThemeColor = document.getElementById('pwaThemeColor') || document.querySelector('meta[name="theme-color"]');
                if (metaThemeColor && p.primary) {
                    metaThemeColor.setAttribute('content', p.primary);
                }

                localStorage.setItem('fact_highlight_color', currentHighlightColor);
                updateThemeModalUI();
            }

            function setHighlightColor(colorId) {
                applyHighlightColor(colorId);
            }

            let currentDefaultMode = localStorage.getItem('fact_default_mode') || 'appraisal';

            function setDefaultStartupMode(mode) {
                currentDefaultMode = mode;
                localStorage.setItem('fact_default_mode', mode);
                updateThemeModalUI();
            }

            function updateThemeModalUI() {
                const isDark = document.documentElement.classList.contains('dark');
                const themeBtnLight = document.getElementById('themeBtnLight');
                const themeBtnDark = document.getElementById('themeBtnDark');
                const checkLight = document.getElementById('themeCheckLight');
                const checkDark = document.getElementById('themeCheckDark');

                if (themeBtnLight && themeBtnDark) {
                    if (isDark) {
                        themeBtnDark.className = "p-4 rounded-xl border text-left flex items-start space-x-3 transition cursor-pointer border-indigo-500 bg-slate-800 shadow-xs ring-2 ring-indigo-500/30";
                        if (checkDark) checkDark.classList.remove('hidden');
                        themeBtnLight.className = "p-4 rounded-xl border text-left flex items-start space-x-3 transition cursor-pointer border-slate-700 bg-slate-800/40 hover:bg-slate-800 text-slate-400";
                        if (checkLight) checkLight.classList.add('hidden');
                    } else {
                        themeBtnLight.className = "p-4 rounded-xl border text-left flex items-start space-x-3 transition cursor-pointer border-amber-400 bg-white shadow-xs ring-2 ring-amber-400/30";
                        if (checkLight) checkLight.classList.remove('hidden');
                        themeBtnDark.className = "p-4 rounded-xl border text-left flex items-start space-x-3 transition cursor-pointer border-slate-200 bg-slate-50 hover:bg-slate-100 text-slate-600";
                        if (checkDark) checkDark.classList.add('hidden');
                    }
                }

                const curPal = HIGHLIGHT_PALETTES[currentHighlightColor] || HIGHLIGHT_PALETTES.amber;

                // Update Default Startup Mode UI
                const curDefMode = localStorage.getItem('fact_default_mode') || 'appraisal';
                const modeBtnMap = {
                    finder: { btn: document.getElementById('defaultModeBtnFinder'), check: document.getElementById('defaultModeCheckFinder') },
                    appraisal: { btn: document.getElementById('defaultModeBtnAppraisal'), check: document.getElementById('defaultModeCheckAppraisal') },
                    summarizer: { btn: document.getElementById('defaultModeBtnSummarizer'), check: document.getElementById('defaultModeCheckSummarizer') }
                };

                Object.keys(modeBtnMap).forEach(mKey => {
                    const item = modeBtnMap[mKey];
                    if (!item.btn) return;
                    const isSelected = (mKey === curDefMode);
                    if (isSelected) {
                        item.btn.className = "p-3.5 rounded-xl border text-left flex flex-col justify-between transition cursor-pointer shadow-xs font-semibold ring-2";
                        item.btn.style.borderColor = curPal.primary;
                        item.btn.style.backgroundColor = isDark ? curPal.softBgDark : curPal.softBgLight;
                        item.btn.style.boxShadow = `0 0 0 2px ${curPal.ring}`;
                        if (item.check) {
                            item.check.classList.remove('hidden');
                            item.check.style.backgroundColor = curPal.hex;
                            item.check.style.color = '#ffffff';
                            item.check.style.borderColor = curPal.primary;
                        }
                    } else {
                        item.btn.className = "p-3.5 rounded-xl border text-left flex flex-col justify-between transition cursor-pointer border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300";
                        item.btn.style.borderColor = '';
                        item.btn.style.backgroundColor = '';
                        item.btn.style.boxShadow = '';
                        if (item.check) item.check.classList.add('hidden');
                    }
                });

                const nameEl = document.getElementById('activeHighlightName');
                if (nameEl) nameEl.innerText = curPal.name;

                const badgeEl = document.getElementById('activeHighlightBadge');
                if (badgeEl) {
                    badgeEl.style.backgroundColor = isDark ? curPal.softBgDark : curPal.softBgLight;
                    badgeEl.style.color = isDark ? curPal.textDark : curPal.textLight;
                    badgeEl.style.borderColor = isDark ? curPal.borderDark : curPal.borderLight;
                }

                const grid = document.getElementById('highlightColorGrid');
                if (grid) {
                    grid.innerHTML = Object.values(HIGHLIGHT_PALETTES).map(pal => {
                        const isSelected = pal.id === currentHighlightColor;
                        return `
                            <button
                                type="button"
                                onclick="setHighlightColor('${pal.id}')"
                                class="p-3 rounded-xl border text-left transition flex items-center space-x-2.5 cursor-pointer ${
                                    isSelected
                                        ? 'shadow-xs font-bold'
                                        : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/40 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300'
                                }"
                                style="${isSelected ? `border-color: ${pal.primary}; background-color: ${isDark ? pal.softBgDark : pal.softBgLight}; box-shadow: 0 0 0 2px ${pal.ring};` : ''}"
                            >
                                <div class="w-6 h-6 rounded-full flex items-center justify-center text-white shrink-0 shadow-2xs text-xs font-bold" style="background-color: ${pal.hex};">
                                    ${isSelected ? '✓' : ''}
                                </div>
                                <div class="min-w-0">
                                    <div class="font-semibold text-xs truncate text-slate-900 dark:text-slate-100">${escapeHtml(pal.name)}</div>
                                    <div class="text-[10px] text-slate-500 dark:text-slate-400 truncate">${escapeHtml(pal.desc)}</div>
                                </div>
                            </button>
                        `;
                    }).join('');
                }
            }

            function openSettingsModal(section) {
                const m = document.getElementById('settingsModal');
                if (m) {
                    m.classList.remove('hidden');
                    updateThemeModalUI();
                    renderVoiceModalUI();
                    if (section === 'voice') {
                        setTimeout(() => {
                            const vs = document.getElementById('settingsVoiceSection');
                            if (vs) vs.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        }, 50);
                    }
                }
            }

            function closeSettingsModal() {
                const m = document.getElementById('settingsModal');
                if (m) m.classList.add('hidden');
            }

            // Global Encapsulated Cross-Tab State
            window.ResearchAppState = {
                currentMasterMode: 'appraisal', // 'finder' | 'summarizer' | 'appraisal'
                finderResults: [],
                summarizerBatch: [],
                lastSearchQuery: '',
                isSearching: false,
                isSummarizing: false,
                lastSummarizerMarkdown: ''
            };

            function switchMasterMode(mode) {
                window.ResearchAppState.currentMasterMode = mode;
                const finderCont = document.getElementById('finderContainer');
                const summarizerCont = document.getElementById('summarizerContainer');
                const resultBox = document.getElementById('resultBox');
                const splitCont = document.getElementById('splitContainer');
                const tabFinderBtn = document.getElementById('masterTabFinder');
                const tabSummarizerBtn = document.getElementById('masterTabSummarizer');
                const tabAppraisalBtn = document.getElementById('masterTabAppraisal');

                // Reset tab styles
                if (tabFinderBtn) tabFinderBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium";
                if (tabSummarizerBtn) tabSummarizerBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium";
                if (tabAppraisalBtn) tabAppraisalBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 flex items-center gap-1.5 text-xs font-medium";

                // Toggle visibility between sibling DOM containers
                if (finderCont) finderCont.classList.add('hidden');
                if (summarizerCont) summarizerCont.classList.add('hidden');
                if (resultBox) resultBox.classList.add('hidden');

                if (mode === 'finder') {
                    if (finderCont) finderCont.classList.remove('hidden');
                    if (tabFinderBtn) tabFinderBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                } else if (mode === 'summarizer') {
                    if (summarizerCont) summarizerCont.classList.remove('hidden');
                    if (tabSummarizerBtn) tabSummarizerBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    syncSummarizerInputFromBatch();
                } else {
                    // Mode 'appraisal'
                    if (tabAppraisalBtn) tabAppraisalBtn.className = "px-3 py-1.5 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    // Only unhide resultBox if appraisal content has already been generated
                    if (currentFilename) {
                        if (resultBox) resultBox.classList.remove('hidden');
                        if (typeof centerHighlightInViewer === 'function') {
                            requestAnimationFrame(() => centerHighlightInViewer(false));
                        }
                    }
                }
            }

            // Paper Finder Handlers
            function setFinderQuery(q) {
                const input = document.getElementById('finderSearchInput');
                if (input) {
                    input.value = q;
                    input.focus();
                }
            }

            function clearFinderSearch() {
                const input = document.getElementById('finderSearchInput');
                if (input) {
                    input.value = '';
                    input.focus();
                }
            }

            async function executeFinderSearch() {
                if (!currentUser) {
                    openAuthModal();
                    return;
                }
                if (!isApproved) {
                    const pendingModal = document.getElementById('pendingApprovalModal');
                    if (pendingModal) pendingModal.classList.remove('hidden');
                    return;
                }

                const input = document.getElementById('finderSearchInput');
                const query = input ? input.value.trim() : '';
                if (!query) {
                    alert('Please enter a clinical research query or recollection.');
                    return;
                }

                const btn = document.getElementById('finderSubmitBtn');
                const btnIcon = document.getElementById('finderBtnIcon');
                const btnText = document.getElementById('finderBtnText');
                const banner = document.getElementById('finderStatusBanner');
                const resultsList = document.getElementById('finderResultsList');

                window.ResearchAppState.isSearching = true;
                if (btn) btn.disabled = true;
                if (btnIcon) btnIcon.innerHTML = '<span class="inline-block animate-spin">⏳</span>';
                if (btnText) btnText.innerText = 'Searching Databases...';

                if (banner) {
                    banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-sky-50 text-sky-800 border-sky-200";
                    banner.innerHTML = '<span>⏳ Searching PubMed & Europe PMC and verifying against published abstracts...</span>';
                    banner.classList.remove('hidden');
                }

                const forceRefresh = document.getElementById('finderForceRefresh')?.checked || false;
                try {
                    const resp = await fetch('/api/finder/search', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            query: query,
                            max_results: 10,
                            force_refresh: forceRefresh,
                            user_uid: currentUser ? currentUser.uid : 'anonymous',
                            user_email: currentUser ? currentUser.email : 'unauthenticated'
                        })
                    });
                    
                    if (!resp.ok) {
                        const errText = await resp.text();
                        let msg = `Server returned HTTP ${resp.status}`;
                        try {
                            const errJson = JSON.parse(errText);
                            if (errJson.detail) msg = errJson.detail;
                            else if (errJson.message) msg = errJson.message;
                        } catch (_) {
                            if (resp.status === 504 || resp.status === 524) {
                                msg = "Gateway Timeout: Literature search took longer than 60s. Please refine your query.";
                            }
                        }
                        throw new Error(msg);
                    }
                    const data = await resp.json();

                    window.ResearchAppState.finderResults = data.qualifying_papers || [];
                    window.ResearchAppState.lastSearchQuery = query;

                    if (data.status === 'success' && data.qualifying_papers && data.qualifying_papers.length > 0) {
                        const tierName = typeof data.tier_used === 'string' ? data.tier_used :
                                         data.tier_used === 1 ? 'Tier 1 (Strict Specific)' : 
                                         data.tier_used === 2 ? 'Tier 2 (Relaxed Geography)' : 
                                         data.tier_used === 3 ? 'Tier 3 (Core Clinical Only)' : 'Tier 4 (Semantic Scholar Fallback)';
                        
                        banner.className = data.is_fallback ? 
                            "rounded-lg p-3 text-xs flex items-center justify-between border bg-amber-50 text-amber-900 border-amber-200" :
                            "rounded-lg p-3 text-xs flex items-center justify-between border bg-emerald-50 text-emerald-900 border-emerald-200";
                        
                        const cacheBadge = data.from_cache ? 
                            '<span class="px-2 py-0.5 rounded bg-sky-100 text-sky-800 font-bold text-[10px] border border-sky-300">⚡ CACHED</span>' : '';
                        const reasoningBadge = data.thinking_level ? 
                            `<span class="px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-[10px] font-mono border border-slate-200">reasoning: ${data.thinking_level}</span>` : '';

                        banner.innerHTML = `
                            <div class="flex flex-wrap items-center gap-2">
                                <span class="font-bold">${data.qualifying_count} Verified Studies Found</span>
                                <span class="text-slate-400">•</span>
                                <span>Source: ${data.source_database} (${tierName})</span>
                                ${cacheBadge}
                                ${reasoningBadge}
                                ${data.is_fallback ? '<span class="px-2 py-0.5 rounded bg-amber-200 text-amber-900 font-bold text-[10px]">FALLBACK</span>' : ''}
                            </div>
                            <span class="font-mono text-[11px] text-slate-500">Evaluated ${data.total_evaluated} candidates</span>
                        `;
                        renderFinderResults(data.qualifying_papers);
                    } else {
                        banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-rose-50 text-rose-800 border-rose-200";
                        banner.innerHTML = `<span>⚠️ ${data.message || 'Search Failed: No literature candidates matching clinical criteria located.'}</span>`;
                        resultsList.innerHTML = `
                            <div class="text-center py-12 text-slate-500 text-xs space-y-2">
                                <p class="font-semibold text-slate-700">No qualifying studies found</p>
                                <p class="text-slate-400">All evaluated candidates failed the binary clinical gate (Intervention and Condition mismatch).</p>
                            </div>
                        `;
                    }
                } catch (err) {
                    if (banner) {
                        banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-rose-50 text-rose-800 border-rose-200";
                        banner.innerHTML = `<span>❌ Search request failed: ${err.message}</span>`;
                    }
                } finally {
                    window.ResearchAppState.isSearching = false;
                    if (btn) btn.disabled = false;
                    if (btnIcon) btnIcon.innerText = '🔍';
                    if (btnText) btnText.innerText = 'Find Verified Papers';
                }
            }

            function renderFinderResults(papers) {
                const resultsList = document.getElementById('finderResultsList');
                if (!resultsList) return;

                if (!papers || papers.length === 0) {
                    resultsList.innerHTML = '<div class="text-center py-10 text-slate-400 text-xs">No papers to display.</div>';
                    return;
                }

                resultsList.innerHTML = papers.map((p, idx) => {
                    const matchScore = p.match_score || 50;
                    const scoreColor = matchScore >= 80 ? 'bg-emerald-100 text-emerald-800 border-emerald-300' :
                                       matchScore >= 65 ? 'bg-sky-100 text-sky-800 border-sky-300' :
                                       'bg-amber-100 text-amber-800 border-amber-300';
                    
                    const isEPMC = Boolean(
                        (p.source && p.source.includes('Europe PMC')) ||
                        (p.pmc_url && p.pmc_url.includes('europepmc.org')) ||
                        (p.url && p.url.includes('europepmc.org'))
                    );

                    let sourceBadge = '';
                    if (p.source && p.source.includes('Europe PMC') && p.source.includes('PubMed')) {
                        sourceBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-teal-100 text-teal-900 border border-teal-300">PubMed + Europe PMC</span>';
                    } else if (p.source === 'Europe PMC') {
                        sourceBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-teal-100 text-teal-800 border border-teal-300">Europe PMC Verified</span>';
                    } else if (p.is_fallback) {
                        sourceBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300">Semantic Scholar Fallback</span>';
                    } else {
                        sourceBadge = '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">PubMed Verified</span>';
                    }

                    const hasFullText = Boolean(p.has_full_text || p.pmcid);
                    let fullTextBadge = '';
                    if (hasFullText && isEPMC) {
                        fullTextBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-teal-50 text-teal-800 border border-teal-300 flex items-center gap-1" title="Open Access Full Text via Europe PMC (${p.pmcid || 'Europe PMC'})">
                            <span>🌐</span> <span>Europe PMC OA ${p.pmcid ? '(' + p.pmcid + ')' : ''}</span>
                        </span>`;
                    } else if (hasFullText) {
                        fullTextBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-800 border border-emerald-300 flex items-center gap-1" title="Free full text available on PubMed Central (${p.pmcid || 'PMC'})">
                            <span>🟢</span> <span>Free Full Text ${p.pmcid ? '(' + p.pmcid + ')' : ''}</span>
                        </span>`;
                    } else {
                        fullTextBadge = `<span class="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-200/80 text-slate-700 border border-slate-300 flex items-center gap-1" title="Paywalled: Only the published abstract is freely accessible. Full text requires institutional subscription or manual PDF upload.">
                            <span>🔒</span> <span>Paywalled (Abstract Only)</span>
                        </span>`;
                    }

                    const safeTitle = (p.title || 'Untitled Study').replace(/"/g, '&quot;');
                    const safeUrl = p.url || '';
                    const authorsStr = (p.authors && p.authors.length > 0) ? p.authors.slice(0, 3).join(', ') + (p.authors.length > 3 ? ' et al.' : '') : '';

                    const pmcLinkHtml = (hasFullText && p.pmcid) ? `
                        <a href="${p.pmc_url || (isEPMC ? 'https://europepmc.org/articles/' + p.pmcid : 'https://pmc.ncbi.nlm.nih.gov/articles/' + p.pmcid + '/')}" target="_blank" rel="noopener noreferrer" class="text-xs text-teal-700 hover:text-teal-900 underline flex items-center gap-1 font-mono font-medium" title="View Open Access Full Text on ${isEPMC ? 'Europe PMC' : 'PubMed Central'}">
                            <span>📄</span> <span>${isEPMC ? 'Europe PMC' : 'PMC'}: ${p.pmcid}</span>
                        </a>
                    ` : '';

                    // Construct Google Scholar query optimized for Scholar's citation & cluster grouping
                    // Passing the core title (up to the colon or first 12 words) plus first author gives Scholar the exact cluster
                    const rawTitle = p.title || '';
                    const titleBase = rawTitle.includes(':') ? rawTitle.split(':')[0] : rawTitle;
                    const cleanTitle = titleBase.replace(/[^\w\s-]/g, ' ').replace(/\s+/g, ' ').trim();
                    // PubMed lists authors as "Demidov LV" (surname first, then initials)
                    const firstAuthorParts = (p.authors && p.authors.length > 0) ? String(p.authors[0]).trim().split(/\s+/) : [];
                    const lastTok = firstAuthorParts[firstAuthorParts.length - 1] || '';
                    const firstAuthor = (firstAuthorParts.length > 1 && /^[A-Z]{1,3}$/.test(lastTok) ? firstAuthorParts[0] : lastTok).replace(/[^\w]/g, '');
                    
                    const scholarQueryParts = [];
                    if (cleanTitle) scholarQueryParts.push(cleanTitle);
                    if (firstAuthor) scholarQueryParts.push(firstAuthor);
                    
                    const scholarQuery = scholarQueryParts.join(' ') || (p.doi || (p.pmid ? 'PMID ' + p.pmid : ''));
                    const scholarUrl = 'https://scholar.google.com/scholar?hl=en&as_sdt=0%2C30&q=' + encodeURIComponent(scholarQuery) + '&btnG=';

                    const scholarBadge = `
                        <a href="${scholarUrl}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-sky-50 text-slate-700 hover:text-sky-800 border border-slate-300 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-700 transition" title="Search Google Scholar for author preprints, institutional repositories, and all free PDF versions">
                            <span>🎓</span> <span>Scholar Versions ↗</span>
                        </a>
                    `;

                    const appraiseTargetUrl = (hasFullText && p.pmc_url) ? p.pmc_url : safeUrl;
                    const appraiseBtn = hasFullText ? `
                        <button 
                            onclick="appraisePaperFromExternal('${appraiseTargetUrl}')" 
                            class="px-3 py-1.5 rounded-lg ${isEPMC ? 'bg-teal-600 hover:bg-teal-700' : 'bg-sky-600 hover:bg-sky-700'} text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer"
                            title="Open full interactive analysis in Workbench (${isEPMC ? 'Full manuscript retrieved via Europe PMC' : 'Full manuscript retrieved via PMC'})"
                        >
                            <span>🔬</span> <span>Analyze Full Text ${isEPMC ? '(Europe PMC)' : ''}</span>
                        </button>
                    ` : `
                        <button 
                            onclick="appraisePaperFromExternal('${safeUrl}')" 
                            class="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer"
                            title="Paywalled paper: Analyze published abstract or upload full-text PDF in Workbench"
                        >
                            <span>📄</span> <span>Analyze Abstract</span>
                        </button>
                    `;

                    return `
                        <div class="bg-slate-50 hover:bg-white rounded-xl border border-slate-200 p-5 shadow-2xs hover:shadow-xs transition space-y-3">
                            <div class="flex flex-wrap items-center justify-between gap-2">
                                <div class="flex flex-wrap items-center gap-2">
                                    <span class="px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${scoreColor}">
                                        ${matchScore}% Match
                                    </span>
                                    <span class="text-xs font-semibold text-slate-700 bg-slate-200/80 px-2 py-0.5 rounded">
                                        Year: ${p.year || 'N/A'}
                                    </span>
                                    ${sourceBadge}
                                    ${fullTextBadge}
                                </div>
                                <span class="text-[11px] text-slate-400 font-mono">
                                    ${p.pmid ? 'PMID: ' + p.pmid : ''}
                                </span>
                            </div>

                            <div>
                                <h3 class="text-sm font-bold text-slate-900 leading-snug">
                                    ${p.title}
                                </h3>
                                ${authorsStr ? `<p class="text-[11px] text-slate-500 mt-0.5">${authorsStr} • <span class="italic">${p.journal || ''}</span></p>` : ''}
                            </div>

                            <div class="bg-white rounded-lg p-3 border border-slate-200 text-xs text-slate-700 leading-relaxed">
                                <span class="font-bold text-sky-800 block text-[11px] uppercase tracking-wide mb-1">Grounded Clinical Findings:</span>
                                ${p.grounded_summary || 'Summary unavailable.'}
                            </div>

                            <div class="flex flex-wrap items-center justify-between gap-3 pt-1 border-t border-slate-100">
                                <div class="flex flex-wrap items-center gap-3">
                                    <a href="${safeUrl}" target="_blank" rel="noopener noreferrer" class="text-xs text-sky-600 hover:text-sky-800 underline flex items-center gap-1 font-mono">
                                        <span>🔗</span> <span>${safeUrl}</span>
                                    </a>
                                    ${pmcLinkHtml}
                                    ${scholarBadge}
                                </div>
                                <div class="flex items-center gap-2">
                                    <button 
                                        onclick="toggleContextualizerBatch(this, '${safeUrl}', '${safeTitle}')" 
                                        class="contextualizer-toggle-btn px-3 py-1.5 rounded-lg ${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? 'bg-sky-600 hover:bg-sky-700 text-white border-sky-600 shadow-2xs' : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border-slate-300'} text-xs font-semibold transition border flex items-center gap-1 cursor-pointer"
                                        title="${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? 'Click to remove from contextualizer batch' : 'Add to multi-paper contextualizer batch'}"
                                        data-url="${safeUrl}"
                                    >
                                        ${window.ResearchAppState.summarizerBatch.includes(safeUrl) ? '<span>+ Added</span>' : '<span>➕</span> <span>Add to Contextualizer</span>'}
                                    </button>
                                    ${appraiseBtn}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // Contextualizer (Summarizer) Handlers
            function updateSummarizerBatchCount() {
                const textarea = document.getElementById('summarizerUrlsInput');
                const counter = document.getElementById('summarizerBatchCounter');
                if (!textarea || !counter) return;
                const lines = textarea.value.trim().split(/\n+/).map(l => l.trim()).filter(Boolean);
                counter.innerText = `Batch size: ${lines.length} / 10 papers`;
                if (lines.length > 10) {
                    counter.className = "text-[11px] text-rose-600 font-bold";
                } else {
                    counter.className = "text-[11px] text-slate-400";
                }
                // Keep state aligned
                window.ResearchAppState.summarizerBatch = lines;
                updateSummarizerBadge();
                document.querySelectorAll('.contextualizer-toggle-btn').forEach(btn => {
                    const btnUrl = btn.getAttribute('data-url');
                    if (btnUrl && lines.includes(btnUrl)) {
                        btn.className = "contextualizer-toggle-btn px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold transition border border-sky-600 shadow-2xs flex items-center gap-1 cursor-pointer";
                        btn.innerHTML = `<span>+ Added</span>`;
                        btn.title = "Click to remove from contextualizer batch";
                    } else if (btnUrl) {
                        btn.className = "contextualizer-toggle-btn px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition border border-slate-300 flex items-center gap-1 cursor-pointer";
                        btn.innerHTML = `<span>➕</span> <span>Add to Contextualizer</span>`;
                        btn.title = "Add to multi-paper contextualizer batch";
                    }
                });
            }

            function toggleContextualizerBatch(btn, url, title) {
                if (!url) return;
                const batch = window.ResearchAppState.summarizerBatch;
                const idx = batch.indexOf(url);
                
                if (idx > -1) {
                    // Deselect
                    batch.splice(idx, 1);
                    if (btn) {
                        btn.className = "contextualizer-toggle-btn px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition border border-slate-300 flex items-center gap-1 cursor-pointer";
                        btn.innerHTML = `<span>➕</span> <span>Add to Contextualizer</span>`;
                        btn.title = "Add to multi-paper contextualizer batch";
                    }
                } else {
                    // Select
                    batch.push(url);
                    if (btn) {
                        btn.className = "contextualizer-toggle-btn px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold transition border border-sky-600 shadow-2xs flex items-center gap-1 cursor-pointer";
                        btn.innerHTML = `<span>+ Added</span>`;
                        btn.title = "Click to remove from contextualizer batch";
                    }
                }
                
                updateSummarizerBadge();
                syncSummarizerInputFromBatch();
            }

            function addToSummarizerBatch(url, title) {
                toggleContextualizerBatch(null, url, title);
            }

            function updateSummarizerBadge() {
                const badge = document.getElementById('summarizerBatchBadge');
                const count = window.ResearchAppState.summarizerBatch.length;
                if (badge) {
                    if (count > 0) {
                        badge.innerText = count;
                        badge.classList.remove('hidden');
                    } else {
                        badge.classList.add('hidden');
                    }
                }
            }

            function syncSummarizerInputFromBatch() {
                const textarea = document.getElementById('summarizerUrlsInput');
                if (textarea) {
                    textarea.value = window.ResearchAppState.summarizerBatch.join('\n');
                    const counter = document.getElementById('summarizerBatchCounter');
                    if (counter) {
                        const count = window.ResearchAppState.summarizerBatch.length;
                        counter.innerText = `Batch size: ${count} / 10 papers`;
                        counter.className = count > 10 ? "text-[11px] text-rose-600 font-bold" : "text-[11px] text-slate-400";
                    }
                }
            }

            function clearSummarizerInput() {
                const textarea = document.getElementById('summarizerUrlsInput');
                if (textarea) {
                    textarea.value = '';
                    updateSummarizerBatchCount();
                }
                window.ResearchAppState.summarizerBatch = [];
                updateSummarizerBadge();
                document.querySelectorAll('.contextualizer-toggle-btn').forEach(btn => {
                    btn.className = "contextualizer-toggle-btn px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition border border-slate-300 flex items-center gap-1 cursor-pointer";
                    btn.innerHTML = `<span>➕</span> <span>Add to Contextualizer</span>`;
                    btn.title = "Add to multi-paper contextualizer batch";
                });
            }

            function loadSampleSummarizerBatch() {
                const textarea = document.getElementById('summarizerUrlsInput');
                if (textarea) {
                    textarea.value = [
                        'https://pubmed.ncbi.nlm.nih.gov/23843810/',
                        'https://pubmed.ncbi.nlm.nih.gov/30302302/',
                        'https://pubmed.ncbi.nlm.nih.gov/29188837/'
                    ].join('\n');
                    updateSummarizerBatchCount();
                }
            }

            async function executeSummarizerBatch() {
                if (!currentUser) {
                    openAuthModal();
                    return;
                }
                if (!isApproved) {
                    const pendingModal = document.getElementById('pendingApprovalModal');
                    if (pendingModal) pendingModal.classList.remove('hidden');
                    return;
                }

                const textarea = document.getElementById('summarizerUrlsInput');
                const rawVal = textarea ? textarea.value.trim() : '';
                const lines = rawVal.split(/\n+/).map(l => l.trim()).filter(Boolean);

                if (lines.length === 0) {
                    alert('Please enter at least 1 PubMed URL, PMID, or DOI.');
                    return;
                }

                if (lines.length > 10) {
                    alert('Maximum recommended batch size is 10 papers. Please reduce the number of entries.');
                    return;
                }

                const btn = document.getElementById('summarizerSubmitBtn');
                const btnIcon = document.getElementById('summarizerBtnIcon');
                const btnText = document.getElementById('summarizerBtnText');
                const banner = document.getElementById('summarizerStatusBanner');
                const outContainer = document.getElementById('summarizerOutputContainer');
                const renderedDiv = document.getElementById('summarizerRenderedContent');
                const metaBadge = document.getElementById('summarizerMetaBadge');

                window.ResearchAppState.isSummarizing = true;
                if (btn) btn.disabled = true;
                if (btnIcon) btnIcon.innerHTML = '<span class="inline-block animate-spin">⏳</span>';
                if (btnText) btnText.innerText = 'Synthesizing Briefing...';

                if (banner) {
                    banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-sky-50 text-sky-800 border-sky-200";
                    banner.innerHTML = `<span>⚡ Ingesting structured abstracts sequentially for ${lines.length} papers & synthesizing lay briefing...</span>`;
                    banner.classList.remove('hidden');
                }

                try {
                    const resp = await fetch('/api/summarizer/generate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            urls: lines,
                            max_batch_size: 10,
                            user_uid: currentUser ? currentUser.uid : 'anonymous',
                            user_email: currentUser ? currentUser.email : 'unauthenticated'
                        })
                    });
                    
                    if (!resp.ok) {
                        const errText = await resp.text();
                        let msg = `Server returned HTTP ${resp.status}`;
                        try {
                            const errJson = JSON.parse(errText);
                            if (errJson.detail) msg = errJson.detail;
                            else if (errJson.message) msg = errJson.message;
                        } catch (_) {
                            if (resp.status === 504 || resp.status === 524) {
                                msg = "Gateway Timeout: Literature search took longer than 60s. Please refine your query.";
                            }
                        }
                        throw new Error(msg);
                    }
                    const data = await resp.json();

                    if (data.status === 'success') {
                        window.ResearchAppState.lastSummarizerMarkdown = data.formatted_markdown || '';
                        
                        banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-emerald-50 text-emerald-900 border-emerald-200";
                        banner.innerHTML = `
                            <span class="font-bold">✅ Briefing generated successfully (${data.accessible_count} accessible, ${data.inaccessible_count} unavailable).</span>
                        `;

                        if (metaBadge) {
                            metaBadge.innerText = `${data.accessible_count} of ${data.total_processed} Studies Analyzed`;
                        }

                        if (renderedDiv) {
                            renderedDiv.innerHTML = marked.parse(data.formatted_markdown || '');
                        }

                        if (outContainer) outContainer.classList.remove('hidden');
                    } else {
                        banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-rose-50 text-rose-800 border-rose-200";
                        banner.innerHTML = `<span>⚠️ ${data.message || 'Summarization failed.'}</span>`;
                    }
                } catch (err) {
                    if (banner) {
                        banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-rose-50 text-rose-800 border-rose-200";
                        banner.innerHTML = `<span>❌ Error generating summary: ${err.message}</span>`;
                    }
                } finally {
                    window.ResearchAppState.isSummarizing = false;
                    if (btn) btn.disabled = false;
                    if (btnIcon) btnIcon.innerText = '🚀';
                    if (btnText) btnText.innerText = 'Generate Science Briefing';
                }
            }

            function copySummarizerMarkdown() {
                const text = window.ResearchAppState.lastSummarizerMarkdown;
                if (!text) {
                    alert('No generated briefing to copy.');
                    return;
                }
                navigator.clipboard.writeText(text).then(() => {
                    const btnText = document.getElementById('copySummaryBtnText');
                    if (btnText) {
                        const original = btnText.innerText;
                        btnText.innerText = 'Copied to Clipboard!';
                        setTimeout(() => { btnText.innerText = original; }, 2000);
                    }
                }).catch(err => {
                    alert('Could not copy to clipboard: ' + err);
                });
            }

            // Cross-Tab Trigger: Deep link to Appraisal Workbench from Finder or Summarizer
            function appraisePaperFromExternal(url) {
                if (!url) return;

                // Step 1: Explicitly switch mode to appraisal and render splitContainer
                switchMasterMode('appraisal');

                // Ensure resultBox is unhidden so splitContainer DOM is actively rendered in layout
                const resultBox = document.getElementById('resultBox');
                if (resultBox) {
                    resultBox.classList.remove('hidden');
                }

                // Switch input tab to URL
                switchInputTab('url');

                const urlInput = document.getElementById('paperUrl');
                if (urlInput) {
                    urlInput.value = url;
                }

                // Step 2: Strict visibility toggling: wait for layout reflow before startUrlResolution()
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        startUrlResolution();
                    });
                });
            }

            let currentFilename = '';
            let anchorIndex = {};
            let currentMeta = null;

            // Draggable Divider Implementation
            (function initResizer() {
                const divider = document.getElementById('dragDivider');
                const leftPane = document.getElementById('leftPane');
                const rightPane = document.getElementById('rightPane');
                const container = document.getElementById('splitContainer');

                let isDragging = false;

                divider.addEventListener('mousedown', function(e) {
                    isDragging = true;
                    divider.classList.add('resizing');
                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                });

                document.addEventListener('mousemove', function(e) {
                    if (!isDragging) return;
                    const containerRect = container.getBoundingClientRect();
                    const newLeftWidth = e.clientX - containerRect.left;
                    const totalWidth = containerRect.width;

                    const leftPercent = Math.max(20, Math.min(80, (newLeftWidth / totalWidth) * 100));
                    const rightPercent = 100 - leftPercent;

                    leftPane.style.width = leftPercent + '%';
                    rightPane.style.width = rightPercent + '%';
                    
                    // Reposition hitbox after panel width change without forced auto-scroll
                    repositionHitbox(false);
                });

                document.addEventListener('mouseup', function() {
                    if (isDragging) {
                        isDragging = false;
                        divider.classList.remove('resizing');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';
                    }
                });
            })();

            // Section Hover & Pin Popup Implementation
            let popupHideTimer = null;
            let isPinned = false;
            let currentZoom = 1.0;
            let userCustomWidth = null;
            let userCustomHeight = null;

            function adjustPopupZoom(delta) {
                currentZoom = Math.max(0.6, Math.min(2.5, Math.round((currentZoom + delta) * 100) / 100));
                applyZoom();
            }

            function resetPopupZoom() {
                currentZoom = 1.0;
                applyZoom();
            }

            function applyZoom() {
                const img = document.getElementById('popupCropImg');
                const label = document.getElementById('popupZoomLevel');
                const popup = document.getElementById('sectionPopup');
                if (!img) return;
                const popW = (popup && popup.clientWidth > 0) ? popup.clientWidth : 740;
                const baseW = Math.max(300, popW - 32);
                const targetW = Math.round(baseW * currentZoom);
                img.style.width = targetW + 'px';
                img.style.maxWidth = currentZoom <= 1.0 ? '100%' : 'none';
                if (label) {
                    label.innerText = Math.round(currentZoom * 100) + '%';
                }
            }

            function togglePopupPin() {
                isPinned = !isPinned;
                updatePinUI();
            }

            function updatePinUI() {
                const pinBtn = document.getElementById('popupPinBtn');
                const pinText = document.getElementById('pinBtnText');
                if (!pinBtn || !pinText) return;
                if (isPinned) {
                    pinBtn.className = "flex items-center gap-1 px-2.5 py-1 rounded bg-amber-500 hover:bg-amber-600 text-slate-900 text-[11px] font-bold transition shadow-xs";
                    pinText.innerText = "Pinned";
                } else {
                    pinBtn.className = "flex items-center gap-1 px-2.5 py-1 rounded bg-sky-800/90 hover:bg-sky-600 text-sky-100 hover:text-white text-[11px] font-medium transition border border-sky-600/60";
                    pinText.innerText = "Pin";
                }
            }

            function closeSectionPopup() {
                isPinned = false;
                clearTimeout(popupHideTimer);
                updatePinUI();
                const popup = document.getElementById('sectionPopup');
                if (popup) popup.style.display = 'none';
            }

            function scheduleHidePopup() {
                if (isPinned) return;
                clearTimeout(popupHideTimer);
                popupHideTimer = setTimeout(() => {
                    if (!isPinned) {
                        const popup = document.getElementById('sectionPopup');
                        if (popup) popup.style.display = 'none';
                    }
                }, 400);
            }

            function cancelHidePopup() {
                clearTimeout(popupHideTimer);
            }

            (function initSectionPopup() {
                const hitbox = document.getElementById('highlightHitbox');
                const popup = document.getElementById('sectionPopup');
                const popupImg = document.getElementById('popupCropImg');
                const popupTitle = document.getElementById('popupTitle');

                function openPopup(e) {
                    if (!currentMeta) return;
                    cancelHidePopup();
                    popupTitle.innerText = (typeof formatAnchorDisplay === 'function') ? (formatAnchorDisplay(currentMeta.anchor_id) || 'Highlighted Section') : (currentMeta.anchor_id || 'Highlighted Section');
                    const cropUrl = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(currentMeta.anchor_id)}`;
                    if (popupImg.src !== cropUrl && !popupImg.src.endsWith(cropUrl)) {
                        popupImg.src = cropUrl;
                    }
                    
                    const transcriptBox = document.getElementById('popupTranscriptBox');
                    const transcriptText = document.getElementById('popupTranscriptText');
                    const pageInfo = document.getElementById('popupPageInfo');
                    if (transcriptBox && transcriptText && currentMeta.text) {
                        transcriptText.innerText = currentMeta.text;
                        if (pageInfo) pageInfo.innerText = currentMeta.page ? `Page ${currentMeta.page}` : '';
                        transcriptBox.classList.remove('hidden');
                    } else if (transcriptBox) {
                        transcriptBox.classList.add('hidden');
                    }
                    
                    applyZoom();

                    // Only compute position if popup is currently hidden to avoid jumping/chasing
                    if (popup.style.display !== 'flex') {
                        popup.style.display = 'flex';
                        positionPopup(e);
                    }
                }

                hitbox.addEventListener('mouseenter', openPopup);
                hitbox.addEventListener('mouseleave', scheduleHidePopup);

                // Clicking the highlight hitbox pins the popup
                hitbox.addEventListener('click', function(e) {
                    openPopup(e);
                    isPinned = true;
                    updatePinUI();
                });

                // When cursor enters the popup itself, cancel any hide timer so user can scroll / interact
                popup.addEventListener('mouseenter', cancelHidePopup);
                popup.addEventListener('mouseleave', scheduleHidePopup);

                // Close on Escape key
                document.addEventListener('keydown', function(e) {
                    if (e.key === 'Escape') {
                        closeSectionPopup();
                    }
                });

                function positionPopup(e) {
                    let popW = userCustomWidth || Math.min(740, window.innerWidth - 32);
                    popW = Math.min(popW, window.innerWidth - 32);
                    popup.style.width = Math.round(popW) + 'px';

                    if (userCustomHeight) {
                        let popH = Math.min(userCustomHeight, window.innerHeight - 32);
                        popup.style.height = Math.round(popH) + 'px';
                    }

                    const margin = 20;
                    // Determine if cursor is on the right or left half of screen
                    const isCursorOnRight = e.clientX > (window.innerWidth / 2);
                    let left;
                    if (isCursorOnRight) {
                        left = e.clientX - popW - margin;
                        if (left < 16) left = 16;
                    } else {
                        left = e.clientX + margin;
                        if (left + popW > window.innerWidth - 16) {
                            left = window.innerWidth - 16 - popW;
                        }
                    }

                    const popH = popup.offsetHeight || userCustomHeight || 480;
                    let top = e.clientY - (popH / 2);
                    if (top < 16) top = 16;
                    if (top + popH > window.innerHeight - 16) {
                        top = Math.max(16, window.innerHeight - popH - 16);
                    }

                    popup.style.left = Math.round(left) + 'px';
                    popup.style.top = Math.round(top) + 'px';
                }
            })();

            // Section Popup Drag-and-Move Implementation
            (function initPopupDraggable() {
                const header = document.getElementById('popupHeader');
                const popup = document.getElementById('sectionPopup');
                if (!header || !popup) return;

                let isDragging = false;
                let startX = 0, startY = 0;
                let initialLeft = 0, initialTop = 0;

                header.addEventListener('mousedown', function(e) {
                    // Do not drag if user clicked on buttons or zoom controls
                    if (e.target.closest('button, #popupZoomLevel')) return;

                    e.preventDefault();
                    isDragging = true;
                    startX = e.clientX;
                    startY = e.clientY;

                    // Auto-pin so the popup stays open while and after being moved
                    if (!isPinned) {
                        isPinned = true;
                        updatePinUI();
                    }

                    const rect = popup.getBoundingClientRect();
                    initialLeft = rect.left;
                    initialTop = rect.top;

                    header.style.cursor = 'grabbing';
                    document.body.style.userSelect = 'none';

                    function onMouseMove(moveEvent) {
                        if (!isDragging) return;
                        const dx = moveEvent.clientX - startX;
                        const dy = moveEvent.clientY - startY;

                        let newLeft = initialLeft + dx;
                        let newTop = initialTop + dy;

                        // Keep popup within viewport bounds with 10px margin
                        const popW = popup.offsetWidth;
                        const popH = popup.offsetHeight;
                        newLeft = Math.max(10, Math.min(window.innerWidth - popW - 10, newLeft));
                        newTop = Math.max(10, Math.min(window.innerHeight - popH - 10, newTop));

                        popup.style.left = Math.round(newLeft) + 'px';
                        popup.style.top = Math.round(newTop) + 'px';
                    }

                    function onMouseUp() {
                        if (isDragging) {
                            isDragging = false;
                            header.style.cursor = 'grab';
                            document.body.style.userSelect = '';
                            window.removeEventListener('mousemove', onMouseMove);
                            window.removeEventListener('mouseup', onMouseUp);
                        }
                    }

                    window.addEventListener('mousemove', onMouseMove);
                    window.addEventListener('mouseup', onMouseUp);
                });
            })();

            // Section Popup Drag-and-Resize Implementation
            (function initPopupResizable() {
                const popup = document.getElementById('sectionPopup');
                if (!popup) return;

                let isResizing = false;
                let currentHandle = null;
                let startX = 0, startY = 0;
                let startW = 0, startH = 0;
                let startLeft = 0, startTop = 0;

                popup.addEventListener('mousedown', function(e) {
                    const handle = e.target.closest('.popup-resizer');
                    if (!handle) return;

                    e.preventDefault();
                    e.stopPropagation();

                    isResizing = true;
                    currentHandle = handle.dataset.resize;
                    startX = e.clientX;
                    startY = e.clientY;

                    const rect = popup.getBoundingClientRect();
                    startW = rect.width;
                    startH = rect.height;
                    startLeft = rect.left;
                    startTop = rect.top;

                    // Auto-pin so the popup does not dismiss during or after resizing
                    if (!isPinned) {
                        isPinned = true;
                        updatePinUI();
                    }

                    document.body.style.userSelect = 'none';

                    const cursorMap = {
                        'r': 'ew-resize',
                        'l': 'ew-resize',
                        'b': 'ns-resize',
                        't': 'ns-resize',
                        'br': 'nwse-resize',
                        'tl': 'nwse-resize',
                        'bl': 'nesw-resize',
                        'tr': 'nesw-resize'
                    };
                    document.body.style.cursor = cursorMap[currentHandle] || 'nwse-resize';

                    function onMouseMove(moveEvent) {
                        if (!isResizing) return;
                        const dx = moveEvent.clientX - startX;
                        const dy = moveEvent.clientY - startY;

                        let newW = startW;
                        let newH = startH;
                        let newLeft = startLeft;
                        let newTop = startTop;

                        const minW = 320;
                        const minH = 180;
                        const maxW = window.innerWidth - 20;
                        const maxH = window.innerHeight - 20;

                        if (currentHandle.includes('r')) {
                            newW = Math.min(maxW, Math.max(minW, startW + dx));
                            if (newLeft + newW > window.innerWidth - 10) {
                                newW = window.innerWidth - 10 - newLeft;
                            }
                        }
                        if (currentHandle.includes('b')) {
                            newH = Math.min(maxH, Math.max(minH, startH + dy));
                            if (newTop + newH > window.innerHeight - 10) {
                                newH = window.innerHeight - 10 - newTop;
                            }
                        }
                        if (currentHandle.includes('l')) {
                            let proposedW = startW - dx;
                            if (proposedW < minW) {
                                newW = minW;
                                newLeft = startLeft + (startW - minW);
                            } else if (startLeft + dx < 10) {
                                newLeft = 10;
                                newW = startLeft + startW - 10;
                            } else {
                                newW = proposedW;
                                newLeft = startLeft + dx;
                            }
                        }
                        if (currentHandle.includes('t')) {
                            let proposedH = startH - dy;
                            if (proposedH < minH) {
                                newH = minH;
                                newTop = startTop + (startH - minH);
                            } else if (startTop + dy < 10) {
                                newTop = 10;
                                newH = startTop + startH - 10;
                            } else {
                                newH = proposedH;
                                newTop = startTop + dy;
                            }
                        }

                        userCustomWidth = newW;
                        userCustomHeight = newH;

                        popup.style.width = Math.round(newW) + 'px';
                        popup.style.height = Math.round(newH) + 'px';
                        popup.style.left = Math.round(newLeft) + 'px';
                        popup.style.top = Math.round(newTop) + 'px';

                        // Dynamically update image width to match the new container dimensions
                        applyZoom();
                    }

                    function onMouseUp() {
                        if (isResizing) {
                            isResizing = false;
                            currentHandle = null;
                            document.body.style.userSelect = '';
                            document.body.style.cursor = '';
                            window.removeEventListener('mousemove', onMouseMove);
                            window.removeEventListener('mouseup', onMouseUp);
                        }
                    }

                    window.addEventListener('mousemove', onMouseMove);
                    window.addEventListener('mouseup', onMouseUp);
                });
            })();

            function centerHighlightInViewer(smooth = true) {
                const pageViewer = document.getElementById('pageViewer');
                const hitbox = document.getElementById('highlightHitbox');
                if (!pageViewer || !hitbox || hitbox.style.display === 'none') return;

                requestAnimationFrame(() => {
                    const viewerRect = pageViewer.getBoundingClientRect();
                    const hitboxRect = hitbox.getBoundingClientRect();

                    if (viewerRect.height === 0 || hitboxRect.height === 0) return;

                    // Calculate precise relative offset of hitbox within pageViewer
                    const currentScroll = pageViewer.scrollTop;
                    const relativeTop = hitboxRect.top - viewerRect.top;
                    const targetScroll = currentScroll + relativeTop - (viewerRect.height / 2) + (hitboxRect.height / 2);

                    pageViewer.scrollTo({
                        top: Math.max(0, targetScroll),
                        behavior: smooth ? 'smooth' : 'auto'
                    });

                    // Trigger pulse animation to draw immediate visual attention
                    hitbox.classList.remove('hitbox-pulse');
                    void hitbox.offsetWidth; // Force reflow
                    hitbox.classList.add('hitbox-pulse');
                });
            }

            function renderFullDocumentPages(filename, totalPages, pagesList) {
                if (!filename || !totalPages || totalPages < 1) return;
                currentFilename = filename;
                const pagesStack = document.getElementById('pagesStack');
                const placeholder = document.getElementById('viewerPlaceholder');
                if (!pagesStack) return;

                if (pagesStack.getAttribute('data-loaded-file') === filename && pagesStack.children.length === totalPages) {
                    return;
                }

                pagesStack.innerHTML = '';
                pagesStack.setAttribute('data-loaded-file', filename);
                if (placeholder) placeholder.classList.add('hidden');
                pagesStack.classList.remove('hidden');

                for (let p = 1; p <= totalPages; p++) {
                    const pageWrapper = document.createElement('div');
                    pageWrapper.id = `page-wrapper-${p}`;
                    pageWrapper.className = 'relative bg-white dark:bg-slate-900 shadow rounded border border-slate-300 dark:border-slate-700 max-w-full inline-block transition';
                    pageWrapper.setAttribute('data-page', p);
                    pageWrapper.style.minHeight = '750px';

                    const badge = document.createElement('div');
                    badge.className = 'absolute top-2 left-2 px-2 py-0.5 bg-slate-800/70 text-white rounded text-[10px] font-mono pointer-events-none select-none z-10';
                    badge.innerText = `Page ${p} / ${totalPages}`;
                    pageWrapper.appendChild(badge);

                    const img = document.createElement('img');
                    img.id = `pdf-page-img-${p}`;
                    img.className = 'block max-w-full h-auto select-none rounded';
                    img.alt = `Page ${p}`;
                    img.loading = (p <= 2) ? 'eager' : 'lazy';
                    img.src = `/view-pdf-page?filename=${encodeURIComponent(filename)}&page=${p}`;

                    img.onload = function() {
                        if (currentMeta && (currentMeta.page || 1) === p) {
                            repositionHitbox(true);
                        }
                    };

                    pageWrapper.appendChild(img);
                    pagesStack.appendChild(pageWrapper);
                }
            }

            function repositionHitbox(shouldScroll = false) {
                if (!currentMeta || !currentMeta.bbox) {
                    const hitbox = document.getElementById('highlightHitbox');
                    if (hitbox) hitbox.style.display = 'none';
                    return;
                }
                const targetPage = currentMeta.page || 1;
                const pageWrapper = document.getElementById('page-wrapper-' + targetPage);
                const img = document.getElementById('pdf-page-img-' + targetPage);
                const hitbox = document.getElementById('highlightHitbox');
                if (!hitbox || !pageWrapper) return;

                if (hitbox.parentElement !== pageWrapper) {
                    hitbox.style.display = 'none';
                    pageWrapper.appendChild(hitbox);
                }

                if (!img || img.naturalWidth === 0) {
                    if (img) {
                        img.loading = 'eager';
                        img.addEventListener('load', () => repositionHitbox(shouldScroll), { once: true });
                    }
                    return;
                }

                if (img.clientWidth === 0) {
                    requestAnimationFrame(() => repositionHitbox(shouldScroll));
                    return;
                }

                const pWidth = currentMeta.page_width || 595.0;
                const scale = img.clientWidth / pWidth;

                const bbox = currentMeta.bbox;
                const left = bbox[0] * scale;
                const top = bbox[1] * scale;
                const width = (bbox[2] - bbox[0]) * scale;
                const height = (bbox[3] - bbox[1]) * scale;

                hitbox.style.position = 'absolute';
                hitbox.style.left = Math.max(0, left - 4) + 'px';
                hitbox.style.top = Math.max(0, top - 2) + 'px';
                hitbox.style.width = (width + 8) + 'px';
                hitbox.style.height = (height + 4) + 'px';
                hitbox.style.display = 'block';

                if (shouldScroll) {
                    centerHighlightInViewer(true);
                }
            }

            window.addEventListener('resize', function() { repositionHitbox(false); });

            function switchInputTab(tab) {
                const tabPdf = document.getElementById('tabPdf');
                const tabUrl = document.getElementById('tabUrl');
                const tabPdfBtn = document.getElementById('tabPdfBtn');
                const tabUrlBtn = document.getElementById('tabUrlBtn');

                const activeClass = "px-2.5 py-1 rounded bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-semibold transition";
                const inactiveClass = "px-2.5 py-1 rounded text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition";

                if (tab === 'pdf') {
                    tabPdf.classList.remove('hidden');
                    tabUrl.classList.add('hidden');
                    tabPdfBtn.className = activeClass;
                    tabUrlBtn.className = inactiveClass;
                } else {
                    tabPdf.classList.add('hidden');
                    tabUrl.classList.remove('hidden');
                    tabUrlBtn.className = activeClass;
                    tabPdfBtn.className = inactiveClass;
                }
            }

            function escapeHtml(str) {
                if (!str) return '';
                return String(str)
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#039;');
            }

            function switchLeftTab(tab) {
                const appraisalView = document.getElementById('outputMarkdown');
                const askView = document.getElementById('askContainer');
                const thinkingView = document.getElementById('thinkingContainer');
                const commentaryView = document.getElementById('commentaryContainer');
                const tabAppraisalBtn = document.getElementById('leftTabAppraisalBtn');
                const tabAskBtn = document.getElementById('leftTabAskBtn');
                const tabThinkingBtn = document.getElementById('leftTabThinkingBtn');
                const tabCommentaryBtn = document.getElementById('leftTabCommentaryBtn');
                const hint = document.getElementById('leftPaneHint');

                const activeClass = "px-3 py-1 rounded-md bg-white dark:bg-slate-900 tab-active-accent shadow-2xs font-semibold transition flex items-center gap-1.5 cursor-pointer";
                const inactiveClass = "px-3 py-1 rounded-md text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition flex items-center gap-1.5 cursor-pointer";

                if (appraisalView) appraisalView.classList.add('hidden');
                if (askView) askView.classList.add('hidden');
                if (thinkingView) thinkingView.classList.add('hidden');
                if (commentaryView) commentaryView.classList.add('hidden');

                if (tabAppraisalBtn) tabAppraisalBtn.className = inactiveClass;
                if (tabAskBtn) tabAskBtn.className = inactiveClass;
                if (tabThinkingBtn) tabThinkingBtn.className = inactiveClass;
                if (tabCommentaryBtn) tabCommentaryBtn.className = inactiveClass;

                if (tab === 'appraisal') {
                    if (appraisalView) appraisalView.classList.remove('hidden');
                    if (tabAppraisalBtn) tabAppraisalBtn.className = activeClass;
                    if (hint) hint.innerText = "Click any coordinate pill to inspect source text";
                } else if (tab === 'ask') {
                    if (askView) askView.classList.remove('hidden');
                    if (tabAskBtn) tabAskBtn.className = activeClass;
                    if (hint) hint.innerText = "Interactive QA grounded in manuscript anchors";
                    const inp = document.getElementById('askQuestionInput');
                    if (inp) inp.focus();
                } else if (tab === 'thinking') {
                    if (thinkingView) thinkingView.classList.remove('hidden');
                    if (tabThinkingBtn) tabThinkingBtn.className = activeClass;
                    if (hint) hint.innerText = "Auditing triage rationale, rules AST & reasoning trace";
                } else if (tab === 'commentary') {
                    if (commentaryView) commentaryView.classList.remove('hidden');
                    if (tabCommentaryBtn) tabCommentaryBtn.className = activeClass;
                    if (hint) hint.innerText = "Personalized clinician commentary with adversarial QC audit";
                    updateVoiceUIElements();
                }
            }

            const TAG_LABELS = {
                '+TAG_NON_INFERIORITY': 'Non-Inferiority Design',
                '+TAG_CONSORT_PRO': 'Patient-Reported Outcomes (PRO)',
                '+TAG_BIOMARKER': 'Biomarker Analysis',
                '+TAG_CROSSOVER': 'Crossover Design',
                '+TAG_SAFETY_HARMS': 'Safety & Adverse Events',
                '+TAG_IMMUNOTHERAPY': 'Immunotherapy',
                '+TAG_ONCOLOGY': 'Oncology',
                '+TAG_SUBGROUP': 'Subgroup Analysis',
                '+TAG_LIQUID_BIOPSY_CTDNA': 'Liquid Biopsy / ctDNA',
                '+TAG_COMPOSITE': 'Composite Endpoints',
                '+TAG_COHORT': 'Observational Cohort',
                '+TAG_EHR_CLAIMS': 'EHR / Claims Linkage',
                '+TAG_SURVEY': 'Survey / Questionnaire',
                '+TAG_IMMORTAL_TIME_RISK': 'Immortal Time Bias Risk',
                '+TAG_CARDIOLOGY': 'Cardiology',
                '+TAG_NEPHROLOGY': 'Nephrology',
                '+TAG_NEUROLOGY': 'Neurology',
                '+TAG_SURROGATE_ENDPOINT': 'Surrogate Endpoints'
            };

            function formatTagLabel(tag) {
                if (TAG_LABELS[tag]) return TAG_LABELS[tag];
                return tag.replace(/^\+?TAG_/, '').replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
            }

            function renderCoordinatePillsInText(rawText) {
                if (!rawText) return '';
                let escaped = escapeHtml(rawText);
                const bracketCoordRegex = /\[([^\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Patients?\s+and\s+Methods?|Materials?\s+and\s+Methods?|Results?|Res|Findings?|Discussion|Disc|Conclusions?|Concl|Appendix|Supp(?:lementary)?|Para(?:graph)?|Table(?:Note)?|Fig(?:ure)?(?:Legend)?|Box|p\d+)\b[^\]]*?)\]/gi;
                return escaped.replace(bracketCoordRegex, function(fullMatch, inner) {
                    const trimmed = inner.trim();
                    const rawAnchorId = `[${trimmed}]`;
                    const enc = encodeURIComponent(rawAnchorId);
                    const displayText = formatAnchorDisplay(trimmed);
                    return `<button type="button" onclick="inspectAnchor('${enc}')" data-anchor="${rawAnchorId}" class="anchor-pill inline-flex items-center px-1.5 py-0.5 mx-0.5 text-[11px] font-sans font-medium bg-sky-50 dark:bg-sky-950/70 text-sky-800 dark:text-sky-300 hover:bg-sky-600 hover:text-white border border-sky-300/80 dark:border-sky-800 rounded shadow-2xs leading-none cursor-pointer" title="Click to view source page and highlight">${displayText}</button>`;
                });
            }

            function renderThinkingAudit(data) {
                const container = document.getElementById('thinkingContainer');
                if (!container) return;

                const triage = data.triage || {};
                const evaluations = data.rule_evaluations || [];
                const rulesDetail = data.active_rules_detail || [];
                const displayRules = (evaluations.length > 0) ? evaluations : rulesDetail;
                const thought = (data.thought_output || '').trim();
                const selectedModel = data.selected_model || 'gemini-3.8-flash';

                // 1. Triage Rationale
                const fwName = triage.framework_name || 'Clinical Study';
                const confPercent = Math.round((triage.confidence || 0) * 100);
                const rationaleText = triage.rationale || 'Selected via deterministic trigger scoring against manuscript abstract and methods sections.';
                
                const tags = triage.sub_feature_tags || [];
                const tagsHtml = tags.length > 0
                    ? tags.map(t => `<span class="px-2.5 py-1 rounded bg-sky-50 text-sky-800 font-medium text-xs border border-sky-200">${escapeHtml(formatTagLabel(t))}</span>`).join(' ')
                    : '<span class="text-slate-400 italic text-xs">Standard study features</span>';

                const triggers = triage.matched_triggers || [];
                const triggersHtml = triggers.length > 0
                    ? triggers.map(tr => `<span class="px-2 py-0.5 rounded bg-slate-200/80 text-slate-700 font-mono text-[11px] border border-slate-300">"${escapeHtml(tr)}"</span>`).join(' ')
                    : '<span class="text-slate-400 italic text-[11px]">Standard design keywords</span>';

                // 2. Methodological Bias Rules Audit
                const passCount = displayRules.filter(e => (e.status || '').toUpperCase() === 'PASS').length;
                const failCount = displayRules.filter(e => (e.status || '').toUpperCase() === 'FAIL').length;
                const naCount = displayRules.filter(e => ['NOT_AVAILABLE', 'PENDING', 'UNKNOWN'].includes((e.status || '').toUpperCase())).length;

                let summaryTallyHtml = '';
                if (evaluations.length > 0) {
                    summaryTallyHtml = `
                        <div class="flex flex-wrap items-center gap-1.5 text-xs font-semibold">
                            <span class="px-2 py-0.5 rounded text-[11px] bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 flex items-center gap-1">
                                <span class="font-bold">✓</span> ${passCount} Compliant
                            </span>
                            ${failCount > 0 ? `
                            <span class="px-2 py-0.5 rounded text-[11px] bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300 border border-rose-200 dark:border-rose-800 flex items-center gap-1">
                                <span class="font-bold">✗</span> ${failCount} Deviations
                            </span>` : ''}
                            ${naCount > 0 ? `
                            <span class="px-2 py-0.5 rounded text-[11px] bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border border-amber-200 dark:border-amber-800 flex items-center gap-1">
                                <span class="font-bold">?</span> ${naCount} Not Reported
                            </span>` : ''}
                        </div>
                    `;
                } else {
                    summaryTallyHtml = `<span class="text-[11px] text-slate-500 font-mono">AST Rulebase v2.0</span>`;
                }

                let rulesListHtml = '';
                if (displayRules.length > 0) {
                    rulesListHtml = displayRules.map((r, idx) => {
                        const status = (r.status || '').toUpperCase();
                        let statusBadge = '';
                        if (status === 'PASS') {
                            statusBadge = `<span class="px-2.5 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700 flex items-center gap-1"><span class="text-emerald-600 dark:text-emerald-400 font-extrabold">✓</span> Compliant (Low Risk)</span>`;
                        } else if (status === 'FAIL') {
                            statusBadge = `<span class="px-2.5 py-0.5 rounded text-xs font-bold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 border border-rose-300 dark:border-rose-700 flex items-center gap-1"><span class="text-rose-600 dark:text-rose-400 font-extrabold">✗</span> Deviation (High Risk)</span>`;
                        } else if (status === 'NOT_AVAILABLE') {
                            statusBadge = `<span class="px-2.5 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 border border-amber-300 dark:border-amber-700 flex items-center gap-1"><span class="text-amber-600 dark:text-amber-400 font-extrabold">?</span> Not Reported</span>`;
                        } else if (status === 'PENDING') {
                            statusBadge = `<span class="px-2.5 py-0.5 rounded text-xs font-bold bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-300 dark:border-slate-700 flex items-center gap-1"><span class="text-slate-500 font-extrabold">⋯</span> Pending</span>`;
                        } else {
                            statusBadge = `<span class="px-2 py-0.5 rounded text-[11px] font-medium text-slate-600 bg-slate-100 border border-slate-200">Rule Active</span>`;
                        }

                        let headlineHtml = '';
                        if (r.verdict_title) {
                            headlineHtml = `<div class="text-xs font-bold text-slate-900 dark:text-slate-100 mb-1 flex items-center gap-1.5">${escapeHtml(r.verdict_title)}</div>`;
                        }

                        let explanationHtml = '';
                        if (r.explanation) {
                            explanationHtml = `<div class="text-xs text-slate-800 dark:text-slate-200 mb-2 leading-relaxed">${renderCoordinatePillsInText(r.explanation)}</div>`;
                        } else if (r.appraisal_action) {
                            explanationHtml = `<p class="text-xs text-slate-800 dark:text-slate-200 font-medium mb-2 leading-relaxed">${escapeHtml(r.appraisal_action)}</p>`;
                        }

                        let citationsHtml = '';
                        if (r.citations && Array.isArray(r.citations) && r.citations.length > 0) {
                            const pills = r.citations.map(c => {
                                const clean = String(c).replace(/^\[|\]$/g, '').trim();
                                const rawAnchorId = `[${clean}]`;
                                const enc = encodeURIComponent(rawAnchorId);
                                const displayText = formatAnchorDisplay(clean);
                                return `<button type="button" onclick="inspectAnchor('${enc}')" data-anchor="${rawAnchorId}" class="anchor-pill inline-flex items-center px-2 py-0.5 text-[11px] font-sans font-medium bg-sky-50 dark:bg-sky-950/70 text-sky-800 dark:text-sky-300 hover:bg-sky-600 hover:text-white border border-sky-300/80 dark:border-sky-800 rounded shadow-2xs leading-none cursor-pointer" title="Click to view source page and highlight">${displayText}</button>`;
                            }).join(' ');
                            citationsHtml = `
                                <div class="flex items-center gap-1.5 flex-wrap pt-1.5 pb-1">
                                    <span class="text-[11px] font-semibold text-slate-500 dark:text-slate-400">Cited Coordinates:</span>
                                    ${pills}
                                </div>
                            `;
                        }

                        return `
                            <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md p-3.5 shadow-2xs hover:border-slate-300 dark:hover:border-slate-700 transition">
                                <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
                                    <div class="flex items-center gap-2">
                                        <span class="text-xs font-bold text-sky-800 dark:text-sky-300 bg-sky-100 dark:bg-sky-950 px-2 py-0.5 rounded-full font-mono">${idx + 1}</span>
                                        <span class="text-xs font-bold text-slate-900 dark:text-slate-100">${escapeHtml(r.target_domain || 'Methodological Standard')}</span>
                                    </div>
                                    ${statusBadge}
                                </div>
                                ${headlineHtml}
                                ${explanationHtml}
                                ${citationsHtml}
                                <div class="flex flex-wrap items-center gap-3 text-[11px] text-slate-500 dark:text-slate-400 pt-2 border-t border-slate-100 dark:border-slate-800">
                                    ${r.citation ? `<span><strong class="text-slate-700 dark:text-slate-300 font-semibold">Guideline:</strong> ${escapeHtml(r.citation)}</span>` : ''}
                                    ${r.directional_bias ? `<span><strong class="text-rose-700 dark:text-rose-400 font-semibold">Directional Risk:</strong> ${escapeHtml(r.directional_bias)}</span>` : ''}
                                </div>
                            </div>
                        `;
                    }).join('');
                } else {
                    rulesListHtml = `
                        <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md p-4 text-xs text-slate-500 italic">
                            Standard methodological analysis framework rules applied.
                        </div>
                    `;
                }

                // 3. Deliberation & Chain of Thought (Clean Light Mode Theme)
                let thoughtBodyHtml = '';
                if (thought) {
                    thoughtBodyHtml = `
                        <div class="font-mono text-xs leading-relaxed max-h-[460px] overflow-y-auto whitespace-pre-wrap text-slate-700 bg-white p-4 rounded border border-slate-200 shadow-2xs select-text">
${escapeHtml(thought)}
                        </div>
                    `;
                } else {
                    thoughtBodyHtml = `
                        <div class="text-xs text-slate-600 bg-white p-4 rounded border border-slate-200 italic leading-relaxed">
                            <span class="text-sky-700 font-semibold not-italic">Direct Synthesis Mode:</span> The verified model evaluated the study and grounded bias rules directly against the manuscript coordinates without emitting a separate internal thought buffer.
                        </div>
                    `;
                }

                container.innerHTML = `
                    <!-- Card 1: Triage Assessment Rationale -->
                    <div class="bg-slate-50 border border-slate-200 rounded-lg p-5">
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-3 border-b border-slate-200 pb-2.5">
                            <div class="flex items-center gap-2">
                                <span class="text-sm font-bold text-slate-800">1. Deterministic Triage Rationale</span>
                                <span class="px-2.5 py-0.5 rounded text-xs font-semibold bg-sky-100 text-sky-800 border border-sky-200">${escapeHtml(fwName)}</span>
                            </div>
                            <span class="text-xs font-semibold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">${confPercent}% Confidence</span>
                        </div>
                        <p class="text-xs text-slate-700 leading-relaxed mb-3.5 bg-white p-3 rounded border border-slate-200/80">
                            ${escapeHtml(rationaleText)}
                        </p>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 text-xs">
                            <div>
                                <span class="text-[11px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Detected Clinical & Study Features</span>
                                <div class="flex flex-wrap gap-1.5">
                                    ${tagsHtml}
                                </div>
                            </div>
                            <div>
                                <span class="text-[11px] font-bold text-slate-500 uppercase tracking-wide block mb-1.5">Matched Keywords & Design Triggers</span>
                                <div class="flex flex-wrap gap-1.5">
                                    ${triggersHtml}
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Card 2: Methodological Bias Rules Audit -->
                    <div id="auditCard2" class="bg-slate-50 border border-slate-200 rounded-lg p-5">
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-3 border-b border-slate-200 pb-2.5">
                            <div class="flex items-center gap-2">
                                <span class="text-sm font-bold text-slate-800">2. Grounded Methodological Bias Rules Audit</span>
                                <span class="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-100 text-amber-900 border border-amber-200">${displayRules.length} Rules Active</span>
                            </div>
                            ${summaryTallyHtml}
                        </div>
                        <p class="text-xs text-slate-600 mb-3 leading-relaxed">
                            The following domain-specific methodological bias rules were triggered by AST logic and evaluated against manuscript coordinates:
                        </p>
                        <div class="space-y-3">
                            ${rulesListHtml}
                        </div>
                    </div>

                    <!-- Card 3: Model Deliberation & Chain of Thought (Clean Light Mode Theme) -->
                    <div class="bg-slate-50 border border-slate-200 rounded-lg p-5">
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-3 border-b border-slate-200 pb-2.5">
                            <div class="flex items-center gap-2">
                                <span class="text-sm font-bold text-slate-800">3. Synthesis Deliberation & Chain-of-Thought</span>
                            </div>
                            <span class="font-mono text-[11px] text-sky-800 bg-sky-50 px-2.5 py-0.5 rounded border border-sky-200 font-semibold">${escapeHtml(selectedModel)}</span>
                        </div>
                        ${thoughtBodyHtml}
                    </div>
                `;
            }

            let pendingResolution = null;
            let checkTimeout = null;

            // Real-time PubMed / PMC availability listener
            document.addEventListener('DOMContentLoaded', function() {
                const urlInput = document.getElementById('paperUrl');
                const notice = document.getElementById('availabilityNotice');
                if (!urlInput || !notice) return;

                urlInput.addEventListener('input', function() {
                    clearTimeout(checkTimeout);
                    const val = urlInput.value.trim();
                    if (!val || val.length < 5) {
                        notice.classList.add('hidden');
                        return;
                    }

                    const isLikelyPaper = /pubmed|\d{6,9}|PMC\d+|10\.\d{4,9}\//i.test(val);
                    if (!isLikelyPaper) {
                        notice.classList.add('hidden');
                        return;
                    }

                    notice.classList.remove('hidden');
                    notice.className = "p-2.5 rounded-lg text-xs flex items-center justify-between border bg-sky-50 border-sky-200 text-sky-800 transition-all";
                    notice.innerHTML = `
                        <div class="flex items-center gap-2">
                            <svg class="animate-spin h-3.5 w-3.5 text-sky-600" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
                            <span>Checking PubMed / PMC API for full-text availability...</span>
                        </div>
                    `;

                    checkTimeout = setTimeout(async () => {
                        try {
                            const fd = new FormData();
                            fd.append('url', val);
                            const r = await fetch('/check-url', { method: 'POST', body: fd });
                            const d = await r.json();

                            if (d.full_text_available) {
                                notice.className = "p-2.5 rounded-lg text-xs flex items-center justify-between border bg-emerald-50 border-emerald-300 text-emerald-900 transition-all";
                                notice.innerHTML = `
                                    <div class="flex items-center gap-2">
                                        <span class="text-emerald-600 font-bold text-sm">✓</span>
                                        <span><strong>Full Text Available:</strong> ${d.message || d.source_type}</span>
                                    </div>
                                    <span class="px-2 py-0.5 rounded bg-emerald-200 text-emerald-900 font-semibold text-[11px]">Free Full Text</span>
                                `;
                            } else if (d.is_abstract_only) {
                                notice.className = "p-2.5 rounded-lg text-xs flex items-center justify-between border bg-amber-50 border-amber-300 text-amber-900 transition-all";
                                const isBlocked = d.publisher_blocked;
                                notice.innerHTML = `
                                    <div class="flex items-center gap-2">
                                        <span class="text-amber-600 font-bold text-sm">⚠️</span>
                                        <span><strong>${isBlocked ? 'Publisher Download Restriction:' : 'Full Text Unavailable:'}</strong> ${isBlocked ? 'Publisher blocks automated XML download. Full-text PDF available at link.' : 'Paywalled study. Only official abstract available in PubMed registry.'}</span>
                                    </div>
                                    <span class="px-2 py-0.5 rounded ${isBlocked ? 'bg-sky-200 text-sky-900' : 'bg-amber-200 text-amber-900'} font-semibold text-[11px]">${isBlocked ? 'Manual Download' : 'Abstract Only'}</span>
                                `;
                            } else {
                                notice.classList.add('hidden');
                            }
                        } catch (e) {
                            notice.classList.add('hidden');
                        }
                    }, 350);
                });
            });

            function closeAbstractModal() {
                document.getElementById('abstractModal').classList.add('hidden');
                pendingResolution = null;
                document.getElementById('resolveBtn').disabled = false;
                document.getElementById('statusBox').classList.add('hidden');
            }

            function switchToManualUpload() {
                closeAbstractModal();
                switchInputTab('pdf');
                const fileInput = document.getElementById('pdfFile');
                if (fileInput) {
                    fileInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // Automatically open the OS file selection dialog
                    setTimeout(() => {
                        fileInput.click();
                    }, 50);
                }
            }

            async function proceedWithAbstractOnly() {
                document.getElementById('abstractModal').classList.add('hidden');
                if (!pendingResolution || !pendingResolution.pdf_filename) return;
                
                await executeAppraisalForFilename(pendingResolution.pdf_filename, true);
            }

            async function startUrlResolution() {
                if (!currentUser) {
                    openAuthModal();
                    return;
                }
                if (!isApproved) {
                    const pendingModal = document.getElementById('pendingApprovalModal');
                    if (pendingModal) pendingModal.classList.remove('hidden');
                    return;
                }

                closeSectionPopup();
                const urlInput = document.getElementById('paperUrl');
                const rawUrl = urlInput.value.trim();
                if (!rawUrl) {
                    alert('Please enter a paper URL, PMC ID, PMID, or DOI.');
                    return;
                }

                // If user initiates URL resolution while in Finder or Contextualize, switch master mode to Analyze
                switchMasterMode('appraisal');

                const statusBox = document.getElementById('statusBox');
                const statusText = document.getElementById('statusText');
                const spinner = document.getElementById('spinner');
                const statusIcon = document.getElementById('statusIcon');
                const resultBox = document.getElementById('resultBox');
                const resolveBtn = document.getElementById('resolveBtn');

                statusBox.classList.remove('hidden');
                resultBox.classList.add('hidden');
                resolveBtn.disabled = true;

                // Step 1: Pre-check full-text availability via PubMed API
                statusText.innerHTML = '<span>Checking PubMed API for full-text availability...</span>';

                const formData = new FormData();
                formData.append('url', rawUrl);

                try {
                    const checkRes = await fetch('/check-url', { method: 'POST', body: formData });
                    const checkData = await checkRes.json();

                    if (checkData.full_text_available) {
                        statusText.innerHTML = `<span class="font-semibold text-emerald-700">✓ Full text available on ${checkData.source_type} (${checkData.pmcid || ''})!</span> Retrieving manuscript via PubMed API...`;
                    } else if (checkData.is_abstract_only) {
                        statusText.innerHTML = '<span class="font-semibold text-amber-700">Paywalled manuscript detected.</span> Retrieving abstract from PubMed registry...';
                    }

                    // Step 2: Fetch and format the manuscript PDF
                    const res = await fetch('/resolve-url', { method: 'POST', body: formData });
                    const data = await res.json();

                    if (data.status === 'error') {
                        throw new Error(data.message || 'Could not resolve or access URL.');
                    }

                    if (data.status === 'abstract_only') {
                        pendingResolution = data;
                        
                        const modalTitle = document.getElementById('abstractModalTitle');
                        const modalDesc = document.getElementById('abstractModalDesc');
                        const pubBox = document.getElementById('publisherLinkBox');
                        const pubLink = document.getElementById('publisherDirectLink');
                        const uploadBtn = document.getElementById('modalUploadBtn');
                        const modalPrompt = document.getElementById('abstractModalPrompt');
                        const scholarLink = document.getElementById('scholarSearchLink');

                        // Construct pre-filled Google Scholar query optimized for Scholar's citation & cluster grouping
                        if (scholarLink) {
                            const rawT = data.title || '';
                            const tBase = rawT.includes(':') ? rawT.split(':')[0] : rawT;
                            const cleanT = tBase.replace(/[^\w\s-]/g, ' ').replace(/\s+/g, ' ').trim();
                            const queryTerm = cleanT || (data.doi || (data.pmid ? 'PMID ' + data.pmid : ''));
                            scholarLink.href = 'https://scholar.google.com/scholar?hl=en&as_sdt=0%2C30&q=' + encodeURIComponent(queryTerm) + '&btnG=';
                        }

                        if (data.publisher_blocked) {
                            if (modalTitle) modalTitle.innerText = 'Publisher Download Restriction';
                            if (modalDesc) modalDesc.innerText = 'The publisher restricts automated API downloading of this article. However, the complete full-text PDF is available to download directly in your browser:';
                            if (pubBox) pubBox.classList.remove('hidden');
                            if (pubLink) {
                                pubLink.href = data.direct_url || (data.pmcid ? `https://pmc.ncbi.nlm.nih.gov/articles/${data.pmcid}/` : '#');
                                pubLink.innerText = `Open Article on PubMed Central (${data.pmcid || 'PMC'}) ↗`;
                            }
                            if (uploadBtn) uploadBtn.classList.remove('hidden');
                            if (modalPrompt) modalPrompt.innerText = 'Would you like to manually download & upload the PDF, or should F.A.C.T. analyze the official abstract only?';
                        } else {
                            if (modalTitle) modalTitle.innerText = 'Full Text Unavailable (Abstract Only)';
                            if (modalDesc) modalDesc.innerText = 'The requested URL or identifier does not have a free full-text manuscript available (likely behind a journal paywall). We retrieved the official published abstract.';
                            if (pubBox) pubBox.classList.add('hidden');
                            if (uploadBtn) uploadBtn.classList.add('hidden');
                            if (modalPrompt) modalPrompt.innerText = 'Would you like to analyze the abstract only?';
                        }

                        document.getElementById('modalAbstractSnippet').innerText = data.abstract_text || '(Abstract text extracted from publication registry)';
                        document.getElementById('abstractModal').classList.remove('hidden');
                        statusText.innerHTML = '<span class="text-amber-700 font-medium">⚠️ Abstract only available.</span> Awaiting user confirmation to analyze abstract...';
                        return;
                    }

                    // Full text PDF retrieved!
                    statusText.innerHTML = `<span class="font-semibold text-emerald-700">✓ ${data.message || 'Full text retrieved via PubMed API!'}</span> Starting analysis pipeline...`;
                    await executeAppraisalForFilename(data.pdf_filename, false);
                } catch (err) {
                    spinner.classList.add('hidden');
                    alert('Error: ' + err.message);
                    statusText.innerText = 'Failed: ' + err.message;
                    resolveBtn.disabled = false;
                }
            }

            async function executeAppraisalForFilename(filename, isAbstractOnly) {
                currentFilename = filename;

                // Immediately fetch PDF manifest and render all document pages so the user can read the paper while appraisal executes
                fetch(`/api/pdf-manifest?filename=${encodeURIComponent(filename)}`)
                    .then(r => r.json())
                    .then(manifest => {
                        if (manifest && manifest.total_pages) {
                            renderFullDocumentPages(manifest.filename, manifest.total_pages, manifest.pages);
                        }
                    }).catch(e => console.warn('Pre-viewer manifest note:', e));

                const statusBox = document.getElementById('statusBox');
                const statusText = document.getElementById('statusText');
                const spinner = document.getElementById('spinner');
                const statusIcon = document.getElementById('statusIcon');
                const resultBox = document.getElementById('resultBox');
                const resolveBtn = document.getElementById('resolveBtn');
                const runBtn = document.getElementById('runBtn');

                statusBox.classList.remove('hidden');
                statusText.innerText = isAbstractOnly ? 
                    'Extracting coordinates & analyzing Abstract...' : 
                    'Ingesting full text layout, triaging & synthesizing analysis...';

                const formData = new FormData();
                formData.append('filename', filename);
                if (currentUser) {
                    formData.append('user_uid', currentUser.uid);
                    formData.append('user_email', currentUser.email);
                }

                try {
                    const res = await fetch('/appraise-fetched', { method: 'POST', body: formData });
                    if (!res.ok) {
                        let errMsg = `Server returned status ${res.status}`;
                        try {
                            const errData = await res.json();
                            if (errData && errData.detail) errMsg = errData.detail;
                        } catch (_) {
                            const rawErrText = await res.text().catch(() => '');
                            if (res.status === 524 || rawErrText.includes('524')) {
                                errMsg = 'Gateway timeout: Cloudflare limit reached. If this is a large scanned PDF, processing may still complete on server.';
                            } else if (res.status === 502 || res.status === 504) {
                                errMsg = `Server Gateway Error (${res.status}). Please try again shortly.`;
                            }
                        }
                        throw new Error(errMsg);
                    }

                    const data = await res.json();
                    renderAppraisalResults(data);
                } catch (err) {
                    spinner.classList.add('hidden');
                    alert('Error: ' + err.message);
                    statusText.innerText = 'Failed: ' + err.message;
                } finally {
                    resolveBtn.disabled = false;
                    runBtn.disabled = false;
                }
            }

            // Configure Marked.js for external links to open in a new tab by default
            if (window.marked) {
                const renderer = new marked.Renderer();
                renderer.link = function(href, title, text) {
                    let linkHref = href;
                    let linkTitle = title;
                    let linkText = text;
                    if (typeof href === 'object' && href !== null) {
                        linkHref = href.href || '';
                        linkTitle = href.title || '';
                        linkText = href.text || linkHref;
                    }
                    const titleAttr = linkTitle ? ` title="${linkTitle}"` : ' title="Open link in new tab"';
                    return `<a href="${linkHref}"${titleAttr} target="_blank" rel="noopener noreferrer" class="doi-link">${linkText}</a>`;
                };
                if (marked.use) {
                    marked.use({ renderer: renderer, gfm: true, breaks: true });
                } else if (marked.setOptions) {
                    marked.setOptions({ renderer: renderer, gfm: true, breaks: true });
                }
            }

            function formatAnchorDisplay(str) {
                if (!str) return '';
                let text = str.replace(/^\[|\]$/g, '').trim();
                if (text.toLowerCase() === 'doc_header') return 'Header';
                text = text.replace(/^Introduction\b/i, 'Intro');
                text = text.replace(/^Abstract\b/i, 'Abs');
                text = text.replace(/^(?:Materials?\s+and\s+Methods?|Patients?\s+and\s+Methods?|Study\s+Design|Statistical\s+Analysis|Methods?)\b/i, 'Meth');
                text = text.replace(/^(?:Results?|Findings?|Efficacy|Safety)\b/i, 'Res');
                text = text.replace(/^Discussion\b/i, 'Disc');
                text = text.replace(/^(?:Conclusions?|Conclusion\s+and\s+Relevance)\b/i, 'Concl');
                text = text.replace(/^(?:Supplementary(?:\s+Material|\s+Appendix)?|Appendix)\b/i, 'Supp');
                text = text.replace(/\bPara\s*(\d+)/gi, 'p$1');
                return '[' + text + ']';
            }

            function expandAnchorShortName(anc) {
                if (!anc) return '';
                let s = anc.replace(/^\[|\]$/g, '').trim();
                s = s.replace(/^Abs\b/i, 'Abstract');
                s = s.replace(/^Intro\b/i, 'Introduction');
                s = s.replace(/^Meth\b/i, 'Methods');
                s = s.replace(/^Res\b/i, 'Results');
                s = s.replace(/^Disc\b/i, 'Discussion');
                s = s.replace(/^Concl\b/i, 'Conclusions');
                s = s.replace(/^Supp\b/i, 'Appendix');
                s = s.replace(/\bp(\d+)\b/gi, 'Para $1');
                return '[' + s + ']';
            }

            function getExportableAnalysisText() {
                let text = (window.ResearchAppState && window.ResearchAppState.lastAppraisalMarkdown) 
                    ? window.ResearchAppState.lastAppraisalMarkdown 
                    : '';
                if (!text) {
                    const out = document.getElementById('outputMarkdown');
                    if (out) text = out.innerText.trim();
                }
                if (!text) return '';

                // Group consecutive coordinate anchor brackets so they export neatly demarcated as [Abs, p38; Abs, p39; Abs, p41]
                const consecutiveCoordGroupRegex = /(\[\s*[^[\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Results?|Res|Disc(?:ussion)?|Concl(?:usions?)?|Conc|Para(?:graph)?|Table(?:Note)?|Fig(?:Legend)?|Box|p\d+)\b[^\]]*?\](?:\s*\[\s*[^[\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Results?|Res|Disc(?:ussion)?|Concl(?:usions?)?|Conc|Para(?:graph)?|Table(?:Note)?|Fig(?:Legend)?|Box|p\d+)\b[^\]]*?\])*)/gi;
                text = text.replace(consecutiveCoordGroupRegex, function(fullMatch) {
                    const singleBracketRe = /\[\s*([^[\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Results?|Res|Disc(?:ussion)?|Concl(?:usions?)?|Conc|Para(?:graph)?|Table(?:Note)?|Fig(?:Legend)?|Box|p\d+)\b[^\]]*?)\s*\]/gi;
                    const items = [];
                    let match;
                    while ((match = singleBracketRe.exec(fullMatch)) !== null) {
                        const trimmed = match[1].trim();
                        if (trimmed.toLowerCase() === 'doc_header' || trimmed.toLowerCase() === 'header') {
                            items.push('Header');
                            continue;
                        }
                        let rawParts = [];
                        if (trimmed.includes(';')) {
                            rawParts = trimmed.split(';').map(p => p.trim()).filter(Boolean);
                        } else {
                            rawParts = trimmed.split(/,\s*(?=[A-Za-z\s]+,\s*(?:Para(?:graph)?|Table(?:Note)?|Fig(?:Legend)?|Box|p\d+))/i).map(p => p.trim()).filter(Boolean);
                        }
                        if (!rawParts || rawParts.length === 0) {
                            rawParts = [trimmed];
                        }
                        for (const p of rawParts) {
                            const multiParaMatch = p.match(/^([A-Za-z\s&]+?),\s*Para\s+(\d+(?:,\s*\d+)+)$/i);
                            if (multiParaMatch) {
                                const sec = multiParaMatch[1].trim();
                                const nums = multiParaMatch[2].split(',').map(n => n.trim()).filter(Boolean);
                                for (const num of nums) {
                                    items.push(formatAnchorDisplay(sec + ", Para " + num).replace(/^\[|\]$/g, ''));
                                }
                            } else {
                                items.push(formatAnchorDisplay(p).replace(/^\[|\]$/g, ''));
                            }
                        }
                    }
                    if (items.length === 0) return fullMatch;
                    return '[' + items.join('; ') + ']';
                });

                return text.replace(/[ \t]{2,}/g, ' ').trim();
            }

            // -------------------------------------------------------------
            // Consolidated Export & WordPress Conversion Engine
            // -------------------------------------------------------------
            function toggleExportMenu(e) {
                if (e) e.stopPropagation();
                const dd = document.getElementById('exportMenuDropdown');
                if (dd) dd.classList.toggle('hidden');
            }

            function closeExportMenu() {
                const dd = document.getElementById('exportMenuDropdown');
                if (dd) dd.classList.add('hidden');
            }

            document.addEventListener('click', function(e) {
                const wrapper = document.getElementById('exportDropdownWrapper');
                if (wrapper && !wrapper.contains(e.target)) {
                    closeExportMenu();
                }
            });

            function getRawAppraisalMarkdown() {
                let text = (window.ResearchAppState && window.ResearchAppState.lastAppraisalMarkdown) 
                    ? window.ResearchAppState.lastAppraisalMarkdown 
                    : '';
                if (!text) {
                    const out = document.getElementById('outputMarkdown');
                    if (out) text = out.innerText.trim();
                }
                return text || '';
            }

            function getClinicianCommentaryText() {
                const ta = document.getElementById('commentaryTextarea');
                return ta ? ta.value.trim() : '';
            }

            function formatAnalysisForWordPress(asFullHtmlDocument = false) {
                let markdown = getRawAppraisalMarkdown();
                if (!markdown) return '';

                const includeCommentary = document.getElementById('exportIncludeCommentary')?.checked;
                const commentaryText = includeCommentary ? getClinicianCommentaryText() : '';

                // 1. Clean LaTeX math macros and strip {R_...} tags
                markdown = markdown.replace(/\s*\{R_[A-Z0-9_]+\}/g, '').replace(/\s*\[R_[A-Z0-9_]+\]/g, '');
                markdown = markdown.replace(/(\[[^\]]*?\b)Paragraphs?\b/gi, '$1Para');

                // Determine export theme styling based on user's active highlight/theme preference
                const activeColor = (typeof currentHighlightColor !== 'undefined' && currentHighlightColor)
                    ? currentHighlightColor
                    : (localStorage.getItem('fact_highlight_color') || 'blue');

                // Harmonious WordPress export palettes for each theme option
                const exportThemeMap = {
                    emerald: { header: '#047857', pillText: '#065f46', pillBg: '#ecfdf5', pillBorder: '#6ee7b7' },
                    amber:   { header: '#b45309', pillText: '#92400e', pillBg: '#fffbeb', pillBorder: '#fcd34d' },
                    teal:    { header: '#0f766e', pillText: '#115e59', pillBg: '#f0fdfa', pillBorder: '#5eead4' },
                    indigo:  { header: '#4338ca', pillText: '#3730a3', pillBg: '#eef2ff', pillBorder: '#a5b4fc' },
                    violet:  { header: '#6d28d9', pillText: '#5b21b6', pillBg: '#f5f3ff', pillBorder: '#c4b5fd' },
                    rose:    { header: '#be123c', pillText: '#9f1239', pillBg: '#fff1f2', pillBorder: '#fda4af' },
                    slate:   { header: '#334155', pillText: '#1e293b', pillBg: '#f8fafc', pillBorder: '#cbd5e1' },
                    blue:    { header: '#0369a1', pillText: '#0369a1', pillBg: '#f0f9ff', pillBorder: '#7dd3fc' }
                };
                const themeTheme = exportThemeMap[activeColor] || exportThemeMap.blue;

                // 2. Convert coordinate anchor citations into static, beautiful inline badge pills
                const pillStyle = `display:inline-block; padding:1px 6px; margin:0 2px; font-size:11px; font-weight:600; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; color:${themeTheme.pillText}; background-color:${themeTheme.pillBg}; border:1px solid ${themeTheme.pillBorder}; border-radius:4px; line-height:1.3; vertical-align:baseline; white-space:nowrap; text-decoration:none;`;
                
                const bracketCoordRegex = /\[([^\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Patients?\s+and\s+Methods?|Materials?\s+and\s+Methods?|Results?|Res|Findings?|Discussion|Disc|Conclusions?|Concl|Appendix|Supp(?:lementary)?|Para(?:graph)?|Table(?:Note)?|Fig(?:ure)?(?:Legend)?|Box|p\d+)\b[^\]]*?)\]/gi;
                
                markdown = markdown.replace(bracketCoordRegex, function(fullMatch, inner) {
                    const cleanText = formatAnchorDisplay(inner.trim());
                    return `###FACT_PILL_START###${escapeHtml(cleanText)}###FACT_PILL_END###`;
                });

                // 3. Line by line parsing to semantic HTML
                const lines = markdown.split('\n');
                let htmlOut = [];
                let inList = false;

                for (let i = 0; i < lines.length; i++) {
                    let line = lines[i].trim();
                    if (!line) {
                        if (inList) {
                            htmlOut.push('</ul>');
                            inList = false;
                        }
                        continue;
                    }

                    // Headers
                    if (line.startsWith('# ')) {
                        if (inList) { htmlOut.push('</ul>'); inList = false; }
                        const title = line.replace(/^#\s+/, '').replace(/\*\*/g, '');
                        htmlOut.push(`<h2 style="font-size:22px; font-weight:800; color:#0f172a; margin-top:0; margin-bottom:14px; line-height:1.3; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">${escapeHtml(title)}</h2>`);
                        continue;
                    }
                    if (line.startsWith('## ')) {
                        if (inList) { htmlOut.push('</ul>'); inList = false; }
                        const h2 = line.replace(/^##\s+/, '').replace(/\*\*/g, '');
                        htmlOut.push(`<h3 style="font-size:17px; font-weight:700; color:${themeTheme.header}; margin-top:24px; margin-bottom:10px; line-height:1.4; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">${escapeHtml(h2)}</h3>`);
                        continue;
                    }
                    if (line.startsWith('### ')) {
                        if (inList) { htmlOut.push('</ul>'); inList = false; }
                        const h3 = line.replace(/^###\s+/, '').replace(/\*\*/g, '');
                        htmlOut.push(`<h4 style="font-size:14px; font-weight:700; color:#1e293b; margin-top:16px; margin-bottom:8px; line-height:1.4; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">${escapeHtml(h3)}</h4>`);
                        continue;
                    }

                    // Unordered list item
                    if (/^[-*•]\s+/.test(line)) {
                        if (!inList) {
                            htmlOut.push('<ul style="margin:8px 0 16px 20px; padding:0; font-size:14px; line-height:1.65; color:#334155; font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;">');
                            inList = true;
                        }
                        let itemContent = line.replace(/^[-*•]\s+/, '');
                        itemContent = formatInlineFormatting(itemContent);
                        htmlOut.push(`<li style="margin-bottom:6px;">${itemContent}</li>`);
                        continue;
                    }

                    // Standard paragraph
                    if (inList) {
                        htmlOut.push('</ul>');
                        inList = false;
                    }
                    let pContent = formatInlineFormatting(line);
                    htmlOut.push(`<p style="font-size:14px; line-height:1.65; color:#334155; margin-top:0; margin-bottom:14px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">${pContent}</p>`);
                }
                if (inList) {
                    htmlOut.push('</ul>');
                }

                function formatInlineFormatting(str) {
                    // Replace bold **text**
                    let s = str.replace(/\*\*([^*]+)\*\*/g, '<strong style="color:#0f172a; font-weight:700;">$1</strong>');
                    // Replace italic *text*
                    s = s.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
                    // Replace pills placeholder
                    s = s.replace(/###FACT_PILL_START###(.*?)###FACT_PILL_END###/g, function(match, inner) {
                        return `<span class="fact-pill" style="${pillStyle}">${inner}</span>`;
                    });
                    return s;
                }

                let bodyHtml = htmlOut.join('\n');

                // Optional Clinician Commentary Box prepended
                if (commentaryText) {
                    const commentaryParagraphs = commentaryText.split('\n\n').map(p => {
                        let formattedP = formatInlineFormatting(p.trim());
                        return `<p style="margin-top:0; margin-bottom:10px; font-size:14px; line-height:1.65; color:#1e293b; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">${formattedP}</p>`;
                    }).join('');

                    const commentaryBox = `
<div class="fact-commentary-box" style="background-color:#f8fafc; border-left:4px solid ${themeTheme.header}; border-top:1px solid #e2e8f0; border-right:1px solid #e2e8f0; border-bottom:1px solid #e2e8f0; padding:16px 20px; margin-bottom:24px; border-radius:0 8px 8px 0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <div style="font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:0.06em; color:${themeTheme.header}; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
        <span>✍️</span> <span>Clinician Editorial Commentary</span>
    </div>
    <div style="font-style:italic;">
        ${commentaryParagraphs}
    </div>
</div>
`;
                    bodyHtml = commentaryBox + bodyHtml;
                }

                // Scoped CSS styles for complete theme immunity in WordPress
                const embeddedStyle = `
<style>
.fact-clinical-review { max-width:820px; margin:0 auto; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; text-rendering:optimizeLegibility; -webkit-font-smoothing:antialiased; color:#334155; line-height:1.65; }
.fact-clinical-review h2 { font-size:22px !important; font-weight:800 !important; color:#0f172a !important; margin-top:0 !important; margin-bottom:14px !important; line-height:1.3 !important; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif !important; border:none !important; }
.fact-clinical-review h3 { font-size:17px !important; font-weight:700 !important; color:${themeTheme.header} !important; margin-top:24px !important; margin-bottom:10px !important; line-height:1.4 !important; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif !important; border:none !important; }
.fact-clinical-review h4 { font-size:14px !important; font-weight:700 !important; color:#1e293b !important; margin-top:16px !important; margin-bottom:8px !important; line-height:1.4 !important; }
.fact-clinical-review p { font-size:14px !important; line-height:1.65 !important; color:#334155 !important; margin-top:0 !important; margin-bottom:14px !important; }
.fact-clinical-review ul { margin:8px 0 16px 20px !important; padding:0 !important; font-size:14px !important; line-height:1.65 !important; color:#334155 !important; }
.fact-clinical-review li { margin-bottom:6px !important; }
.fact-clinical-review strong { color:#0f172a !important; font-weight:700 !important; }
.fact-clinical-review .fact-pill { display:inline-block !important; padding:1px 6px !important; margin:0 2px !important; font-size:11px !important; font-weight:600 !important; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif !important; color:${themeTheme.pillText} !important; background-color:${themeTheme.pillBg} !important; border:1px solid ${themeTheme.pillBorder} !important; border-radius:4px !important; line-height:1.3 !important; vertical-align:baseline !important; white-space:nowrap !important; text-decoration:none !important; }
.fact-clinical-review .fact-commentary-box { background-color:#f8fafc !important; border:1px solid #e2e8f0 !important; border-left:4px solid ${themeTheme.header} !important; padding:16px 20px !important; margin-bottom:24px !important; border-radius:0 8px 8px 0 !important; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif !important; }
</style>`;

                // Wrap in scoped container and native Gutenberg block comment
                const scopedHtml = `<!-- wp:html -->\n${embeddedStyle}\n<div class="fact-clinical-review">\n${bodyHtml}\n</div>\n<!-- /wp:html -->`;

                if (asFullHtmlDocument) {
                    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Clinical Research Appraisal</title>
<style>
body { background: #ffffff; color: #334155; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 24px; margin: 0; }
</style>
</head>
<body>
${scopedHtml}
</body>
</html>`;
                }

                return scopedHtml;
            }

            async function handleExportAction(action) {
                closeExportMenu();
                const rawMarkdown = getRawAppraisalMarkdown();
                if (!rawMarkdown) {
                    alert('No clinical analysis available to export. Please run an appraisal on a paper first.');
                    return;
                }

                let baseName = (window.ResearchAppState && window.ResearchAppState.lastAppraisalFilename)
                    ? window.ResearchAppState.lastAppraisalFilename
                    : 'clinical_analysis';
                baseName = baseName.replace(/\.pdf$/i, '').replace(/[^a-zA-Z0-9_\-\s]/g, '').trim().replace(/\s+/g, '_');

                const menuBtnText = document.getElementById('exportMenuBtnText');
                function showToast(msg) {
                    if (menuBtnText) {
                        const orig = menuBtnText.innerText;
                        menuBtnText.innerText = msg;
                        setTimeout(() => { menuBtnText.innerText = orig; }, 2200);
                    }
                }

                if (action === 'wp_visual') {
                    // Copy rich text/html directly to clipboard for direct Ctrl+V into Gutenberg
                    try {
                        const htmlContent = formatAnalysisForWordPress(false);
                        const plainText = getExportableAnalysisText();

                        if (navigator.clipboard && window.ClipboardItem) {
                            const blobHtml = new Blob([htmlContent], { type: 'text/html' });
                            const blobText = new Blob([plainText], { type: 'text/plain' });
                            const item = new ClipboardItem({
                                'text/html': blobHtml,
                                'text/plain': blobText
                            });
                            await navigator.clipboard.write([item]);
                            showToast('✓ Copied for WordPress!');
                        } else {
                            // Fallback
                            await navigator.clipboard.writeText(htmlContent);
                            showToast('✓ HTML Copied!');
                        }
                    } catch (err) {
                        console.warn("ClipboardItem write error, falling back:", err);
                        const htmlContent = formatAnalysisForWordPress(false);
                        await navigator.clipboard.writeText(htmlContent);
                        showToast('✓ HTML Copied!');
                    }
                } else if (action === 'wp_html') {
                    // Copy pure HTML string for WordPress Custom HTML block
                    const htmlCode = formatAnalysisForWordPress(false);
                    await navigator.clipboard.writeText(htmlCode);
                    showToast('✓ HTML Code Copied!');
                } else if (action === 'wp_download') {
                    // Download WordPress standalone HTML file
                    const fullHtml = formatAnalysisForWordPress(true);
                    const blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8;' });
                    downloadBlob(blob, `${baseName}_wordpress.html`);
                    showToast('✓ HTML Downloaded!');
                } else if (action === 'copy_markdown') {
                    // Standard clean markdown
                    const mdText = getExportableAnalysisText();
                    await navigator.clipboard.writeText(mdText);
                    showToast('✓ Markdown Copied!');
                } else if (action === 'copy_text') {
                    // Plain text stripped of markdown
                    let plain = getExportableAnalysisText();
                    plain = plain.replace(/^#+\s+/gm, '').replace(/\*\*([^*]+)\*\*/g, '$1');
                    await navigator.clipboard.writeText(plain);
                    showToast('✓ Plain Text Copied!');
                } else if (action === 'download_markdown') {
                    // Download .md file
                    const mdText = getExportableAnalysisText();
                    const blob = new Blob([mdText], { type: 'text/markdown;charset=utf-8;' });
                    downloadBlob(blob, `${baseName}_analysis.md`);
                    showToast('✓ .md Downloaded!');
                }
            }

            function downloadBlob(blob, filename) {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }

            function copyExportedAnalysis() {
                handleExportAction('copy_markdown');
            }

            function downloadExportedAnalysis() {
                handleExportAction('download_markdown');
            }

            function renderAnchoredMarkdown(rawText) {
                if (!rawText) return '';
                let content = rawText;
                // Strip raw {R_...} or [R_...] rule tags if emitted by model
                content = content.replace(/\s*\{R_[A-Z0-9_]+\}/g, '').replace(/\s*\[R_[A-Z0-9_]+\]/g, '');
                // Normalize any model variations like "Paragraph" -> "Para" in citations
                content = content.replace(/(\[[^\]]*?\b)Paragraphs?\b/gi, '$1Para');

                // Clean any raw LaTeX math formatting or macros emitted by the model
                function cleanLatexMath(str) {
                    if (!str) return '';
                    let t = str;
                    t = t.replace(/\\(?:text|mathrm|mathbf|mathit|mathsf)\{([^}]+)\}/g, '$1');
                    t = t.replace(/\^\+/g, '⁺').replace(/\^\-/g, '⁻').replace(/\^2/g, '²').replace(/\^3/g, '³').replace(/\^0/g, '⁰').replace(/\^1/g, '¹');
                    const greek = {
                        '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ', '\\epsilon': 'ε',
                        '\\theta': 'θ', '\\lambda': 'λ', '\\mu': 'μ', '\\pi': 'π', '\\sigma': 'σ',
                        '\\tau': 'τ', '\\phi': 'φ', '\\chi': 'χ', '\\omega': 'ω', '\\pm': '±',
                        '\\times': '×', '\\geq': '≥', '\\ge': '≥', '\\leq': '≤', '\\le': '≤',
                        '\\neq': '≠', '\\approx': '≈', '\\infty': '∞', '\\rightarrow': '→', '\\to': '→'
                    };
                    for (const [k, v] of Object.entries(greek)) {
                        t = t.replace(new RegExp(k.replace('\\', '\\\\') + '\\b', 'g'), v);
                    }
                    t = t.replace(/\$\$([^\$]+?)\$\$/g, '$1');
                    t = t.replace(/\$([^\$\n]+?)\$/g, '$1');
                    t = t.replace(/\\([a-zA-Z]+)/g, '$1');
                    return t;
                }
                content = cleanLatexMath(content);

                if (!window.marked) {
                    return escapeHtml(content);
                }

                let html = marked.parse(content);
                // Match coordinate blocks, supporting single, multi-paragraph, and compound citations
                // Expanded to include Doc_Header, Header, Abstract, Intro, Methods, Results, Disc, Concl, Para, Table, Fig, Box, p\d+
                const bracketCoordRegex = /\[([^\]]*?\b(?:Doc_Header|Header|Abstract|Abs|Intro(?:duction)?|Methods?|Meth|Patients?\s+and\s+Methods?|Materials?\s+and\s+Methods?|Results?|Res|Findings?|Discussion|Disc|Conclusions?|Concl|Appendix|Supp(?:lementary)?|Para(?:graph)?|Table(?:Note)?|Fig(?:ure)?(?:Legend)?|Box|p\d+)\b[^\]]*?)\]/gi;
                html = html.replace(bracketCoordRegex, function(fullMatch, inner) {
                    const trimmed = inner.trim();
                    if (trimmed.toLowerCase() === 'doc_header' || trimmed.toLowerCase() === 'header') {
                        const enc = encodeURIComponent('[Doc_Header]');
                        return `<button onclick="inspectAnchor('${enc}')" data-anchor="[Doc_Header]" class="anchor-pill inline-flex items-center px-1.5 py-0.5 mx-0.5 text-[11px] font-sans font-medium bg-sky-50 dark:bg-sky-950/70 text-sky-800 dark:text-sky-300 hover:bg-sky-600 hover:text-white border border-sky-300/80 dark:border-sky-800 rounded shadow-2xs leading-none" title="Click to view source page and highlight">Header</button>`;
                    }

                    // Split compound coordinates by semicolon first, or by section-boundary comma
                    let rawParts = [];
                    if (trimmed.includes(';')) {
                        rawParts = trimmed.split(';').map(p => p.trim()).filter(Boolean);
                    } else {
                        rawParts = trimmed.split(/,\s*(?=[A-Za-z\s]+,\s*(?:Para(?:graph)?|Table(?:Note)?|Fig(?:ure)?(?:Legend)?|Box|p\d+))/i).map(p => p.trim()).filter(Boolean);
                    }

                    if (!rawParts || rawParts.length === 0) {
                        rawParts = [trimmed];
                    }

                    let parts = [];
                    for (const p of rawParts) {
                        // Expand multi-paragraph list: e.g. "Methods, Para 1, 13" -> "Methods, Para 1", "Methods, Para 13"
                        const multiParaMatch = p.match(/^([A-Za-z\s&]+?)\s*,\s*Para\s+(\d+(?:\s*,\s*\d+)+)$/i);
                        if (multiParaMatch) {
                            const sec = multiParaMatch[1].trim();
                            const nums = multiParaMatch[2].split(',').map(n => n.trim()).filter(Boolean);
                            for (const num of nums) {
                                parts.push(`${sec}, Para ${num}`);
                            }
                        } else {
                            parts.push(p);
                        }
                    }

                    const buttons = parts.map(part => {
                        const rawAnchorId = `[${part}]`;
                        const enc = encodeURIComponent(rawAnchorId);
                        const displayText = formatAnchorDisplay(part);
                        return `<button onclick="inspectAnchor('${enc}')" data-anchor="${rawAnchorId}" class="anchor-pill inline-flex items-center px-1.5 py-0.5 mx-0.5 text-[11px] font-sans font-medium bg-sky-50 dark:bg-sky-950/70 text-sky-800 dark:text-sky-300 hover:bg-sky-600 hover:text-white border border-sky-300/80 dark:border-sky-800 rounded shadow-2xs leading-none" title="Click to view source page and highlight">${displayText}</button>`;
                    });

                    return buttons.join(' ');
                });

                return html;
            }

            function openThinkingModalToCard(cardIdx) {
                switchLeftTab('thinking');
                if (cardIdx === 2) {
                    setTimeout(() => {
                        const card2 = document.getElementById('auditCard2');
                        if (card2) card2.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }, 80);
                }
            }

            function injectMethodologicalScorecard(container, evaluations) {
                if (!container) return;
                // Remove any pre-existing scorecard for idempotency
                const existing = container.querySelector('#methodologicalAuditScorecard');
                if (existing) existing.remove();

                if (!evaluations || !Array.isArray(evaluations) || evaluations.length === 0) {
                    return;
                }

                const passCount = evaluations.filter(e => (e.status || '').toUpperCase() === 'PASS').length;
                const failCount = evaluations.filter(e => (e.status || '').toUpperCase() === 'FAIL').length;
                const naCount = evaluations.filter(e => ['NOT_AVAILABLE', 'PENDING', 'UNKNOWN'].includes((e.status || '').toUpperCase())).length;

                const scorecard = document.createElement('div');
                scorecard.id = 'methodologicalAuditScorecard';
                scorecard.className = 'my-4 p-3.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 shadow-2xs flex flex-wrap items-center justify-between gap-3 select-none';

                let badgesHtml = `
                    <span class="px-2 py-0.5 rounded font-semibold text-[11px] bg-emerald-100 text-emerald-800 dark:bg-emerald-950/70 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 flex items-center gap-1">
                        <span class="font-bold">✓</span> ${passCount} Compliant
                    </span>
                `;
                if (failCount > 0) {
                    badgesHtml += `
                    <span class="px-2 py-0.5 rounded font-semibold text-[11px] bg-rose-100 text-rose-800 dark:bg-rose-950/70 dark:text-rose-300 border border-rose-200 dark:border-rose-800 flex items-center gap-1">
                        <span class="font-bold">✗</span> ${failCount} ${failCount === 1 ? 'Deviation' : 'Deviations'}
                    </span>`;
                }
                if (naCount > 0) {
                    badgesHtml += `
                    <span class="px-2 py-0.5 rounded font-semibold text-[11px] bg-amber-100 text-amber-800 dark:bg-amber-950/70 dark:text-amber-300 border border-amber-200 dark:border-amber-800 flex items-center gap-1">
                        <span class="font-bold">?</span> ${naCount} Not Reported
                    </span>`;
                }

                scorecard.innerHTML = `
                    <div class="flex flex-wrap items-center gap-2 text-xs">
                        <span class="font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                            <svg class="w-4 h-4 text-sky-600 dark:text-sky-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                            Methodological Audit:
                        </span>
                        ${badgesHtml}
                    </div>
                    <button type="button" onclick="openThinkingModalToCard(2)" class="text-xs font-semibold text-sky-600 dark:text-sky-400 hover:text-sky-800 dark:hover:text-sky-200 flex items-center gap-1 cursor-pointer transition">
                        Inspect Full Audit Trail &rarr;
                    </button>
                `;

                // Post-Render DOM Insertion: insertBefore target <h2>
                const headings = container.querySelectorAll('h2');
                const targetH2 = Array.from(headings).find(h => /Assertive Critical Appraisal/i.test(h.textContent));
                if (targetH2 && targetH2.parentNode) {
                    targetH2.parentNode.insertBefore(scorecard, targetH2);
                } else {
                    container.appendChild(scorecard);
                }
            }

            function renderAppraisalResults(data) {
                anchorIndex = data.anchor_index || {};

                // Update Study Wonk Header Badge and Tooltip
                const badgeWrapper = document.getElementById('studyBadgeWrapper');
                const badgeText = document.getElementById('studyBadgeText');
                const tipFw = document.getElementById('tooltipFwId');
                const tipRules = document.getElementById('tooltipRulesCount');
                const tipDesc = document.getElementById('tooltipFwDesc');
                const tipList = document.getElementById('tooltipRulesList');

                if (badgeWrapper && data.triage) {
                    badgeWrapper.classList.remove('hidden');
                    const fwName = data.triage.framework_name || 'Clinical Study';
                    const fwId = data.triage.primary_framework_id || 'FW';
                    const applicableRules = data.triage.applicable_rules || [];

                    badgeText.innerText = fwName;
                    if (tipFw) tipFw.innerText = fwName;
                    if (tipRules) tipRules.innerText = applicableRules.length + ' Rules Triggered';
                    if (tipDesc) tipDesc.innerText = data.triage.description || 'Deterministic bias auditing rules tailored to this study design.';

                    if (tipList) {
                        const rulesList = (data.active_rules_detail && data.active_rules_detail.length > 0)
                            ? data.active_rules_detail.map(r => `<li><span class="text-sky-200 font-medium">${escapeHtml(r.target_domain || r.rule_id)}</span></li>`).join('')
                            : (applicableRules.length > 0 
                                ? applicableRules.map(r => `<li><span class="text-sky-200 font-medium">${escapeHtml(r)}</span></li>`).join('')
                                : '<li>Standard critical analysis framework</li>');
                        tipList.innerHTML = rulesList;
                    }
                }

                let content = data.final_markdown || data.raw_output || '';

                // Ensure study title and 'Clinical Bottom Line' have proper bold/header markdown
                const contentLines = content.trim().split('\n');
                if (contentLines.length > 0) {
                    let firstNonEmptyIdx = contentLines.findIndex(l => l.trim().length > 0);
                    if (firstNonEmptyIdx !== -1) {
                        let firstLine = contentLines[firstNonEmptyIdx].trim();
                        let rawTitle = firstLine.replace(/^#+\s*/, '').replace(/^\*\*|\*\*$/g, '').trim();
                        if (rawTitle.startsWith('[') && rawTitle.endsWith(']')) {
                            rawTitle = rawTitle.slice(1, -1).trim();
                        }
                        contentLines[firstNonEmptyIdx] = '# ' + rawTitle;
                    }
                    for (let i = 0; i < contentLines.length; i++) {
                        let trimmedLine = contentLines[i].trim();
                        if (/^(?:#*\s*)?\*\*?Clinical Bottom Line\*\*?:?$/i.test(trimmedLine) || trimmedLine.toLowerCase() === 'clinical bottom line') {
                            contentLines[i] = '## Clinical Bottom Line';
                        }
                    }
                    content = contentLines.join('\n');
                }

                // Cache normalized appraisal markdown and filename for clean export
                if (window.ResearchAppState) {
                    window.ResearchAppState.lastAppraisalMarkdown = content;
                    window.ResearchAppState.lastAppraisalFilename = currentFilename || 'clinical_analysis';
                    window.ResearchAppState.lastAppraisalData = data;
                }

                const container = document.getElementById('outputMarkdown');
                if (container) {
                    container.innerHTML = renderAnchoredMarkdown(content);

                    // Ensure all <a> tags open in a new tab
                    container.querySelectorAll('a').forEach(a => {
                        a.setAttribute('target', '_blank');
                        a.setAttribute('rel', 'noopener noreferrer');
                        a.classList.add('doi-link');
                        if (!a.getAttribute('title')) {
                            a.setAttribute('title', 'Open in new tab');
                        }
                    });

                    // Convert unlinked DOI/PubMed text
                    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null, false);
                    const nodesToReplace = [];
                    while (walker.nextNode()) {
                        const node = walker.currentNode;
                        if (node.parentElement && (node.parentElement.tagName === 'A' || node.parentElement.tagName === 'BUTTON')) continue;
                        if (/https?:\/\/(?:dx\.)?doi\.org\/[^\s\)]+|10\.\d{4,9}\/[^\s\)]+|https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/\d+/i.test(node.nodeValue)) {
                            nodesToReplace.push(node);
                        }
                    }

                    nodesToReplace.forEach(node => {
                        const span = document.createElement('span');
                        span.innerHTML = node.nodeValue.replace(/(https?:\/\/(?:dx\.)?doi\.org\/[^\s\)]+)|(10\.\d{4,9}\/[^\s\)]+)|(https?:\/\/pubmed\.ncbi\.nlm\.nih\.gov\/\d+\/?)/gi, function(match, fullDoi, rawDoi, pubmedUrl) {
                            const url = fullDoi || pubmedUrl || ('https://doi.org/' + rawDoi);
                            return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="doi-link" title="Open in new tab">${match}</a>`;
                        });
                        node.parentNode.replaceChild(span, node);
                    });

                    // Injected Methodological Audit Scorecard strictly post-render
                    injectMethodologicalScorecard(container, data.rule_evaluations);
                }

                // Reset Ask conversational interface for new paper
                resetAskChat();

                // Populate Thinking & Audit Trail view (Behavior 3)
                renderThinkingAudit(data);
                switchLeftTab('appraisal');

                // Switch master mode to appraisal to guarantee Finder / Contextualize containers are hidden
                switchMasterMode('appraisal');

                document.getElementById('resultBox').classList.remove('hidden');
                document.getElementById('statusBox').classList.add('hidden');

                if (data.total_pages) {
                    renderFullDocumentPages(currentFilename, data.total_pages);
                }

                // Smoothly scroll down to the split workspace
                const splitContainer = document.getElementById('splitContainer');
                if (splitContainer) {
                    splitContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }

                const firstPill = document.querySelector('.anchor-pill');
                if (firstPill) {
                    firstPill.click();
                }
            }

            async function startAppraisal() {
                if (!currentUser) {
                    openAuthModal();
                    return;
                }
                if (!isApproved) {
                    const pendingModal = document.getElementById('pendingApprovalModal');
                    if (pendingModal) pendingModal.classList.remove('hidden');
                    return;
                }

                closeSectionPopup();
                const fileInput = document.getElementById('pdfFile');
                if (!fileInput.files[0]) {
                    alert('Please select a PDF file to analyze.');
                    return;
                }

                // If user initiates appraisal while in Finder or Contextualize, switch master mode to Analyze
                switchMasterMode('appraisal');

                currentFilename = fileInput.files[0].name;

                const statusBox = document.getElementById('statusBox');
                const statusText = document.getElementById('statusText');
                const spinner = document.getElementById('spinner');
                const statusIcon = document.getElementById('statusIcon');
                const resultBox = document.getElementById('resultBox');
                const runBtn = document.getElementById('runBtn');

                statusBox.classList.remove('hidden');
                resultBox.classList.add('hidden');
                runBtn.disabled = true;
                statusText.innerText = 'Uploading manuscript & preparing document layout...';

                try {
                    // Step 1: Upload once to initialize viewer and guarantee file is saved to server
                    const uploadForm = new FormData();
                    uploadForm.append('file', fileInput.files[0]);
                    const initRes = await fetch('/api/init-pdf-viewer', { method: 'POST', body: uploadForm });
                    if (!initRes.ok) {
                        throw new Error(`Upload failed with status ${initRes.status}`);
                    }
                    const initData = await initRes.json();
                    if (initData && initData.total_pages) {
                        renderFullDocumentPages(initData.filename, initData.total_pages, initData.pages);
                    }

                    // Step 2: Run appraisal pipeline on the saved server file via /appraise-fetched
                    statusText.innerText = 'Extracting PDF layout, triaging & synthesizing analysis...';
                    const appraiseForm = new FormData();
                    appraiseForm.append('filename', initData.filename);
                    if (currentUser) {
                        appraiseForm.append('user_uid', currentUser.uid);
                        appraiseForm.append('user_email', currentUser.email);
                    }

                    const res = await fetch('/appraise-fetched', { method: 'POST', body: appraiseForm });
                    if (!res.ok) {
                        let errMsg = `Server returned status ${res.status}`;
                        try {
                            const errData = await res.json();
                            if (errData && errData.detail) errMsg = errData.detail;
                        } catch (_) {
                            const rawErrText = await res.text().catch(() => '');
                            if (res.status === 524 || rawErrText.includes('524')) {
                                errMsg = 'Gateway timeout: Cloudflare limit reached. If this is a large scanned PDF, processing may still complete on server.';
                            } else if (res.status === 502 || res.status === 504) {
                                errMsg = `Server Gateway Error (${res.status}). Please try again shortly.`;
                            }
                        }
                        throw new Error(errMsg);
                    }

                    const data = await res.json();
                    renderAppraisalResults(data);
                } catch (err) {
                    spinner.classList.add('hidden');
                    alert('Error: ' + err.message);
                    statusText.innerText = 'Failed: ' + err.message;
                } finally {
                    runBtn.disabled = false;
                }
            }

            // --- Interactive Conversational Interrogation ('Ask') Feature ---
            let askConversationHistory = [];

            function resetAskChat() {
                askConversationHistory = [];
                const feed = document.getElementById('askChatFeed');
                if (feed) {
                    feed.innerHTML = `
                        <div class="text-center p-6 text-slate-400 my-auto">
                            <span class="text-2xl block mb-1">💬</span>
                            <p class="font-semibold text-slate-600 text-xs">Ask anything about this manuscript</p>
                            <p class="text-[11px] text-slate-400 mt-1 max-w-sm mx-auto">Answers cite coordinate anchors that jump directly to the source paragraph in the viewer on the right.</p>
                        </div>
                    `;
                }
                const inp = document.getElementById('askQuestionInput');
                if (inp) inp.value = '';
            }

            function askQuickChip(question) {
                switchLeftTab('ask');
                const inp = document.getElementById('askQuestionInput');
                if (inp) {
                    inp.value = question;
                    executeAskQuery();
                }
            }

            async function executeAskQuery() {
                if (!currentUser) {
                    openAuthModal();
                    return;
                }
                if (!isApproved) {
                    const pendingModal = document.getElementById('pendingApprovalModal');
                    if (pendingModal) pendingModal.classList.remove('hidden');
                    return;
                }

                const inp = document.getElementById('askQuestionInput');
                const btn = document.getElementById('askSubmitBtn');
                const feed = document.getElementById('askChatFeed');

                if (!inp || !inp.value.trim()) return;
                const question = inp.value.trim();

                if (!currentFilename) {
                    alert('Please analyze a paper first before asking questions.');
                    return;
                }

                // If feed currently shows placeholder empty state, clear it
                if (askConversationHistory.length === 0 && feed) {
                    feed.innerHTML = '';
                }

                // Append user message
                const userMsgEl = document.createElement('div');
                userMsgEl.className = 'flex justify-end';
                userMsgEl.innerHTML = `
                    <div class="max-w-[85%] bg-sky-600 text-white rounded-lg px-3.5 py-2 shadow-2xs">
                        <p class="font-medium text-xs">${escapeHtml(question)}</p>
                    </div>
                `;
                if (feed) {
                    feed.appendChild(userMsgEl);
                }

                // Append temporary loading assistant message
                const loadingMsgId = 'ask-loading-' + Date.now();
                const loadingMsgEl = document.createElement('div');
                loadingMsgEl.id = loadingMsgId;
                loadingMsgEl.className = 'flex justify-start';
                loadingMsgEl.innerHTML = `
                    <div class="max-w-[85%] bg-white border border-slate-200 text-slate-700 rounded-lg px-3.5 py-2.5 shadow-2xs space-y-1">
                        <div class="flex items-center gap-2 text-slate-500 font-medium">
                            <svg class="animate-spin h-3.5 w-3.5 text-sky-600" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                            <span>Examining manuscript anchors...</span>
                        </div>
                    </div>
                `;
                if (feed) {
                    feed.appendChild(loadingMsgEl);
                    feed.scrollTop = feed.scrollHeight;
                }

                inp.value = '';
                inp.disabled = true;
                if (btn) btn.disabled = true;

                try {
                    const formData = new FormData();
                    formData.append('filename', currentFilename);
                    formData.append('question', question);
                    formData.append('history', JSON.stringify(askConversationHistory.slice(-4)));
                    if (currentUser) {
                        formData.append('user_uid', currentUser.uid);
                        formData.append('user_email', currentUser.email);
                    }

                    const apiKeyInput = document.getElementById('apiKey');
                    if (apiKeyInput && apiKeyInput.value.trim()) {
                        formData.append('api_key', apiKeyInput.value.trim());
                    }

                    const res = await fetch('/ask-paper', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await res.json();

                    const loadingNode = document.getElementById(loadingMsgId);
                    if (loadingNode) loadingNode.remove();

                    if (!res.ok) {
                        throw new Error(data.detail || 'Inquiry failed.');
                    }

                    const answerHtml = renderAnchoredMarkdown(data.answer || data.message || 'No answer generated.');
                    const cachedBadge = data.cached ? `<span class="ml-2 inline-flex items-center px-1.5 py-0.2 text-[10px] bg-emerald-100 text-emerald-800 rounded font-normal">⚡ Cached ($0.00)</span>` : '';

                    const assistantMsgEl = document.createElement('div');
                    assistantMsgEl.className = 'flex justify-start';
                    assistantMsgEl.innerHTML = `
                        <div class="max-w-[90%] bg-white border border-slate-200 text-slate-800 rounded-lg px-3.5 py-2.5 shadow-2xs space-y-1.5">
                            <div class="text-[11px] font-semibold text-slate-500 flex items-center justify-between">
                                <span>Study Wonk Answer ${cachedBadge}</span>
                            </div>
                            <div class="prose prose-sm max-w-none text-xs leading-relaxed">${answerHtml}</div>
                        </div>
                    `;
                    if (feed) {
                        feed.appendChild(assistantMsgEl);
                    }

                    // Update rolling history
                    askConversationHistory.push({ role: 'user', content: question });
                    askConversationHistory.push({ role: 'assistant', content: data.answer || '' });

                } catch (err) {
                    const loadingNode = document.getElementById(loadingMsgId);
                    if (loadingNode) loadingNode.remove();

                    const errorMsgEl = document.createElement('div');
                    errorMsgEl.className = 'flex justify-start';
                    errorMsgEl.innerHTML = `
                        <div class="max-w-[85%] bg-rose-50 border border-rose-200 text-rose-700 rounded-lg px-3.5 py-2 shadow-2xs text-xs">
                            <span class="font-bold">Error:</span> ${escapeHtml(err.message)}
                        </div>
                    `;
                    if (feed) {
                        feed.appendChild(errorMsgEl);
                    }
                } finally {
                    inp.disabled = false;
                    if (btn) btn.disabled = false;
                    inp.focus();
                    if (feed) {
                        feed.scrollTop = feed.scrollHeight;
                    }
                }
            }

            function inspectAnchor(encodedAnchor) {
                if (!encodedAnchor) return;
                const anchor = decodeURIComponent(encodedAnchor);
                
                // Highlight active pill
                document.querySelectorAll('.anchor-pill').forEach(el => {
                    const dataAnc = el.getAttribute('data-anchor');
                    const text = el.innerText.trim();
                    if (dataAnc === anchor || text === anchor || ('[' + text + ']') === anchor) {
                        el.classList.add('active');
                    } else {
                        el.classList.remove('active');
                    }
                });

                let meta = anchorIndex[anchor];
                if (!meta) {
                    const expanded = expandAnchorShortName(anchor);
                    meta = anchorIndex[expanded];
                }
                let resolvedAnchorId = (meta && meta.anchor_id) ? meta.anchor_id : anchor;

                // Support multi-paragraph citations, ranges (e.g. [Abstract, Para 1-3], [Results, Para 2, 8]), etc.
                if (!meta) {
                    const match = anchor.match(/\[?\s*([A-Za-z\s&]+?)\s*,\s*(?:Para|p)\s*(\d+)/i);
                    if (match) {
                        const expandedSec = expandAnchorShortName(match[1].trim()).replace(/^\[|\]$/g, '');
                        const fallbackId = `[${expandedSec}, Para ${match[2]}]`;
                        meta = anchorIndex[fallbackId];
                        if (meta) {
                            resolvedAnchorId = fallbackId;
                        } else {
                            const pNum = parseInt(match[2]);
                            for (const [k, v] of Object.entries(anchorIndex)) {
                                if (k.toLowerCase().includes(expandedSec.toLowerCase()) && k.includes(`Para ${pNum}`)) {
                                    meta = v;
                                    resolvedAnchorId = k;
                                    break;
                                }
                            }
                        }
                    }
                }

                // Support Table, TableNote, Fig, FigLegend, Box citations
                if (!meta) {
                    const tblFigMatch = anchor.match(/\[?\s*([A-Za-z\s&]+?)\s*,\s*(Table(?:Note)?|Fig(?:Legend)?|Box)\s*(\d+)/i);
                    if (tblFigMatch) {
                        const rawType = tblFigMatch[2];
                        const itemType = rawType.charAt(0).toUpperCase() + rawType.slice(1);
                        const expandedSec = expandAnchorShortName(tblFigMatch[1].trim()).replace(/^\[|\]$/g, '');
                        const fallbackId = `[${expandedSec}, ${itemType} ${tblFigMatch[3]}]`;
                        meta = anchorIndex[fallbackId];
                        if (meta) {
                            resolvedAnchorId = fallbackId;
                        } else {
                            for (const [k, v] of Object.entries(anchorIndex)) {
                                if (k.toLowerCase().includes(expandedSec.toLowerCase()) && k.toLowerCase().includes(`${itemType.toLowerCase()} ${tblFigMatch[3]}`)) {
                                    meta = v;
                                    resolvedAnchorId = k;
                                    break;
                                }
                            }
                        }
                    }
                }

                // Support structured abstract citations (e.g. [Abstract, Results], [Abs, Results], [Abstract, Methods])
                if (!meta) {
                    const absSubMatch = anchor.match(/\[?\s*(?:Abstract|Abs)\s*,\s*(Objective|Aims?|Methods?|Results?|Conclusions?)\b/i);
                    if (absSubMatch) {
                        const subWord = absSubMatch[1].toLowerCase();
                        for (const [k, v] of Object.entries(anchorIndex)) {
                            if (k.toLowerCase().includes('abstract') && (k.toLowerCase().includes(subWord) || (v.text && v.text.slice(0, 80).toLowerCase().includes(subWord)))) {
                                meta = v;
                                resolvedAnchorId = k;
                                break;
                            }
                        }
                    }
                }

                // Support bare section citations (e.g. [Abstract], [Results], [Methods], [Discussion], [Conclusions])
                if (!meta) {
                    const cleanSec = anchor.replace(/^\[|\]$/g, '').trim().toLowerCase();
                    const secPatterns = {
                        'abstract': [/^\[abstract/i],
                        'abs': [/^\[abstract/i],
                        'introduction': [/^\[intro/i],
                        'intro': [/^\[intro/i],
                        'methods': [/^\[(?:methods|materials and methods|patients and methods|study design)/i],
                        'meth': [/^\[(?:methods|materials and methods|patients and methods|study design)/i],
                        'results': [/^\[(?:results|findings)/i],
                        'res': [/^\[(?:results|findings)/i],
                        'discussion': [/^\[discussion/i],
                        'disc': [/^\[discussion/i],
                        'conclusion': [/^\[conclusion/i],
                        'conclusions': [/^\[conclusion/i],
                        'concl': [/^\[conclusion/i],
                        'header': [/^\[doc_header\]$/i],
                        'doc_header': [/^\[doc_header\]$/i]
                    };
                    const pats = secPatterns[cleanSec];
                    if (pats) {
                        for (const pat of pats) {
                            for (const [k, v] of Object.entries(anchorIndex)) {
                                if (pat.test(k)) {
                                    meta = v;
                                    resolvedAnchorId = k;
                                    break;
                                }
                            }
                            if (meta) break;
                        }
                    }
                }

                if (meta && !meta.anchor_id) {
                    meta.anchor_id = resolvedAnchorId;
                }

                const subtitle = document.getElementById('inspectSubtitle');
                const pageBadge = document.getElementById('pageBadge');
                const snippetBox = document.getElementById('snippetBox');
                const snippetText = document.getElementById('snippetText');
                const placeholder = document.getElementById('viewerPlaceholder');

                if (subtitle) {
                    subtitle.innerText = formatAnchorDisplay(anchor);
                }

                if (meta) {
                    currentMeta = Object.assign({ anchor_id: resolvedAnchorId }, meta);
                    if (pageBadge) {
                        pageBadge.innerText = 'Page ' + (meta.page || 1);
                        pageBadge.classList.remove('hidden');
                    }
                    if (snippetText) {
                        snippetText.innerText = meta.text || '';
                    }
                    if (snippetBox) {
                        snippetBox.classList.remove('hidden');
                    }

                    // If popup is pinned, update it to the new anchor
                    if (isPinned) {
                        const popupTitle = document.getElementById('popupTitle');
                        const popupImg = document.getElementById('popupCropImg');
                        const transcriptBox = document.getElementById('popupTranscriptBox');
                        const transcriptText = document.getElementById('popupTranscriptText');
                        const pageInfo = document.getElementById('popupPageInfo');
                        if (popupTitle) popupTitle.innerText = formatAnchorDisplay(anchor);
                        const cropAnchorId = (meta && meta.anchor_id) ? meta.anchor_id : anchor;
                        if (popupImg) popupImg.src = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(cropAnchorId)}`;
                        if (transcriptBox && transcriptText && meta.text) {
                            transcriptText.innerText = meta.text;
                            if (pageInfo) pageInfo.innerText = meta.page ? `Page ${meta.page}` : '';
                            transcriptBox.classList.remove('hidden');
                        }
                    } else {
                        const popup = document.getElementById('sectionPopup');
                        if (popup) popup.style.display = 'none';
                    }
                } else {
                    currentMeta = null;
                    if (pageBadge) pageBadge.classList.add('hidden');
                    if (snippetBox) snippetBox.classList.add('hidden');
                    const popup = document.getElementById('sectionPopup');
                    if (popup) popup.style.display = 'none';
                }

                if (placeholder) placeholder.classList.add('hidden');

                const targetPage = (meta && meta.page) ? meta.page : 1;
                const pageViewer = document.getElementById('pageViewer');
                const targetWrapper = document.getElementById('page-wrapper-' + targetPage);
                const targetImg = document.getElementById('pdf-page-img-' + targetPage);
                const hitbox = document.getElementById('highlightHitbox');

                if (hitbox && targetWrapper && hitbox.parentElement !== targetWrapper) {
                    hitbox.style.display = 'none';
                    targetWrapper.appendChild(hitbox);
                }

                if (targetImg) {
                    targetImg.loading = 'eager';
                }

                if (pageViewer && targetWrapper) {
                    const currentScroll = pageViewer.scrollTop;
                    const viewerRect = pageViewer.getBoundingClientRect();
                    const wrapperRect = targetWrapper.getBoundingClientRect();
                    const targetScroll = currentScroll + (wrapperRect.top - viewerRect.top) - 20;
                    pageViewer.scrollTo({
                        top: Math.max(0, targetScroll),
                        behavior: 'smooth'
                    });
                }

                repositionHitbox(true);
                setTimeout(() => repositionHitbox(true), 80);
                setTimeout(() => repositionHitbox(true), 250);
            }

            // =========================================================================
            // Clinician Voice Profile & Adversarial QC Engine Client State & Sync
            // =========================================================================
            let voiceProfileState = {
                schema_version: 1,
                revision: 0,
                base_revision: 0,
                local_dirty: false,
                updated_at_ms: 0,
                philosophy: "Prioritize natural therapies and nutritional interventions when safety profiles favor them; focus on absolute risk reductions over relative risk spin.",
                preferred_terms: "absolute risk reduction, clinical relevance, confounding, effect size",
                prohibited_terms: "more research is needed, delve, it is crucial to note",
                exemplars: []
            };

            function loadVoiceProfileFromLocal() {
                try {
                    const raw = localStorage.getItem('fact_voice_profile');
                    if (raw) {
                        const parsed = jsonParseSafe(raw, null);
                        if (parsed && typeof parsed === 'object') {
                            voiceProfileState = {
                                ...voiceProfileState,
                                ...parsed
                            };
                        }
                    }
                } catch (e) {
                    console.warn("[VoiceProfile] Failed reading local profile:", e);
                }
                updateVoiceUIElements();
            }

            function jsonParseSafe(str, fallback) {
                try { return JSON.parse(str); } catch (e) { return fallback; }
            }

            function updateVoiceUIElements() {
                const badge = document.getElementById('commentaryVoiceBadge');
                if (badge) {
                    const activeCount = (voiceProfileState.exemplars || []).filter(e => e.is_active).length;
                    badge.innerText = activeCount > 0 ? `Voice Calibrated (${activeCount} Exemplars)` : `Voice Calibrated (Philosophy Only)`;
                }
                const syncBadge = document.getElementById('voiceSyncBadge');
                if (syncBadge) {
                    const rev = voiceProfileState.revision || 0;
                    if (voiceProfileState.local_dirty) {
                        syncBadge.innerText = `Rev ${rev} · Unsynced Edits`;
                        syncBadge.className = "text-[11px] font-mono px-2 py-0.5 rounded bg-amber-100 text-amber-900 border border-amber-300";
                    } else if (currentUser) {
                        syncBadge.innerText = `Rev ${rev} · Synced to Cloud`;
                        syncBadge.className = "text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 border border-emerald-300";
                    } else {
                        syncBadge.innerText = `Rev ${rev} · Local Cache`;
                        syncBadge.className = "text-[11px] font-mono px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700";
                    }
                }
            }

            function updateVoiceFieldCounts() {
                const phil = document.getElementById('voicePhilosophyInput');
                const pref = document.getElementById('voicePreferredInput');
                const proh = document.getElementById('voiceProhibitedInput');
                const philCount = document.getElementById('voicePhilCount');
                const prefCount = document.getElementById('voicePrefCount');
                const prohCount = document.getElementById('voiceProhCount');

                if (phil && philCount) philCount.innerText = `${phil.value.length}/500`;
                if (pref && prefCount) prefCount.innerText = `${pref.value.length}/300`;
                if (proh && prohCount) prohCount.innerText = `${proh.value.length}/300`;
            }

            function renderVoiceModalUI() {
                const phil = document.getElementById('voicePhilosophyInput');
                const pref = document.getElementById('voicePreferredInput');
                const proh = document.getElementById('voiceProhibitedInput');
                if (phil) phil.value = voiceProfileState.philosophy || '';
                if (pref) pref.value = voiceProfileState.preferred_terms || '';
                if (proh) proh.value = voiceProfileState.prohibited_terms || '';
                updateVoiceFieldCounts();

                const listCont = document.getElementById('exemplarsList');
                if (!listCont) return;

                const exemplars = voiceProfileState.exemplars || [];
                if (exemplars.length === 0) {
                    listCont.innerHTML = `<div class="p-3 text-xs text-slate-400 dark:text-slate-500 italic bg-white dark:bg-slate-900 rounded-md border border-slate-200 dark:border-slate-800 text-center">No writing exemplars stored yet. Add 1 to 3 past reviews or newsletter posts so F.A.C.T. can mirror your sentence cadence and tone.</div>`;
                    return;
                }

                listCont.innerHTML = exemplars.map((ex, idx) => {
                    const charLen = (ex.text || '').length;
                    const isActive = Boolean(ex.is_active);
                    return `
                        <div class="p-2.5 rounded-lg border ${isActive ? 'border-sky-300 dark:border-sky-800 bg-white dark:bg-slate-900' : 'border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 opacity-75'} text-xs space-y-1.5 transition">
                            <div class="flex items-center justify-between">
                                <div class="flex items-center gap-2">
                                    <input type="checkbox" ${isActive ? 'checked' : ''} onchange="toggleExemplarActive('${ex.id}')" id="exCheck_${ex.id}" class="rounded text-sky-600 focus:ring-sky-500 cursor-pointer"/>
                                    <label for="exCheck_${ex.id}" class="font-bold text-slate-800 dark:text-slate-200 cursor-pointer">${escapeHtml(ex.title || ('Exemplar ' + (idx + 1)))}</label>
                                </div>
                                <div class="flex items-center gap-2">
                                    <span class="text-[10px] font-mono text-slate-400">${charLen} chars</span>
                                    <button type="button" onclick="deleteExemplar('${ex.id}')" class="text-rose-500 hover:text-rose-700 text-xs font-bold px-1 transition" title="Delete exemplar">✕</button>
                                </div>
                            </div>
                            <p class="text-[11px] text-slate-600 dark:text-slate-400 line-clamp-2 leading-relaxed font-serif italic">${escapeHtml(ex.text || '')}</p>
                        </div>
                    `;
                }).join('');
            }

            function toggleNewExemplarForm() {
                const box = document.getElementById('newExemplarBox');
                if (!box) return;
                box.classList.toggle('hidden');
                if (!box.classList.contains('hidden')) {
                    const titleInput = document.getElementById('newExemplarTitle');
                    if (titleInput) titleInput.focus();
                }
            }

            function updateNewExemplarCharCount() {
                const txt = document.getElementById('newExemplarText');
                const badge = document.getElementById('newExemplarCharCount');
                if (txt && badge) {
                    badge.innerText = `${txt.value.length}/1500`;
                }
            }

            function saveNewExemplar() {
                const titleInput = document.getElementById('newExemplarTitle');
                const textInput = document.getElementById('newExemplarText');
                if (!textInput || !textInput.value.trim()) {
                    alert("Please paste writing exemplar text before saving.");
                    return;
                }

                const newEx = {
                    id: 'ex_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4),
                    title: (titleInput && titleInput.value.trim()) ? titleInput.value.trim() : 'Writing Exemplar',
                    text: textInput.value.trim().slice(0, 1500),
                    is_active: (voiceProfileState.exemplars || []).filter(e => e.is_active).length < 3,
                    updated_at_ms: Date.now()
                };

                const currentList = voiceProfileState.exemplars || [];
                if (currentList.length >= 10) {
                    alert("Maximum 10 exemplars allowed in your library. Please remove an older exemplar first.");
                    return;
                }

                voiceProfileState.exemplars = [newEx, ...currentList];
                voiceProfileState.local_dirty = true;
                localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));

                if (titleInput) titleInput.value = '';
                if (textInput) textInput.value = '';
                updateNewExemplarCharCount();
                toggleNewExemplarForm();
                renderVoiceModalUI();
                updateVoiceUIElements();
            }

            function toggleExemplarActive(id) {
                const ex = (voiceProfileState.exemplars || []).find(e => e.id === id);
                if (!ex) return;
                
                const currentActive = (voiceProfileState.exemplars || []).filter(e => e.is_active && e.id !== id).length;
                if (!ex.is_active && currentActive >= 3) {
                    alert("A maximum of 3 active exemplars can be used during commentary generation to preserve attention on manuscript data. Please uncheck another exemplar first.");
                    renderVoiceModalUI();
                    return;
                }

                ex.is_active = !ex.is_active;
                ex.updated_at_ms = Date.now();
                voiceProfileState.local_dirty = true;
                localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));
                renderVoiceModalUI();
                updateVoiceUIElements();
            }

            function deleteExemplar(id) {
                voiceProfileState.exemplars = (voiceProfileState.exemplars || []).filter(e => e.id !== id);
                voiceProfileState.local_dirty = true;
                localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));
                renderVoiceModalUI();
                updateVoiceUIElements();
            }

            async function saveVoiceProfileAndNotify() {
                const phil = document.getElementById('voicePhilosophyInput');
                const pref = document.getElementById('voicePreferredInput');
                const proh = document.getElementById('voiceProhibitedInput');

                if (phil) voiceProfileState.philosophy = phil.value.trim();
                if (pref) voiceProfileState.preferred_terms = pref.value.trim();
                if (proh) voiceProfileState.prohibited_terms = proh.value.trim();

                voiceProfileState.local_dirty = true;
                voiceProfileState.updated_at_ms = Date.now();
                localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));

                if (currentUser && fbDb) {
                    await syncVoiceProfileWithFirestore(currentUser.uid, true);
                } else {
                    updateVoiceUIElements();
                }

                alert("Voice profile and exemplar library saved successfully!");
                closeSettingsModal();
            }

            // Monotonic Revision Counter + Dirty State Machine Synchronization
            async function syncVoiceProfileWithFirestore(uid, forcePush = false) {
                if (!uid || !fbDb) return;
                try {
                    const userDocRef = fbDb.collection('users').doc(uid);
                    const docSnap = await userDocRef.get();
                    const userData = docSnap.exists ? docSnap.data() : {};
                    const remote = userData.voice_profile || null;

                    const localBaseRev = voiceProfileState.base_revision || 0;
                    const remoteRev = (remote && typeof remote.revision === 'number') ? remote.revision : 0;

                    if (!voiceProfileState.local_dirty && !forcePush) {
                        // Case 1: Clean local state, remote is newer or equal
                        if (remote && remoteRev !== localBaseRev) {
                            voiceProfileState = {
                                ...voiceProfileState,
                                ...remote,
                                base_revision: remoteRev,
                                revision: remoteRev,
                                local_dirty: false
                            };
                            localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));
                            renderVoiceModalUI();
                            updateVoiceUIElements();
                            console.log(`[VoiceProfile] Hydrated remote revision ${remoteRev} into local state.`);
                        }
                    } else if (voiceProfileState.local_dirty && (!remote || remoteRev === localBaseRev || forcePush)) {
                        // Case 2: Local edits occurred without remote conflict -> commit incremented revision
                        const nextRev = remoteRev + 1;
                        const payloadToSave = {
                            schema_version: 1,
                            revision: nextRev,
                            philosophy: voiceProfileState.philosophy || '',
                            preferred_terms: voiceProfileState.preferred_terms || '',
                            prohibited_terms: voiceProfileState.prohibited_terms || '',
                            exemplars: voiceProfileState.exemplars || [],
                            updated_by_device: 'browser',
                            server_updated_at: firebase.firestore.FieldValue.serverTimestamp()
                        };

                        await userDocRef.set({ voice_profile: payloadToSave }, { merge: true });
                        voiceProfileState.revision = nextRev;
                        voiceProfileState.base_revision = nextRev;
                        voiceProfileState.local_dirty = false;
                        localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));
                        updateVoiceUIElements();
                        console.log(`[VoiceProfile] Committed local changes as revision ${nextRev} to Firestore.`);
                    } else if (voiceProfileState.local_dirty && remoteRev > localBaseRev) {
                        // Case 3: Concurrent conflict -> adopt remote revision and rescue unique local exemplars
                        const remoteTexts = new Set((remote.exemplars || []).map(e => (e.text || '').trim()));
                        const rescued = [];
                        (voiceProfileState.exemplars || []).forEach(localEx => {
                            if (localEx.text && !remoteTexts.has(localEx.text.trim())) {
                                rescued.push({
                                    id: localEx.id || ('ex_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4)),
                                    title: (localEx.title || 'Untitled Exemplar') + ' (Offline Draft)',
                                    text: localEx.text,
                                    is_active: false,
                                    updated_at_ms: Date.now()
                                });
                            }
                        });

                        const mergedExemplars = [...(remote.exemplars || []), ...rescued].slice(0, 10);
                        const mergedRev = remoteRev + 1;
                        const mergedPayload = {
                            schema_version: 1,
                            revision: mergedRev,
                            philosophy: remote.philosophy || voiceProfileState.philosophy || '',
                            preferred_terms: remote.preferred_terms || voiceProfileState.preferred_terms || '',
                            prohibited_terms: remote.prohibited_terms || voiceProfileState.prohibited_terms || '',
                            exemplars: mergedExemplars,
                            updated_by_device: 'browser',
                            server_updated_at: firebase.firestore.FieldValue.serverTimestamp()
                        };

                        await userDocRef.set({ voice_profile: mergedPayload }, { merge: true });
                        voiceProfileState = {
                            ...mergedPayload,
                            base_revision: mergedRev,
                            local_dirty: false
                        };
                        localStorage.setItem('fact_voice_profile', JSON.stringify(voiceProfileState));
                        renderVoiceModalUI();
                        updateVoiceUIElements();
                        console.warn(`[VoiceProfile] Case 3 Concurrent conflict merged into revision ${mergedRev}. Rescued ${rescued.length} local exemplar(s).`);
                    }
                } catch (err) {
                    console.error("[VoiceProfile] Firestore synchronization error:", err);
                }
            }

            // Commentary & Adversarial QC Execution Functions
            function updateCommentaryCharCount() {
                const ta = document.getElementById('commentaryTextarea');
                const cc = document.getElementById('commentaryCharCount');
                if (ta && cc) {
                    cc.innerText = `${ta.value.length} characters`;
                }
            }

            function copyCommentaryToClipboard() {
                const ta = document.getElementById('commentaryTextarea');
                const btnText = document.getElementById('copyCommentaryBtnText');
                if (!ta || !ta.value.trim()) {
                    alert("No commentary to copy.");
                    return;
                }
                navigator.clipboard.writeText(ta.value.trim()).then(() => {
                    if (btnText) {
                        btnText.innerText = "✓ Copied!";
                        setTimeout(() => { btnText.innerText = "Copy Post"; }, 2000);
                    }
                }).catch(err => {
                    alert("Copy failed: " + err);
                });
            }

            async function generateClinicalCommentary() {
                if (!currentFilename) {
                    alert("Please upload or analyze a manuscript before generating commentary.");
                    return;
                }
                const appraisalText = (window.ResearchAppState && window.ResearchAppState.lastAppraisalMarkdown) 
                    ? window.ResearchAppState.lastAppraisalMarkdown 
                    : (document.getElementById('outputMarkdown')?.innerText || '');

                if (!appraisalText) {
                    alert("Please run an appraisal on this paper first.");
                    return;
                }

                const genBtn = document.getElementById('generateCommentaryBtn');
                const genBtnText = document.getElementById('generateCommentaryBtnText');
                const origText = genBtnText ? genBtnText.innerText : 'Generate Commentary';
                if (genBtn) genBtn.disabled = true;
                if (genBtnText) genBtnText.innerText = "Drafting...";

                try {
                    const formData = new FormData();
                    formData.append('filename', currentFilename);
                    formData.append('appraisal_markdown', appraisalText);
                    formData.append('voice_profile', JSON.stringify(voiceProfileState));
                    if (currentUser) {
                        formData.append('user_uid', currentUser.uid || 'anonymous');
                        formData.append('user_email', currentUser.email || 'unauthenticated');
                    }

                    const resp = await fetch('/generate-commentary', {
                        method: 'POST',
                        body: formData
                    });

                    if (!resp.ok) {
                        const err = await resp.text();
                        throw new Error(`Server returned HTTP ${resp.status}: ${err}`);
                    }

                    const data = await resp.json();
                    const ta = document.getElementById('commentaryTextarea');
                    if (ta && data.commentary) {
                        ta.value = data.commentary;
                        updateCommentaryCharCount();
                    }

                    // Auto-trigger background adversarial QC audit after draft generation
                    runSecondaryQCAudit();
                } catch (e) {
                    alert("Commentary generation failed: " + e.message);
                } finally {
                    if (genBtn) genBtn.disabled = false;
                    if (genBtnText) genBtnText.innerText = origText;
                }
            }

            async function runSecondaryQCAudit() {
                if (!currentFilename) {
                    alert("Please load a manuscript before running QC audit.");
                    return;
                }
                const ta = document.getElementById('commentaryTextarea');
                const draftText = ta ? ta.value.trim() : '';
                if (!draftText) {
                    alert("Please generate or paste commentary text to audit.");
                    return;
                }

                const appraisalText = (window.ResearchAppState && window.ResearchAppState.lastAppraisalMarkdown) 
                    ? window.ResearchAppState.lastAppraisalMarkdown 
                    : (document.getElementById('outputMarkdown')?.innerText || '');

                const qcBtn = document.getElementById('runQCAuditBtn');
                const qcBtnText = document.getElementById('runQCAuditBtnText');
                const origText = qcBtnText ? qcBtnText.innerText : 'Run Adversarial QC Audit';
                if (qcBtn) qcBtn.disabled = true;
                if (qcBtnText) qcBtnText.innerText = "Auditing (temp=0.0)...";

                const qcSec = document.getElementById('qcAuditSection');
                if (qcSec) qcSec.classList.remove('hidden');

                try {
                    const formData = new FormData();
                    formData.append('filename', currentFilename);
                    formData.append('appraisal_markdown', appraisalText);
                    formData.append('commentary_text', draftText);
                    if (window.ResearchAppState && window.ResearchAppState.lastAppraisalData && window.ResearchAppState.lastAppraisalData.triage) {
                        formData.append('triage', JSON.stringify(window.ResearchAppState.lastAppraisalData.triage));
                    }
                    if (currentUser) {
                        formData.append('user_uid', currentUser.uid || 'anonymous');
                        formData.append('user_email', currentUser.email || 'unauthenticated');
                    }

                    const resp = await fetch('/audit-commentary', {
                        method: 'POST',
                        body: formData
                    });

                    if (!resp.ok) {
                        const err = await resp.text();
                        throw new Error(`Server returned HTTP ${resp.status}: ${err}`);
                    }

                    const data = await resp.json();
                    renderQCAuditResults(data);
                } catch (e) {
                    alert("QC audit failed: " + e.message);
                } finally {
                    if (qcBtn) qcBtn.disabled = false;
                    if (qcBtnText) qcBtnText.innerText = origText;
                }
            }

            let lastQCAuditData = null;

            function renderQCAuditResults(data) {
                lastQCAuditData = data;
                const qcSec = document.getElementById('qcAuditSection');
                const integrityBadge = document.getElementById('qcIntegrityBadge');
                const summaryVerdict = document.getElementById('qcSummaryVerdict');
                const caveatBox = document.getElementById('qcDesignCaveatBox');
                const feed = document.getElementById('qcDiscrepanciesFeed');

                if (!qcSec) return;
                qcSec.classList.remove('hidden');

                const integrity = (data.overall_integrity || 'VERIFIED').toUpperCase();
                if (integrityBadge) {
                    if (integrity === 'VERIFIED') {
                        integrityBadge.innerText = "✓ Grounding Verified";
                        integrityBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700";
                    } else if (integrity === 'CAUTION') {
                        integrityBadge.innerText = "⚠ Nuance / Overreach Identified";
                        integrityBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border border-amber-300 dark:border-amber-700";
                    } else {
                        integrityBadge.innerText = "✗ Discrepancy Flagged";
                        integrityBadge.className = "px-2.5 py-0.5 rounded text-xs font-bold bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300 border border-rose-300 dark:border-rose-700";
                    }
                }

                if (summaryVerdict) {
                    summaryVerdict.innerText = data.summary_verdict || 'Audit evaluation complete.';
                }

                if (caveatBox) {
                    if (data.study_design_caveat) {
                        caveatBox.innerHTML = `<strong>Methodological Design Caveat:</strong> ${renderCoordinatePillsInText(data.study_design_caveat)}`;
                        caveatBox.classList.remove('hidden');
                    } else {
                        caveatBox.classList.add('hidden');
                    }
                }

                if (!feed) return;
                const discrepancies = data.discrepancies || [];

                if (discrepancies.length === 0) {
                    feed.innerHTML = `
                        <div class="p-4 rounded-md bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200 text-xs flex items-center gap-2">
                            <span class="text-base font-bold text-emerald-600">✓</span>
                            <span><strong>No discrepancies or ungrounded claims detected.</strong> All numerical findings, effect sizes, and causal statements are supported by manuscript coordinates.</span>
                        </div>
                    `;
                    return;
                }

                feed.innerHTML = discrepancies.map((d, idx) => {
                    const isRed = (d.severity || '').toUpperCase() === 'RED';
                    const category = (d.category || 'ANALYSIS').replace(/_/g, ' ');
                    const scope = (d.scope || 'LOCALIZED_CLAIM').replace(/_/g, ' ');
                    
                    let citationsHtml = '';
                    if (d.citations && d.citations.length > 0) {
                        citationsHtml = `
                            <div class="flex items-center gap-1.5 flex-wrap pt-1">
                                <span class="text-[11px] font-semibold text-slate-500">Evidence Anchors:</span>
                                ${d.citations.map(c => {
                                    const clean = String(c).replace(/^\[|\]$/g, '').trim();
                                    const rawId = `[${clean}]`;
                                    const enc = encodeURIComponent(rawId);
                                    return `<button type="button" onclick="inspectAnchor('${enc}')" data-anchor="${rawId}" class="anchor-pill inline-flex items-center px-2 py-0.5 text-[11px] font-sans font-medium bg-sky-50 dark:bg-sky-950/70 text-sky-800 dark:text-sky-300 hover:bg-sky-600 hover:text-white border border-sky-300/80 dark:border-sky-800 rounded shadow-2xs leading-none cursor-pointer" title="Jump to proof on PDF">${formatAnchorDisplay(clean)}</button>`;
                                }).join(' ')}
                            </div>
                        `;
                    }

                    return `
                        <div class="p-3.5 rounded-lg border ${isRed ? 'border-rose-300 dark:border-rose-800 bg-rose-50/50 dark:bg-rose-950/20' : 'border-amber-300 dark:border-amber-800 bg-amber-50/40 dark:bg-amber-950/20'} space-y-2 text-xs">
                            <div class="flex items-center justify-between gap-2">
                                <div class="flex items-center gap-1.5">
                                    <span class="px-2 py-0.5 rounded text-[10px] font-bold ${isRed ? 'bg-rose-200 text-rose-900 border border-rose-300' : 'bg-amber-200 text-amber-900 border border-amber-300'}">${escapeHtml(category)}</span>
                                    <span class="text-[10px] font-mono text-slate-500 uppercase">${escapeHtml(scope)}</span>
                                </div>
                                <span class="text-[10px] font-bold ${isRed ? 'text-rose-700' : 'text-amber-700'}">${isRed ? 'CRITICAL DISCREPANCY' : 'CAUTION / NUANCE'}</span>
                            </div>

                            <div class="bg-white dark:bg-slate-900 p-2.5 rounded border border-slate-200 dark:border-slate-800 space-y-1">
                                <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">Quoted Claim in Draft:</span>
                                <p class="text-xs text-slate-800 dark:text-slate-200 font-serif italic">"${escapeHtml(d.quoted_claim || '')}"</p>
                            </div>

                            <div class="space-y-1">
                                <span class="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">Manuscript Proof / Finding:</span>
                                <p class="text-xs text-slate-700 dark:text-slate-300 leading-relaxed">${renderCoordinatePillsInText(d.manuscript_evidence || '')}</p>
                                ${citationsHtml}
                            </div>

                            ${d.suggested_edit ? `
                                <div class="p-2.5 rounded bg-sky-50 dark:bg-sky-950/40 border border-sky-200 dark:border-sky-800/60 flex items-start justify-between gap-3">
                                    <div class="space-y-0.5">
                                        <span class="text-[10px] font-bold text-sky-900 dark:text-sky-300 uppercase block">Suggested Alignment:</span>
                                        <p class="text-xs text-sky-950 dark:text-sky-200 font-serif italic">${escapeHtml(d.suggested_edit)}</p>
                                    </div>
                                    <button type="button" onclick="applyQCSuggestion(${idx})" class="shrink-0 px-2.5 py-1 rounded bg-white dark:bg-slate-850 hover:bg-sky-600 hover:text-white text-sky-700 dark:text-sky-300 border border-sky-300 dark:border-sky-700 text-[11px] font-semibold transition shadow-2xs cursor-pointer">
                                        Apply Fix
                                    </button>
                                </div>
                            ` : ''}
                        </div>
                    `;
                }).join('');
            }

            function applyQCSuggestion(index) {
                if (!lastQCAuditData || !lastQCAuditData.discrepancies || !lastQCAuditData.discrepancies[index]) return;
                const d = lastQCAuditData.discrepancies[index];
                const ta = document.getElementById('commentaryTextarea');
                if (!ta || !d.quoted_claim || !d.suggested_edit) return;

                const currentVal = ta.value;
                if (currentVal.includes(d.quoted_claim)) {
                    ta.value = currentVal.replace(d.quoted_claim, d.suggested_edit);
                    updateCommentaryCharCount();
                    alert("Applied suggestion to your commentary draft!");
                } else {
                    ta.value = currentVal + "\n\n" + d.suggested_edit;
                    updateCommentaryCharCount();
                    alert("Added suggested alignment to the end of your draft.");
                }
            }

            // Initialize Clinician Voice Profile from Local Storage on Load
            loadVoiceProfileFromLocal();

            // Initialize Firebase Authentication & Governance on Load
            initFirebaseAuth();

            // Initialize Theme & Highlight Settings on Load
            applyThemeMode(currentThemeMode);
            applyHighlightColor(currentHighlightColor);

            // Initialize Default Startup View on Load
            const savedDefaultMode = localStorage.getItem('fact_default_mode') || 'appraisal';
            if (savedDefaultMode && savedDefaultMode !== 'appraisal') {
                switchMasterMode(savedDefaultMode);
            }

            // Global Escape key listener to close modals
            window.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    closeSettingsModal();
                    closeAuthModal();
                    closeUserManagementModal();
                }
            });
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=True)
