import os
import sys
import shutil
import io
import urllib.parse
import re
from typing import Optional, Dict, List
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
from src.finder.searcher import PaperFinder, MODEL_DESIGNATION as FINDER_MODEL_DESIGNATION
from src.summarizer.engine import PaperSummarizer, MODEL_DESIGNATION as SUMMARIZER_MODEL_DESIGNATION

app = FastAPI(
    title="F.A.S.T. - Find. Appraise. Summarize Trials",
    description="Deterministic Clinical Research Appraiser with Inline Coordinate Grounding",
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

DATA_DIR = os.getenv("RESEARCH_EVAL_DATA_DIR", r"D:\SSD-Drive\Antigravity\ResearchEval\data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
PUBLIC_DIR = os.path.join(PROJECT_ROOT, "public")
ICONS_DIR = os.path.join(PUBLIC_DIR, "icons")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if os.path.exists(PUBLIC_DIR):
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")

if os.path.exists(ICONS_DIR):
    app.mount("/icons", StaticFiles(directory=ICONS_DIR), name="icons")

@app.get("/manifest.json")
def get_manifest():
    manifest_file = os.path.join(PUBLIC_DIR, "manifest.json")
    if os.path.exists(manifest_file):
        return FileResponse(manifest_file, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="Manifest not found")

@app.get("/FAST-Elf.jpeg")
def get_fast_elf_image():
    elf_file = os.path.join(PUBLIC_DIR, "FAST-Elf.jpeg")
    if os.path.exists(elf_file):
        return FileResponse(elf_file, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="FAST-Elf image not found")

@app.get("/logo.png")
@app.get("/elf-thinker.png")
def get_logo():
    # Return new FAST icon
    fast_icon = os.path.join(PUBLIC_DIR, "icons", "icon-512.png")
    if os.path.exists(fast_icon):
        return FileResponse(fast_icon, media_type="image/png")
    logo_file = os.path.join(STATIC_DIR, "fast-elf.png")
    if os.path.exists(logo_file):
        return FileResponse(logo_file, media_type="image/png")
    raise HTTPException(status_code=404, detail="Logo not found")

@app.get("/favicon.ico")
def get_favicon():
    favicon_file = os.path.join(PUBLIC_DIR, "favicon.ico")
    if os.path.exists(favicon_file):
        return FileResponse(favicon_file, media_type="image/x-icon")
    alt_file = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(alt_file):
        return FileResponse(alt_file, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="Favicon not found")

engine = SynthesisEngine(DATA_DIR)
fetcher = PaperFetcher(UPLOAD_DIR)

# In-memory session cache of the most recently indexed document
CACHED_INDEX: Dict[str, IndexedDocument] = {}

finder = PaperFinder()
summarizer = PaperSummarizer()


class FinderSearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 10


class SummarizerGenerateRequest(BaseModel):
    urls: List[str]
    max_batch_size: Optional[int] = 10


@app.post("/api/finder/search")
def api_finder_search(req: FinderSearchRequest):
    """Execute Zero-Trust 4-tier relaxation search and binary clinical gate verification."""
    try:
        res = finder.find_papers(query=req.query, max_results=req.max_results or 10)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/summarizer/generate")
def api_summarizer_generate(req: SummarizerGenerateRequest):
    """Execute sequential structured multi-paper lay science communicator briefing."""
    try:
        res = summarizer.summarize_batch(raw_inputs=req.urls, max_batch_size=req.max_batch_size or 10)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.post("/appraise-fetched")
def appraise_fetched_paper(
    filename: str = Form(...),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None)
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
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/appraise")
async def appraise_paper(
    file: UploadFile = File(...),
    model_override: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None)
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

    # 3. Table or Figure matching: '[Results, Table 1]', '[Results, Fig 2]'
    tbl_fig_match = re.search(r'\[?\s*([A-Za-z\s&]+?)\s*,\s*(Table|Fig)\s*(\d+)', anchor_clean, re.IGNORECASE)
    if tbl_fig_match:
        section = tbl_fig_match.group(1).strip()
        item_type = tbl_fig_match.group(2).capitalize()
        num = int(tbl_fig_match.group(3))

        canonical = f"[{section}, {item_type} {num}]"
        if canonical in indexed.anchor_metadata:
            return indexed.anchor_metadata[canonical]

        for k, meta in indexed.anchor_metadata.items():
            if meta.item_type.lower() == item_type.lower() and meta.index == num:
                return meta

    # 4. Fallback: match any single paragraph number in the anchor string
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
        crop_rect = pymupdf.Rect(
            max(0, rect.x0 - 10),
            max(0, rect.y0 - 6),
            min(page.rect.width, rect.x1 + 10),
            min(page.rect.height, rect.y1 + 6)
        )
        pix1 = page.get_pixmap(clip=crop_rect, dpi=300)
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
                max(0, rect2.x0 - 10),
                max(0, rect2.y0 - 6),
                min(p_next.rect.width, rect2.x1 + 10),
                min(p_next.rect.height, rect2.y1 + 6)
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
    """Serve the raw PDF file for inline browser viewing."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return StreamingResponse(open(file_path, "rb"), media_type="application/pdf")

@app.get("/", response_class=HTMLResponse)
def index_page():
    return r"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>F.A.S.T. — Find · Appraise · Summarize Trials</title>
        
        <!-- PWA Meta Tags & Web Manifest -->
        <link rel="manifest" href="/manifest.json">
        <meta name="theme-color" content="#0284c7">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="default">
        <meta name="apple-mobile-web-app-title" content="F.A.S.T.">
        
        <!-- Icons -->
        <link rel="icon" type="image/x-icon" href="/favicon.ico">
        <link rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32x32.png">
        <link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192.png">
        <link rel="apple-touch-icon" sizes="180x180" href="/icons/apple-touch-icon.png">
        <script src="https://cdn.tailwindcss.com"></script>
        <!-- Marked.js for rich markdown rendering -->
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            .anchor-pill {
                cursor: pointer;
                transition: all 0.15s ease-in-out;
            }
            .anchor-pill:hover {
                transform: translateY(-1px);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            }
            .anchor-pill.active {
                background-color: #0284c7 !important;
                color: #ffffff !important;
                border-color: #0369a1 !important;
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
                background-color: #0284c7;
            }
            /* Hover highlight popover box on the manuscript page */
            #imageContainer {
                position: relative;
            }
            #highlightHitbox {
                position: absolute;
                cursor: zoom-in;
                border: 2px solid #d97706; /* vivid amber-600 border */
                background-color: rgba(245, 158, 11, 0.28); /* luminous warm amber tint */
                border-radius: 4px;
                box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.5), 0 0 15px rgba(245, 158, 11, 0.4);
                z-index: 25;
                pointer-events: auto;
                transition: top 0.15s ease-out, left 0.15s ease-out, width 0.15s ease-out, height 0.15s ease-out;
            }
            @keyframes highlightPulse {
                0% { box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.8), 0 0 20px rgba(245, 158, 11, 0.9); }
                50% { box-shadow: 0 0 0 5px rgba(251, 191, 36, 1.0), 0 0 30px rgba(245, 158, 11, 1.0); }
                100% { box-shadow: 0 0 0 2px rgba(251, 191, 36, 0.5), 0 0 15px rgba(245, 158, 11, 0.4); }
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
                border: 2px solid #0284c7;
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
    <body class="bg-slate-50 text-slate-800 min-h-screen p-4">
        <div class="max-w-[1700px] mx-auto space-y-3">
            <!-- Compact Header & Input Bar (Option 1) -->
            <header class="bg-white px-5 py-3 rounded-lg border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-4">
                <!-- Left: Logo & App Title -->
                <div class="flex items-center gap-3 shrink-0">
                    <div class="relative z-30 group shrink-0">
                        <div class="w-10 h-10 rounded-lg bg-white flex items-center justify-center overflow-hidden border border-slate-200 shadow-2xs transition-all duration-300 ease-out origin-top-left group-hover:scale-[3.5] group-hover:rounded-xl group-hover:shadow-2xl group-hover:border-sky-300 group-hover:ring-4 group-hover:ring-sky-500/15 cursor-pointer">
                            <img 
                                src="/FAST-Elf.jpeg" 
                                alt="F.A.S.T. Logo" 
                                class="w-full h-full object-cover"
                            />
                        </div>
                    </div>
                    <div>
                        <h1 class="text-xl font-bold text-sky-800 tracking-tight leading-none">F.A.S.T.</h1>
                        <p class="text-slate-500 text-[11px] font-medium mt-0.5">Find <span class="text-slate-400 font-bold mx-1">·</span> Appraise <span class="text-slate-400 font-bold mx-1">·</span> Summarize Trials</p>
                    </div>
                </div>

                <!-- Master 3-Mode Navigation Switcher: F.A.S.T. (Find -> Appraise -> Summarize Trials) -->
                <div class="flex items-center bg-slate-100 p-1 rounded-lg border border-slate-200 text-xs font-semibold gap-1 shrink-0">
                    <button id="masterTabFinder" onclick="switchMasterMode('finder')" class="px-3 py-1.5 rounded-md transition text-slate-600 hover:text-slate-900 flex items-center gap-1.5 text-xs font-medium">
                        <span>🔍</span> <span>Find</span>
                    </button>
                    <button id="masterTabAppraisal" onclick="switchMasterMode('appraisal')" class="px-3 py-1.5 rounded-md bg-white text-sky-700 shadow-2xs font-bold transition flex items-center gap-1.5 text-xs">
                        <span>🔬</span> <span>Appraise</span>
                    </button>
                    <button id="masterTabSummarizer" onclick="switchMasterMode('summarizer')" class="px-3 py-1.5 rounded-md transition text-slate-600 hover:text-slate-900 flex items-center gap-1.5 text-xs font-medium">
                        <span>📝</span> <span>Summarize</span>
                        <span id="summarizerBatchBadge" class="hidden ml-1 px-1.5 py-0.2 bg-sky-600 text-white rounded-full text-[10px] font-bold">0</span>
                    </button>
                </div>

                <!-- Center: Compact Unified Input (PDF or URL) -->
                <div class="flex items-center gap-2 bg-slate-50 p-1.5 rounded-lg border border-slate-200 flex-1 max-w-2xl">
                    <!-- Mode Switch Buttons -->
                    <div class="flex bg-slate-200/80 p-0.5 rounded text-xs font-medium shrink-0">
                        <button id="tabPdfBtn" onclick="switchInputTab('pdf')" class="px-2.5 py-1 rounded bg-white text-sky-700 shadow-2xs font-semibold transition">📄 PDF</button>
                        <button id="tabUrlBtn" onclick="switchInputTab('url')" class="px-2.5 py-1 rounded text-slate-600 hover:text-slate-900 transition">🔗 Link / PMID</button>
                    </div>

                    <!-- PDF Input Control -->
                    <div id="tabPdf" class="flex items-center gap-2 flex-1">
                        <input type="file" id="pdfFile" accept=".pdf" class="block w-full text-xs text-slate-600 file:mr-2.5 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-700 cursor-pointer bg-white px-2 py-1 rounded border border-slate-200"/>
                        <button onclick="startAppraisal()" id="runBtn" class="bg-sky-600 hover:bg-sky-700 text-white font-semibold text-xs px-4 py-1.5 rounded transition shadow-xs shrink-0">Evaluate</button>
                    </div>

                    <!-- URL / PMID Input Control -->
                    <div id="tabUrl" class="hidden flex items-center gap-2 flex-1">
                        <input type="text" id="paperUrl" placeholder="Paste PubMed URL, PMID (e.g. 37726553), PMC ID, or DOI" class="block w-full text-xs text-slate-800 bg-white px-3 py-1.5 rounded border border-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500"/>
                        <button onclick="startUrlResolution()" id="resolveBtn" class="bg-sky-600 hover:bg-sky-700 text-white font-semibold text-xs px-4 py-1.5 rounded transition shadow-xs shrink-0">Fetch & Evaluate</button>
                    </div>
                </div>

                <!-- Right: Study Type Badge with Rich Tooltip (Hidden until appraisal loaded) -->
                <div class="flex items-center gap-3 shrink-0">
                    <!-- Live Loading Spinner -->
                    <div id="statusBox" class="hidden flex items-center gap-2 text-xs font-medium text-sky-700 bg-sky-50 px-3 py-1.5 rounded-md border border-sky-200">
                        <div id="spinner" class="animate-spin rounded-full h-3.5 w-3.5 border-2 border-sky-600 border-t-transparent"></div>
                        <span id="statusText">Processing...</span>
                    </div>

                    <!-- Study Wonk Framework Badge with Hover Tooltip -->
                    <div id="studyBadgeWrapper" class="hidden study-badge-container cursor-help">
                        <div class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-sky-100 text-sky-900 border border-sky-300 text-xs font-semibold shadow-2xs hover:bg-sky-200 transition">
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
                                    <li>Grounded Appraisal Rules</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </header>

            <!-- Abstract-Only Confirmation Dialog Modal -->
            <div id="abstractModal" class="hidden fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
                <div class="bg-white rounded-xl border border-slate-200 shadow-xl max-w-lg w-full p-6 space-y-4">
                    <div class="flex items-center gap-3 text-amber-600">
                        <svg class="w-6 h-6 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                        <h3 class="text-lg font-bold text-slate-900">Full Text Unavailable (Abstract Only)</h3>
                    </div>
                    <p class="text-sm text-slate-600 leading-relaxed">
                        The requested URL or identifier does not have a free full-text manuscript available (likely behind a journal paywall). We retrieved the official published abstract.
                    </p>
                    <div class="p-3 bg-amber-50 rounded-md border border-amber-200 text-xs text-amber-900 max-h-36 overflow-y-auto font-serif italic" id="modalAbstractSnippet"></div>
                    <p class="text-xs font-semibold text-slate-700">Would you like to evaluate the abstract only?</p>
                    <div class="flex justify-end gap-3 pt-2">
                        <button onclick="closeAbstractModal()" class="px-4 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 bg-slate-100 hover:bg-slate-200 rounded-md transition">Cancel</button>
                        <button onclick="proceedWithAbstractOnly()" class="px-4 py-2 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-700 rounded-md transition shadow">Evaluate Abstract Only</button>
                    </div>
                </div>
            </div>

            <!-- Sibling Container 1: Paper Finder Mode -->
            <div id="finderContainer" class="hidden w-full overflow-y-auto space-y-4" style="height: calc(100vh - 105px);">
                <div class="bg-white rounded-xl border border-slate-200 p-6 shadow-xs max-w-5xl mx-auto space-y-5">
                    <!-- Header & Directive -->
                    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4">
                        <div>
                            <h2 class="text-base font-bold text-slate-800 flex items-center gap-2">
                                <span>🔍</span> Precision Zero-Trust Paper Finder
                            </h2>
                            <p class="text-xs text-slate-500 mt-1">
                                Search medical literature using fuzzy recollection or clinical criteria. Powered by a 4-tier query relaxation ladder and strict binary clinical gate.
                            </p>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-sky-50 text-sky-700 border border-sky-200">
                                Model: Gemini flash
                            </span>
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
                                    class="w-full text-xs bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500 transition shadow-2xs"
                                    onkeydown="if(event.key === 'Enter') executeFinderSearch();"
                                />
                                <button onclick="clearFinderSearch()" class="absolute right-3 top-3 text-slate-400 hover:text-slate-600 text-xs font-bold" title="Clear search">✕</button>
                            </div>
                            <button 
                                id="finderSubmitBtn" 
                                onclick="executeFinderSearch()" 
                                class="bg-sky-600 hover:bg-sky-700 text-white font-semibold text-xs px-5 py-3 rounded-lg transition shadow-xs flex items-center gap-2 shrink-0"
                            >
                                <span id="finderBtnIcon">🔍</span>
                                <span id="finderBtnText">Find Verified Papers</span>
                            </button>
                        </div>
                        <!-- Quick Example Chips -->
                        <div class="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-slate-500">
                            <span class="font-medium">Try example query:</span>
                            <button onclick="setFinderQuery('CoQ10 reduced cardiovascular mortality in elderly Swedish cohort, 5 year follow up')" class="px-2 py-0.5 rounded bg-slate-100 hover:bg-sky-100 hover:text-sky-700 border border-slate-200 transition">
                                CoQ10 cardiovascular mortality in Swedish cohort
                            </button>
                            <button onclick="setFinderQuery('Curcumin osteoarthritis randomized trial knee pain and inflammatory biomarkers')" class="px-2 py-0.5 rounded bg-slate-100 hover:bg-sky-100 hover:text-sky-700 border border-slate-200 transition">
                                Curcumin knee osteoarthritis RCT
                            </button>
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
                <div class="bg-white rounded-xl border border-slate-200 p-6 shadow-xs max-w-5xl mx-auto space-y-5">
                    <!-- Header & Directive -->
                    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 pb-4">
                        <div>
                            <h2 class="text-base font-bold text-slate-800 flex items-center gap-2">
                                <span>📝</span> Multi-Paper Science Communicator Summarizer
                            </h2>
                            <p class="text-xs text-slate-500 mt-1">
                                Paste a batch of 3–10 PubMed URLs, PMIDs, or DOIs. Reads structured abstracts sequentially to create an accessible, grounded overview.
                            </p>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                Model: Gemini flash
                            </span>
                        </div>
                    </div>

                    <!-- Batch URLs Input -->
                    <div class="space-y-2">
                        <div class="flex items-center justify-between text-xs text-slate-600 font-medium">
                            <span>Enter PubMed URLs, PMIDs, or DOIs (one per line):</span>
                            <div class="flex items-center gap-3">
                                <button onclick="loadSampleSummarizerBatch()" class="text-sky-600 hover:text-sky-700 font-semibold text-[11px]">Load Sample CoQ10 Papers</button>
                                <span class="text-slate-300">|</span>
                                <button onclick="clearSummarizerInput()" class="text-rose-600 hover:text-rose-700 font-semibold text-[11px]">Clear All</button>
                            </div>
                        </div>
                        <textarea 
                            id="summarizerUrlsInput" 
                            rows="5" 
                            placeholder="https://pubmed.ncbi.nlm.nih.gov/23843810/&#10;https://pubmed.ncbi.nlm.nih.gov/30302302/&#10;29188837"
                            class="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg p-3 text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-500 transition shadow-2xs leading-relaxed"
                            oninput="updateSummarizerBatchCount()"
                        ></textarea>
                        <div class="flex items-center justify-between pt-1">
                            <span id="summarizerBatchCounter" class="text-[11px] text-slate-400">Batch size: 0 / 10 papers</span>
                            <button 
                                id="summarizerSubmitBtn" 
                                onclick="executeSummarizerBatch()" 
                                class="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs px-5 py-2.5 rounded-lg transition shadow-xs flex items-center gap-2"
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
                        <div class="bg-slate-50 rounded-xl border border-slate-200 p-5 space-y-4">
                            <div class="flex items-center justify-between border-b border-slate-200 pb-3">
                                <div class="flex items-center gap-2">
                                    <span class="text-sm font-bold text-slate-800">📄 Synthesized Briefing Document</span>
                                    <span id="summarizerMetaBadge" class="text-[11px] bg-slate-200 text-slate-700 px-2 py-0.5 rounded font-mono"></span>
                                </div>
                                <div class="flex items-center gap-2">
                                    <button onclick="copySummarizerMarkdown()" id="copySummaryBtn" class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white border border-slate-300 hover:border-slate-400 text-slate-700 hover:text-slate-900 text-xs font-medium transition shadow-2xs">
                                        <span>📋</span> <span id="copySummaryBtnText">Copy to Clipboard</span>
                                    </button>
                                </div>
                            </div>
                            <!-- Rendered Markdown Content -->
                            <div id="summarizerRenderedContent" class="text-xs leading-relaxed space-y-4 text-slate-800"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Results Section: Split Screen -->
            <div id="resultBox" class="hidden">
                <!-- Draggable Split Container: Left Appraisal | Resizer | Right Source Inspector -->
                <div id="splitContainer" class="flex flex-row w-full gap-0 select-none items-stretch rounded-lg border border-slate-200 shadow-sm overflow-hidden bg-white" style="height: calc(100vh - 105px); min-height: 650px;">
                    <!-- Left: Clinical Appraisal & Show Thinking Tab Switcher (Behavior 3) -->
                    <div id="leftPane" class="bg-white p-6 border-r border-slate-200 overflow-y-auto select-text flex flex-col h-full" style="width: 55%; min-width: 25%; max-width: 75%;">
                        <div class="sticky top-0 bg-white z-10 pb-3 border-b border-slate-200 mb-4 flex flex-wrap justify-between items-center gap-2">
                            <div class="flex items-center gap-2">
                                <div class="flex bg-slate-100 p-0.5 rounded-lg border border-slate-200 text-xs font-medium">
                                    <button id="leftTabAppraisalBtn" onclick="switchLeftTab('appraisal')" class="px-3 py-1 rounded-md bg-white text-sky-800 shadow-2xs font-semibold transition flex items-center gap-1.5 cursor-pointer">
                                        <span>📄</span> <span>Clinical Appraisal</span>
                                    </button>
                                    <button id="leftTabThinkingBtn" onclick="switchLeftTab('thinking')" class="px-3 py-1 rounded-md text-slate-600 hover:text-slate-900 transition flex items-center gap-1.5 cursor-pointer">
                                        <span>🧠</span> <span>Show Thinking / Audit</span>
                                    </button>
                                </div>
                            </div>
                            <span id="leftPaneHint" class="text-xs text-slate-400 italic">Click any coordinate pill to inspect source text</span>
                        </div>
                        <div id="outputMarkdown" class="prose max-w-none text-slate-800 bg-slate-50 p-6 rounded-lg border border-slate-200 text-sm leading-relaxed flex-1"></div>
                        <div id="thinkingContainer" class="hidden flex-1 space-y-4"></div>
                    </div>

                    <!-- Draggable Divider Bar -->
                    <div id="dragDivider" class="resizer" title="Drag left or right to resize panels"></div>

                    <!-- Right: Interactive Source Inspector -->
                    <div id="rightPane" class="bg-white p-6 flex flex-col space-y-4 select-text h-full overflow-hidden" style="width: 45%; min-width: 25%; max-width: 75%;">
                        <div class="border-b border-slate-200 pb-3 flex justify-between items-center flex-shrink-0">
                            <div>
                                <h3 class="text-base font-semibold text-slate-800">Source Evidence Inspector</h3>
                                <p id="inspectSubtitle" class="text-xs text-slate-500 mt-0.5">Select any coordinate pill on the left</p>
                            </div>
                            <div class="flex items-center gap-2">
                                <span id="pageBadge" class="hidden px-2.5 py-1 text-xs font-semibold rounded bg-sky-100 text-sky-800 border border-sky-200">Page -</span>
                            </div>
                        </div>

                        <!-- Snippet Text Box (Large Readable Typography) -->
                        <div id="snippetBox" class="hidden p-4 rounded-md bg-amber-50 border border-amber-200 text-sm text-amber-950 leading-relaxed shadow-xs flex-shrink-0 max-h-40 overflow-y-auto">
                            <span class="font-bold uppercase tracking-wider text-[11px] text-amber-800 block mb-1.5 flex items-center gap-1.5">
                                <span>📄 Exact Manuscript Text:</span>
                            </span>
                            <p id="snippetText" class="font-serif italic text-[14px] leading-relaxed"></p>
                        </div>

                        <!-- Full Page Image Viewer with Hover Expand Hitbox -->
                        <div id="pageViewer" class="relative bg-slate-100 rounded border border-slate-300 flex-1 min-h-0 overflow-y-auto flex items-start justify-center p-3">
                            <div id="viewerPlaceholder" class="text-center p-8 text-slate-400">
                                <svg class="w-12 h-12 mx-auto mb-2 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                                <p class="text-sm">Click any inline coordinate pill to inspect the source page</p>
                            </div>
                            <div id="imageContainer" class="hidden relative inline-block">
                                <img id="highlightedImage" class="max-w-full h-auto rounded shadow select-none" alt="Source Page Preview"/>
                                <div id="highlightHitbox" title="Hover over the highlighted section to pop it up in large print!"></div>
                            </div>
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
            <div id="popupScrollContainer" class="p-4 bg-slate-100/70 overflow-y-auto overflow-x-auto flex items-start justify-center flex-1 min-h-0 w-full" style="max-height: calc(100vh - 90px);">
                <img id="popupCropImg" class="rounded border border-slate-200 shadow-sm bg-white" style="max-width: 100%; height: auto; object-fit: contain; transition: width 0.12s ease;" alt="Manuscript Section Crop"/>
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
                if (tabFinderBtn) tabFinderBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 hover:text-slate-900 flex items-center gap-1.5 text-xs font-medium";
                if (tabSummarizerBtn) tabSummarizerBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 hover:text-slate-900 flex items-center gap-1.5 text-xs font-medium";
                if (tabAppraisalBtn) tabAppraisalBtn.className = "px-3 py-1.5 rounded-md transition text-slate-600 hover:text-slate-900 flex items-center gap-1.5 text-xs font-medium";

                // Toggle visibility between sibling DOM containers
                if (finderCont) finderCont.classList.add('hidden');
                if (summarizerCont) summarizerCont.classList.add('hidden');
                if (resultBox) resultBox.classList.add('hidden');

                if (mode === 'finder') {
                    if (finderCont) finderCont.classList.remove('hidden');
                    if (tabFinderBtn) tabFinderBtn.className = "px-3 py-1.5 rounded-md bg-white text-sky-700 shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                } else if (mode === 'summarizer') {
                    if (summarizerCont) summarizerCont.classList.remove('hidden');
                    if (tabSummarizerBtn) tabSummarizerBtn.className = "px-3 py-1.5 rounded-md bg-white text-sky-700 shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
                    syncSummarizerInputFromBatch();
                } else {
                    // Mode 'appraisal'
                    if (tabAppraisalBtn) tabAppraisalBtn.className = "px-3 py-1.5 rounded-md bg-white text-sky-700 shadow-2xs font-bold transition flex items-center gap-1.5 text-xs";
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
                    banner.innerHTML = '<span>⚡ Running 4-tier query relaxation ladder across PubMed & Semantic Scholar...</span>';
                    banner.classList.remove('hidden');
                }

                try {
                    const resp = await fetch('/api/finder/search', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query, max_results: 10 })
                    });
                    const data = await resp.json();

                    window.ResearchAppState.finderResults = data.qualifying_papers || [];
                    window.ResearchAppState.lastSearchQuery = query;

                    if (data.status === 'success' && data.qualifying_papers && data.qualifying_papers.length > 0) {
                        const tierName = data.tier_used === 1 ? 'Tier 1 (Strict All Criteria)' : 
                                         data.tier_used === 2 ? 'Tier 2 (Relaxed Geography)' : 
                                         data.tier_used === 3 ? 'Tier 3 (Core Clinical Only)' : 'Tier 4 (Semantic Scholar Fallback)';
                        
                        banner.className = data.is_fallback ? 
                            "rounded-lg p-3 text-xs flex items-center justify-between border bg-amber-50 text-amber-900 border-amber-200" :
                            "rounded-lg p-3 text-xs flex items-center justify-between border bg-emerald-50 text-emerald-900 border-emerald-200";
                        
                        banner.innerHTML = `
                            <div class="flex items-center gap-2">
                                <span class="font-bold">${data.qualifying_count} Verified Studies Found</span>
                                <span class="text-slate-400">•</span>
                                <span>Source: ${data.source_database} (${tierName})</span>
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
                    
                    const sourceBadge = p.is_fallback ?
                        '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300">Semantic Scholar Fallback</span>' :
                        '<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">PubMed Verified</span>';

                    const hasFullText = Boolean(p.has_full_text || p.pmcid);
                    const fullTextBadge = hasFullText ?
                        `<span class="px-2 py-0.5 rounded text-[10px] font-bold bg-teal-50 text-teal-800 border border-teal-300 flex items-center gap-1" title="Free full text available on PubMed Central (${p.pmcid || 'PMC'})">
                            <span>🟢</span> <span>Free Full Text ${p.pmcid ? '(' + p.pmcid + ')' : ''}</span>
                        </span>` :
                        `<span class="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-200/80 text-slate-700 border border-slate-300 flex items-center gap-1" title="Paywalled: Only the published abstract is freely accessible. Full text requires institutional subscription or manual PDF upload.">
                            <span>🔒</span> <span>Paywalled (Abstract Only)</span>
                        </span>`;

                    const safeTitle = (p.title || 'Untitled Study').replace(/"/g, '&quot;');
                    const safeUrl = p.url || '';
                    const authorsStr = (p.authors && p.authors.length > 0) ? p.authors.slice(0, 3).join(', ') + (p.authors.length > 3 ? ' et al.' : '') : '';

                    const pmcLinkHtml = (hasFullText && p.pmcid) ? `
                        <a href="${p.pmc_url || ('https://pmc.ncbi.nlm.nih.gov/articles/' + p.pmcid + '/')}" target="_blank" rel="noopener noreferrer" class="text-xs text-teal-700 hover:text-teal-900 underline flex items-center gap-1 font-mono font-medium" title="View Open Access Full Text on PubMed Central">
                            <span>📄</span> <span>PMC: ${p.pmcid}</span>
                        </a>
                    ` : '';

                    const appraiseTargetUrl = (hasFullText && p.pmc_url) ? p.pmc_url : safeUrl;
                    const appraiseBtn = hasFullText ? `
                        <button 
                            onclick="appraisePaperFromExternal('${appraiseTargetUrl}')" 
                            class="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer"
                            title="Open full interactive appraisal in Workbench (Full manuscript retrieved via PMC)"
                        >
                            <span>🔬</span> <span>Appraise Full Text</span>
                        </button>
                    ` : `
                        <button 
                            onclick="appraisePaperFromExternal('${safeUrl}')" 
                            class="px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold transition shadow-2xs flex items-center gap-1 cursor-pointer"
                            title="Paywalled paper: Appraise published abstract or upload full-text PDF in Workbench"
                        >
                            <span>📄</span> <span>Appraise Abstract</span>
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
                                </div>
                                <div class="flex items-center gap-2">
                                    <button 
                                        onclick="addToSummarizerBatch('${safeUrl}', '${safeTitle}')" 
                                        class="px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold transition border border-slate-300 flex items-center gap-1 cursor-pointer"
                                        title="Add to multi-paper summarizer batch"
                                    >
                                        <span>➕</span> <span>Add to Summarizer</span>
                                    </button>
                                    ${appraiseBtn}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            // Summarizer Handlers
            function updateSummarizerBatchCount() {
                const textarea = document.getElementById('summarizerUrlsInput');
                const counter = document.getElementById('summarizerBatchCounter');
                if (!textarea || !counter) return;
                const lines = textarea.value.trim().split(/\n+/).filter(l => l.trim().length > 0);
                counter.innerText = `Batch size: ${lines.length} / 10 papers`;
                if (lines.length > 10) {
                    counter.className = "text-[11px] text-rose-600 font-bold";
                } else {
                    counter.className = "text-[11px] text-slate-400";
                }
            }

            function addToSummarizerBatch(url, title) {
                if (!url) return;
                if (!window.ResearchAppState.summarizerBatch.includes(url)) {
                    window.ResearchAppState.summarizerBatch.push(url);
                }
                updateSummarizerBadge();
                alert(`Added to Summarizer queue:
${title || url}`);
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
                if (textarea && window.ResearchAppState.summarizerBatch.length > 0) {
                    const currentVal = textarea.value.trim();
                    const existingList = currentVal ? currentVal.split(/\n+/).map(s => s.trim()) : [];
                    const combined = Array.from(new Set([...existingList, ...window.ResearchAppState.summarizerBatch])).filter(Boolean);
                    textarea.value = combined.join('\n');
                    updateSummarizerBatchCount();
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
                        body: JSON.stringify({ urls: lines, max_batch_size: 10 })
                    });
                    const data = await resp.json();

                    if (data.status === 'success') {
                        window.ResearchAppState.lastSummarizerMarkdown = data.formatted_markdown || '';
                        
                        banner.className = "rounded-lg p-3 text-xs flex items-center justify-between border bg-emerald-50 text-emerald-900 border-emerald-200";
                        banner.innerHTML = `
                            <span class="font-bold">✅ Briefing generated successfully (${data.accessible_count} accessible, ${data.inaccessible_count} unavailable).</span>
                            <span class="text-slate-500 font-mono text-[11px]">Model: ${data.model_designation || 'Gemini flash'}</span>
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
                    popupTitle.innerText = currentMeta.anchor_id || 'Highlighted Section';
                    const cropUrl = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(currentMeta.anchor_id)}`;
                    if (popupImg.src !== cropUrl && !popupImg.src.endsWith(cropUrl)) {
                        popupImg.src = cropUrl;
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

            function repositionHitbox(shouldScroll = false) {
                if (!currentMeta || !currentMeta.bbox) {
                    const hitbox = document.getElementById('highlightHitbox');
                    if (hitbox) hitbox.style.display = 'none';
                    return;
                }
                const img = document.getElementById('highlightedImage');
                const hitbox = document.getElementById('highlightHitbox');
                if (!img || img.naturalWidth === 0) return;

                if (img.clientWidth === 0) {
                    // Layout pending reflow; retry on next frame
                    requestAnimationFrame(() => repositionHitbox(shouldScroll));
                    return;
                }

                const pWidth = currentMeta.page_width || 581.0;
                
                // CSS scaling from natural PDF point coordinates to rendered client display width
                const scale = img.clientWidth / pWidth;

                const bbox = currentMeta.bbox;
                const left = bbox[0] * scale;
                const top = bbox[1] * scale;
                const width = (bbox[2] - bbox[0]) * scale;
                const height = (bbox[3] - bbox[1]) * scale;

                hitbox.style.left = Math.max(0, left - 4) + 'px';
                hitbox.style.top = Math.max(0, top - 3) + 'px';
                hitbox.style.width = (width + 8) + 'px';
                hitbox.style.height = (height + 6) + 'px';
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

                const activeClass = "px-2.5 py-1 rounded bg-white text-sky-700 shadow-2xs font-semibold transition";
                const inactiveClass = "px-2.5 py-1 rounded text-slate-600 hover:text-slate-900 transition";

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
                const thinkingView = document.getElementById('thinkingContainer');
                const tabAppraisalBtn = document.getElementById('leftTabAppraisalBtn');
                const tabThinkingBtn = document.getElementById('leftTabThinkingBtn');
                const hint = document.getElementById('leftPaneHint');

                const activeClass = "px-3 py-1 rounded-md bg-white text-sky-800 shadow-2xs font-semibold transition flex items-center gap-1.5 cursor-pointer";
                const inactiveClass = "px-3 py-1 rounded-md text-slate-600 hover:text-slate-900 transition flex items-center gap-1.5 cursor-pointer";

                if (tab === 'appraisal') {
                    appraisalView.classList.remove('hidden');
                    thinkingView.classList.add('hidden');
                    tabAppraisalBtn.className = activeClass;
                    tabThinkingBtn.className = inactiveClass;
                    if (hint) hint.innerText = "Click any coordinate pill to inspect source text";
                } else {
                    appraisalView.classList.add('hidden');
                    thinkingView.classList.remove('hidden');
                    tabThinkingBtn.className = activeClass;
                    tabAppraisalBtn.className = inactiveClass;
                    if (hint) hint.innerText = "Auditing triage rationale, rules AST & reasoning trace";
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

            function renderThinkingAudit(data) {
                const container = document.getElementById('thinkingContainer');
                if (!container) return;

                const triage = data.triage || {};
                const rulesDetail = data.active_rules_detail || [];
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

                // 2. Methodological Bias Rules
                let rulesListHtml = '';
                if (rulesDetail.length > 0) {
                    rulesListHtml = rulesDetail.map((r, idx) => `
                        <div class="bg-white border border-slate-200 rounded-md p-3.5 shadow-2xs hover:border-slate-300 transition">
                            <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
                                <div class="flex items-center gap-2">
                                    <span class="text-xs font-bold text-sky-800 bg-sky-100 px-2 py-0.5 rounded-full font-mono">${idx + 1}</span>
                                    <span class="text-xs font-bold text-slate-900">${escapeHtml(r.target_domain || 'Methodological Standard')}</span>
                                </div>
                                ${r.citation ? `<span class="text-[11px] font-medium text-slate-600 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">${escapeHtml(r.citation)}</span>` : ''}
                            </div>
                            <p class="text-xs text-slate-800 font-medium mb-2 leading-relaxed">
                                ${escapeHtml(r.appraisal_action || '')}
                            </p>
                            <div class="flex flex-wrap items-center gap-3 text-[11px] text-slate-500 pt-2 border-t border-slate-100">
                                ${r.citation ? `<span><strong class="text-slate-700 font-semibold">Guideline:</strong> ${escapeHtml(r.citation)}</span>` : ''}
                                ${r.directional_bias ? `<span><strong class="text-rose-700 font-semibold">Directional Risk:</strong> ${escapeHtml(r.directional_bias)}</span>` : ''}
                            </div>
                        </div>
                    `).join('');
                } else {
                    rulesListHtml = `
                        <div class="bg-white border border-slate-200 rounded-md p-4 text-xs text-slate-500 italic">
                            Standard methodological appraisal framework rules applied.
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
                    <div class="bg-slate-50 border border-slate-200 rounded-lg p-5">
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-3 border-b border-slate-200 pb-2.5">
                            <div class="flex items-center gap-2">
                                <span class="text-sm font-bold text-slate-800">2. Grounded Methodological Bias Rules</span>
                                <span class="px-2 py-0.5 rounded text-[11px] font-mono font-bold bg-amber-100 text-amber-900 border border-amber-200">${rulesDetail.length} Rules Active</span>
                            </div>
                            <span class="text-[11px] text-slate-500 font-mono">AST Rulebase v2.0</span>
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
                                notice.innerHTML = `
                                    <div class="flex items-center gap-2">
                                        <span class="text-amber-600 font-bold text-sm">⚠️</span>
                                        <span><strong>Full Text Unavailable:</strong> Paywalled study. Only official abstract available in PubMed registry.</span>
                                    </div>
                                    <span class="px-2 py-0.5 rounded bg-amber-200 text-amber-900 font-semibold text-[11px]">Abstract Only</span>
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

            async function proceedWithAbstractOnly() {
                document.getElementById('abstractModal').classList.add('hidden');
                if (!pendingResolution || !pendingResolution.pdf_filename) return;
                
                await executeAppraisalForFilename(pendingResolution.pdf_filename, true);
            }

            async function startUrlResolution() {
                closeSectionPopup();
                const urlInput = document.getElementById('paperUrl');
                const rawUrl = urlInput.value.trim();
                if (!rawUrl) {
                    alert('Please enter a paper URL, PMC ID, PMID, or DOI.');
                    return;
                }

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
                        document.getElementById('modalAbstractSnippet').innerText = data.abstract_text || '(Abstract text extracted from publication registry)';
                        document.getElementById('abstractModal').classList.remove('hidden');
                        statusText.innerHTML = '<span class="text-amber-700 font-medium">⚠️ Abstract only available.</span> Awaiting user confirmation to evaluate abstract...';
                        return;
                    }

                    // Full text PDF retrieved!
                    statusText.innerHTML = `<span class="font-semibold text-emerald-700">✓ ${data.message || 'Full text retrieved via PubMed API!'}</span> Starting appraisal pipeline...`;
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
                const statusBox = document.getElementById('statusBox');
                const statusText = document.getElementById('statusText');
                const spinner = document.getElementById('spinner');
                const statusIcon = document.getElementById('statusIcon');
                const resultBox = document.getElementById('resultBox');
                const resolveBtn = document.getElementById('resolveBtn');
                const runBtn = document.getElementById('runBtn');

                statusBox.classList.remove('hidden');
                statusText.innerText = isAbstractOnly ? 
                    'Extracting coordinates & appraising Abstract...' : 
                    'Ingesting full text layout, triaging & synthesizing appraisal...';

                const formData = new FormData();
                formData.append('filename', filename);

                try {
                    const res = await fetch('/appraise-fetched', { method: 'POST', body: formData });
                    const data = await res.json();

                    if (!res.ok) throw new Error(data.detail || 'Evaluation failed.');

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
                                : '<li>Standard critical appraisal framework</li>');
                        tipList.innerHTML = rulesList;
                    }
                }

                let content = data.final_markdown || data.raw_output || '';
                // Strip raw {R_...} or [R_...] rule tags if emitted by model
                content = content.replace(/\s*\{R_[A-Z0-9_]+\}/g, '').replace(/\s*\[R_[A-Z0-9_]+\]/g, '');

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

                if (window.marked) {
                    let html = marked.parse(content);
                    // Match coordinate blocks, supporting single, multi-paragraph, and compound citations
                    // e.g. [Results, Para 17; Discussion, Para 18], [Methods, Para 26; Results, Para 19], [Abstract, Para 2, 3; Methods, Para 3, 27]
                    const bracketCoordRegex = /\[([^\]]*?\b(?:Doc_Header|Para|Table|Fig)\b[^\]]*?)\]/gi;
                    html = html.replace(bracketCoordRegex, function(fullMatch, inner) {
                        const trimmed = inner.trim();
                        if (trimmed.toLowerCase() === 'doc_header') {
                            const enc = encodeURIComponent('[Doc_Header]');
                            return `<button onclick="inspectAnchor('${enc}')" class="anchor-pill inline-block px-2 py-0.5 mx-0.5 text-xs font-mono font-semibold bg-sky-50 text-sky-800 hover:bg-sky-600 hover:text-white border border-sky-300 rounded shadow-xs" title="Click to view source page and highlight">[Doc_Header]</button>`;
                        }

                        // Split compound coordinates by semicolon first, or by section-boundary comma
                        let parts = [];
                        if (trimmed.includes(';')) {
                            parts = trimmed.split(';').map(p => p.trim()).filter(Boolean);
                        } else {
                            parts = trimmed.split(/,\s*(?=[A-Za-z\s]+,\s*(?:Para|Table|Fig))/i).map(p => p.trim()).filter(Boolean);
                        }

                        if (!parts || parts.length === 0) {
                            parts = [trimmed];
                        }

                        const buttons = parts.map(part => {
                            const anchorLabel = `[${part}]`;
                            const enc = encodeURIComponent(anchorLabel);
                            return `<button onclick="inspectAnchor('${enc}')" class="anchor-pill inline-block px-2 py-0.5 mx-0.5 text-xs font-mono font-semibold bg-sky-50 text-sky-800 hover:bg-sky-600 hover:text-white border border-sky-300 rounded shadow-xs" title="Click to view source page and highlight">${anchorLabel}</button>`;
                        });

                        return buttons.join(' ');
                    });
                    
                    const container = document.getElementById('outputMarkdown');
                    container.innerHTML = html;

                    // Ensure all <a> tags open in a new tab and have classic hyperlink style
                    container.querySelectorAll('a').forEach(a => {
                        a.setAttribute('target', '_blank');
                        a.setAttribute('rel', 'noopener noreferrer');
                        a.classList.add('doi-link');
                        if (!a.getAttribute('title')) {
                            a.setAttribute('title', 'Open in new tab');
                        }
                    });

                    // Convert any unlinked DOI / PubMed text into live links
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
                } else {
                    document.getElementById('outputMarkdown').innerText = content;
                }

                // Populate Thinking & Audit Trail view (Behavior 3)
                renderThinkingAudit(data);
                switchLeftTab('appraisal');

                document.getElementById('resultBox').classList.remove('hidden');
                document.getElementById('statusBox').classList.add('hidden');

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
                closeSectionPopup();
                const fileInput = document.getElementById('pdfFile');
                if (!fileInput.files[0]) {
                    alert('Please select a PDF file to appraise.');
                    return;
                }

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
                statusText.innerText = 'Extracting PDF layout & coordinate anchors...';

                const formData = new FormData();
                formData.append('file', fileInput.files[0]);

                try {
                    statusText.innerText = 'Executing Stage 2 Triage & Stage 3 Scoped Synthesis...';
                    const res = await fetch('/appraise', { method: 'POST', body: formData });
                    const data = await res.json();

                    if (!res.ok) throw new Error(data.detail || 'Evaluation failed.');

                    renderAppraisalResults(data);
                } catch (err) {
                    spinner.classList.add('hidden');
                    alert('Error: ' + err.message);
                    statusText.innerText = 'Failed: ' + err.message;
                } finally {
                    runBtn.disabled = false;
                }
            }

            function inspectAnchor(encodedAnchor) {
                const anchor = decodeURIComponent(encodedAnchor);
                
                // Highlight active pill
                document.querySelectorAll('.anchor-pill').forEach(el => {
                    if (el.innerText.trim() === anchor) {
                        el.classList.add('active');
                    } else {
                        el.classList.remove('active');
                    }
                });

                let meta = anchorIndex[anchor];
                let resolvedAnchorId = (meta && meta.anchor_id) ? meta.anchor_id : anchor;

                // Support multi-paragraph citations, ranges (e.g. [Abstract, Para 1-3], [Results, Para 2, 8]), etc.
                if (!meta) {
                    const match = anchor.match(/\[?\s*([A-Za-z\s&]+?)\s*,\s*Para\s+(\d+)/i);
                    if (match) {
                        const fallbackId = `[${match[1].trim()}, Para ${match[2]}]`;
                        meta = anchorIndex[fallbackId];
                        if (meta) {
                            resolvedAnchorId = fallbackId;
                        } else {
                            const pNum = parseInt(match[2]);
                            for (const [k, v] of Object.entries(anchorIndex)) {
                                if (k.toLowerCase().includes(match[1].trim().toLowerCase()) && k.includes(`Para ${pNum}`)) {
                                    meta = v;
                                    resolvedAnchorId = k;
                                    break;
                                }
                            }
                        }
                    }
                }

                // Support Table or Figure citations (e.g. [Results, Table 1], [Discussion, Fig 2])
                if (!meta) {
                    const tblFigMatch = anchor.match(/\[?\s*([A-Za-z\s&]+?)\s*,\s*(Table|Fig)\s*(\d+)/i);
                    if (tblFigMatch) {
                        const itemType = tblFigMatch[2].charAt(0).toUpperCase() + tblFigMatch[2].slice(1).toLowerCase();
                        const fallbackId = `[${tblFigMatch[1].trim()}, ${itemType} ${tblFigMatch[3]}]`;
                        meta = anchorIndex[fallbackId];
                        if (meta) {
                            resolvedAnchorId = fallbackId;
                        } else {
                            for (const [k, v] of Object.entries(anchorIndex)) {
                                if (k.toLowerCase().includes(tblFigMatch[1].trim().toLowerCase()) && k.toLowerCase().includes(`${itemType.toLowerCase()} ${tblFigMatch[3]}`)) {
                                    meta = v;
                                    resolvedAnchorId = k;
                                    break;
                                }
                            }
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
                const imgContainer = document.getElementById('imageContainer');
                const img = document.getElementById('highlightedImage');
                const placeholder = document.getElementById('viewerPlaceholder');

                subtitle.innerText = anchor;

                if (meta) {
                    currentMeta = Object.assign({ anchor_id: anchor }, meta);
                    pageBadge.innerText = 'Page ' + meta.page;
                    pageBadge.classList.remove('hidden');
                    snippetText.innerText = meta.text;
                    snippetBox.classList.remove('hidden');

                    // If popup is pinned, update it to the new anchor
                    if (isPinned) {
                        const popupTitle = document.getElementById('popupTitle');
                        const popupImg = document.getElementById('popupCropImg');
                        if (popupTitle) popupTitle.innerText = anchor;
                        const cropAnchorId = (meta && meta.anchor_id) ? meta.anchor_id : anchor;
                        if (popupImg) popupImg.src = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(cropAnchorId)}`;
                    } else {
                        const popup = document.getElementById('sectionPopup');
                        if (popup) popup.style.display = 'none';
                    }
                } else {
                    currentMeta = null;
                    pageBadge.classList.add('hidden');
                    snippetBox.classList.add('hidden');
                    const popup = document.getElementById('sectionPopup');
                    if (popup) popup.style.display = 'none';
                }

                placeholder.classList.add('hidden');
                imgContainer.classList.remove('hidden');

                const targetAnchorId = (meta && meta.anchor_id) ? meta.anchor_id : anchor;
                const imgUrl = `/view-anchor-image?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(targetAnchorId)}`;
                
                const applyPosition = () => {
                    repositionHitbox(true);
                    setTimeout(() => repositionHitbox(true), 80);
                    setTimeout(() => repositionHitbox(true), 250);
                };

                // If image URL is already loaded and ready, immediately reposition and center
                if (img.src && (img.src === imgUrl || img.src.endsWith(imgUrl)) && img.complete && img.naturalWidth > 0) {
                    applyPosition();
                } else {
                    img.onload = function() {
                        applyPosition();
                    };
                    img.onerror = function() {
                        placeholder.innerHTML = '<p class="text-sm text-red-500">Failed to render page image for this coordinate.</p>';
                        placeholder.classList.remove('hidden');
                        imgContainer.classList.add('hidden');
                    };
                    img.src = imgUrl;
                    if (img.complete && img.naturalWidth > 0) {
                        applyPosition();
                    }
                }
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
