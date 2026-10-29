import os
import shutil
import io
import urllib.parse
from typing import Optional, Dict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import pymupdf
from PIL import Image

from src.ingestion.indexer import parse_and_index_pdf, IndexedDocument
from src.ingestion.fetcher import PaperFetcher
from src.appraisal.generator import SynthesisEngine, PRIMARY_MODEL, PRO_REASONING_MODEL

app = FastAPI(
    title="Research Evaluation App",
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

engine = SynthesisEngine(DATA_DIR)
fetcher = PaperFetcher(UPLOAD_DIR)

# In-memory session cache of the most recently indexed document
CACHED_INDEX: Dict[str, IndexedDocument] = {}

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
    meta = indexed.anchor_metadata.get(anchor_clean)
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
    meta = indexed.anchor_metadata.get(anchor_clean)
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
        <title>Research Evaluation App - Clinical Appraiser</title>
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
                border: none;
                background-color: transparent;
                border-radius: 4px;
                z-index: 25;
                pointer-events: auto;
            }
            #sectionPopup {
                position: fixed;
                display: none;
                z-index: 9999;
                width: 740px;
                max-width: calc(100vw - 32px);
                max-height: calc(100vh - 40px);
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
            }
            #popupHeader:active {
                cursor: grabbing;
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
        </style>
    </head>
    <body class="bg-slate-50 text-slate-800 min-h-screen p-6">
        <div class="max-w-7xl mx-auto space-y-6">
            <!-- Header -->
            <header class="border-b border-slate-200 pb-4 flex justify-between items-center bg-white p-6 rounded-lg shadow-sm">
                <div>
                    <h1 class="text-3xl font-bold text-sky-700">Research Evaluation App</h1>
                    <p class="text-slate-500 text-sm mt-1">Deterministic Clinical Research Appraiser with Interactive Source Grounding</p>
                </div>
                <div class="text-right text-xs text-slate-500">
                    <span class="inline-block px-3 py-1 bg-sky-50 text-sky-700 rounded-full border border-sky-200 font-medium">Model: gemini-3.1-flash-lite</span>
                </div>
            </header>

            <!-- Input Tabs Panel: Upload PDF vs Paper URL / PubMed -->
            <div class="bg-white p-6 rounded-lg border border-slate-200 shadow-sm space-y-4">
                <div class="flex border-b border-slate-200 gap-6">
                    <button id="tabPdfBtn" onclick="switchInputTab('pdf')" class="pb-2.5 font-semibold text-sm border-b-2 border-sky-600 text-sky-700 transition">📄 Upload PDF File</button>
                    <button id="tabUrlBtn" onclick="switchInputTab('url')" class="pb-2.5 font-semibold text-sm border-b-2 border-transparent text-slate-500 hover:text-slate-800 transition">🔗 Enter Paper URL, PMC, or PubMed ID</button>
                </div>

                <!-- Tab 1: Local PDF Upload -->
                <div id="tabPdf" class="flex gap-4 items-center pt-2">
                    <input type="file" id="pdfFile" accept=".pdf" class="block w-full text-sm text-slate-600 file:mr-4 file:py-2.5 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-700 cursor-pointer bg-slate-50 p-2 rounded-md border border-slate-200"/>
                    <button onclick="startAppraisal()" id="runBtn" class="bg-sky-600 hover:bg-sky-700 text-white font-semibold px-6 py-2.5 rounded-md transition shadow">Evaluate</button>
                </div>

                <!-- Tab 2: URL / PMC / PubMed Resolution -->
                <div id="tabUrl" class="hidden space-y-3 pt-2">
                    <div class="flex gap-3 items-center">
                        <input type="text" id="paperUrl" placeholder="Paste PubMed link, PMID (e.g. 37726553), PMC ID (e.g. PMC10643434), or DOI" class="block w-full text-sm text-slate-800 bg-slate-50 px-4 py-2.5 rounded-md border border-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500"/>
                        <button onclick="startUrlResolution()" id="resolveBtn" class="bg-sky-600 hover:bg-sky-700 text-white font-semibold px-6 py-2.5 rounded-md transition shadow flex-shrink-0">Fetch & Evaluate</button>
                    </div>
                    <!-- Live Availability Banner for PubMed / PMC -->
                    <div id="availabilityNotice" class="hidden p-3 rounded-lg text-xs flex items-center justify-between border transition-all"></div>
                    <p class="text-xs text-slate-400">Supports PubMed links, PMIDs, and PubMed Central (PMC). If free full text is found, it will be automatically fetched using the PubMed API; if paywalled, you will be prompted to evaluate the abstract only.</p>
                </div>
            </div>

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

            <!-- Status Indicator -->
            <div id="statusBox" class="hidden p-4 rounded-lg bg-white border border-slate-200 shadow-sm space-y-2">
                <div class="flex items-center gap-2">
                    <div id="spinner" class="animate-spin rounded-full h-4 w-4 border-2 border-sky-600 border-t-transparent"></div>
                    <span id="statusIcon" class="hidden text-emerald-600 font-bold">✓</span>
                    <span id="statusText" class="text-sm font-medium text-slate-700">Processing...</span>
                </div>
            </div>

            <!-- Results Section: Split Screen -->
            <div id="resultBox" class="hidden space-y-6">
                <!-- Triage Metrics Bar -->
                <div class="grid grid-cols-3 gap-4">
                    <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
                        <span class="text-xs uppercase tracking-wider font-semibold text-slate-400">Framework ID</span>
                        <p id="fwId" class="text-base font-bold text-sky-700 mt-1">-</p>
                    </div>
                    <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
                        <span class="text-xs uppercase tracking-wider font-semibold text-slate-400">Triggered Rules</span>
                        <p id="rulesCount" class="text-base font-bold text-sky-700 mt-1">0</p>
                    </div>
                    <div class="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
                        <span class="text-xs uppercase tracking-wider font-semibold text-slate-400">Anchors Indexed</span>
                        <p id="anchorCount" class="text-base font-bold text-emerald-600 mt-1">0</p>
                    </div>
                </div>

                <!-- Draggable Split Container: Left Appraisal | Resizer | Right Source Inspector -->
                <div id="splitContainer" class="flex flex-row w-full gap-0 select-none items-stretch">
                    <!-- Left: Clinical Appraisal -->
                    <div id="leftPane" class="bg-white p-6 rounded-l-lg border border-slate-200 shadow-sm overflow-y-auto select-text" style="width: 55%; min-width: 25%; max-width: 75%;">
                        <div class="flex justify-between items-center mb-4 border-b border-slate-200 pb-2">
                            <h3 class="text-lg font-semibold text-slate-800">Structured Clinical Appraisal</h3>
                            <span class="text-xs text-slate-400 italic">Click any coordinate pill to inspect source text</span>
                        </div>
                        <div id="outputMarkdown" class="prose max-w-none text-slate-800 bg-slate-50 p-6 rounded-lg border border-slate-200 text-sm leading-relaxed"></div>
                    </div>

                    <!-- Draggable Divider Bar -->
                    <div id="dragDivider" class="resizer mx-1" title="Drag left or right to resize panels"></div>

                    <!-- Right: Interactive Source Inspector -->
                    <div id="rightPane" class="bg-white p-6 rounded-r-lg border border-slate-200 shadow-sm flex flex-col space-y-4 select-text" style="width: 45%; min-width: 25%; max-width: 75%;">
                        <div class="border-b border-slate-200 pb-3 flex justify-between items-center">
                            <div>
                                <h3 class="text-base font-semibold text-slate-800">Source Evidence Inspector</h3>
                                <p id="inspectSubtitle" class="text-xs text-slate-500 mt-0.5">Select any coordinate pill on the left</p>
                            </div>
                            <div class="flex items-center gap-2">
                                <span id="pageBadge" class="hidden px-2.5 py-1 text-xs font-semibold rounded bg-sky-100 text-sky-800 border border-sky-200">Page -</span>
                            </div>
                        </div>

                        <!-- Snippet Text Box (Large Readable Typography) -->
                        <div id="snippetBox" class="hidden p-4 rounded-md bg-amber-50 border border-amber-200 text-sm text-amber-950 leading-relaxed shadow-xs">
                            <span class="font-bold uppercase tracking-wider text-[11px] text-amber-800 block mb-1.5 flex items-center gap-1.5">
                                <span>📄 Exact Manuscript Text:</span>
                            </span>
                            <p id="snippetText" class="font-serif italic text-[14px] leading-relaxed"></p>
                        </div>

                        <!-- Full Page Image Viewer with Hover Expand Hitbox -->
                        <div id="pageViewer" class="relative bg-slate-100 rounded border border-slate-300 min-h-[500px] flex-1 overflow-y-auto flex items-center justify-center p-2">
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
            <div id="popupScrollContainer" class="p-4 bg-slate-100/70 overflow-y-auto overflow-x-auto flex items-start justify-center" style="max-height: calc(85vh - 55px);">
                <img id="popupCropImg" class="rounded border border-slate-200 shadow-sm bg-white" style="max-width: 100%; height: auto; object-fit: contain; transition: width 0.12s ease;" alt="Manuscript Section Crop"/>
            </div>
        </div>

        <script>
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
                    
                    // Reposition hitbox after panel width change
                    repositionHitbox();
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

            function adjustPopupZoom(delta) {
                currentZoom = Math.max(0.6, Math.min(2.0, Math.round((currentZoom + delta) * 100) / 100));
                applyZoom();
            }

            function resetPopupZoom() {
                currentZoom = 1.0;
                applyZoom();
            }

            function applyZoom() {
                const img = document.getElementById('popupCropImg');
                const label = document.getElementById('popupZoomLevel');
                if (!img) return;
                const baseW = 680;
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
                    if (popup.style.display !== 'block') {
                        popup.style.display = 'block';
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
                    const popW = Math.min(740, window.innerWidth - 32);
                    popup.style.width = popW + 'px';

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

                    const popH = popup.offsetHeight || 480;
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

            function repositionHitbox() {
                if (!currentMeta || !currentMeta.bbox) {
                    const hitbox = document.getElementById('highlightHitbox');
                    if (hitbox) hitbox.style.display = 'none';
                    return;
                }
                const img = document.getElementById('highlightedImage');
                const hitbox = document.getElementById('highlightHitbox');
                if (!img || img.naturalWidth === 0) return;

                // When consecutive pages are stitched, naturalHeight reflects both pages + 16px divider
                // Calculate exact single page dimensions
                const pWidth = currentMeta.page_width || 547.0;
                const pHeight = currentMeta.page_height || 737.0;

                // Scale factor from PDF points (72 DPI) to rendered image natural pixels (150 DPI)
                const ptToPx = img.naturalWidth / pWidth;
                
                // CSS scaling from natural image dimensions to client display width/height
                const cssScale = img.clientWidth / img.naturalWidth;

                const bbox = currentMeta.bbox;
                const left = bbox[0] * ptToPx * cssScale;
                const top = bbox[1] * ptToPx * cssScale;
                const width = (bbox[2] - bbox[0]) * ptToPx * cssScale;
                const height = (bbox[3] - bbox[1]) * ptToPx * cssScale;

                hitbox.style.left = Math.max(0, left - 4) + 'px';
                hitbox.style.top = Math.max(0, top - 3) + 'px';
                hitbox.style.width = (width + 8) + 'px';
                hitbox.style.height = (height + 6) + 'px';
                hitbox.style.display = 'block';
            }

            window.addEventListener('resize', repositionHitbox);

            function switchInputTab(tab) {
                const tabPdf = document.getElementById('tabPdf');
                const tabUrl = document.getElementById('tabUrl');
                const tabPdfBtn = document.getElementById('tabPdfBtn');
                const tabUrlBtn = document.getElementById('tabUrlBtn');

                if (tab === 'pdf') {
                    tabPdf.classList.remove('hidden');
                    tabUrl.classList.add('hidden');
                    tabPdfBtn.className = "pb-2.5 font-semibold text-sm border-b-2 border-sky-600 text-sky-700 transition";
                    tabUrlBtn.className = "pb-2.5 font-semibold text-sm border-b-2 border-transparent text-slate-500 hover:text-slate-800 transition";
                } else {
                    tabPdf.classList.add('hidden');
                    tabUrl.classList.remove('hidden');
                    tabUrlBtn.className = "pb-2.5 font-semibold text-sm border-b-2 border-sky-600 text-sky-700 transition";
                    tabPdfBtn.className = "pb-2.5 font-semibold text-sm border-b-2 border-transparent text-slate-500 hover:text-slate-800 transition";
                }
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
                spinner.classList.remove('hidden');
                statusIcon.classList.add('hidden');
                resultBox.classList.add('hidden');
                resolveBtn.disabled = true;

                // Step 1: Pre-check full-text availability via PubMed API
                statusText.innerHTML = '<span class="font-medium text-sky-700">Checking PubMed API for full-text availability...</span>';

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
                spinner.classList.remove('hidden');
                statusIcon.classList.add('hidden');
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

                document.getElementById('fwId').innerText = data.triage.primary_framework_id + ': ' + data.triage.framework_name;
                document.getElementById('rulesCount').innerText = data.triage.applicable_rules.length + ' rules';
                document.getElementById('anchorCount').innerText = data.total_anchors_indexed + ' anchors';

                let content = data.final_markdown || data.raw_output;

                if (window.marked) {
                    let html = marked.parse(content);
                    const anchorRegex = /(\[(?:Doc_Header|Supp_[^,\]]+|[A-Za-z\s]+),\s*(?:Para\s+\d+|Table\s+\d+|Fig\s+\d+)\]|\[Doc_Header\])/g;
                    html = html.replace(anchorRegex, function(match) {
                        const enc = encodeURIComponent(match);
                        return `<button onclick="inspectAnchor('${enc}')" class="anchor-pill inline-block px-2 py-0.5 mx-0.5 text-xs font-mono font-semibold bg-sky-50 text-sky-800 hover:bg-sky-600 hover:text-white border border-sky-300 rounded shadow-xs" title="Click to view source page and highlight">${match}</button>`;
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

                document.getElementById('resultBox').classList.remove('hidden');
                document.getElementById('spinner').classList.add('hidden');
                document.getElementById('statusIcon').classList.remove('hidden');
                document.getElementById('statusText').innerText = 'Appraisal complete.';

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
                spinner.classList.remove('hidden');
                statusIcon.classList.add('hidden');
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

                const meta = anchorIndex[anchor];
                const subtitle = document.getElementById('inspectSubtitle');
                const pageBadge = document.getElementById('pageBadge');
                const snippetBox = document.getElementById('snippetBox');
                const snippetText = document.getElementById('snippetText');
                const cropCard = document.getElementById('cropCard');
                const cropImg = document.getElementById('cropImage');
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
                        if (popupImg) popupImg.src = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(anchor)}`;
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

                // Load full page image with highlight
                placeholder.classList.remove('hidden');
                imgContainer.classList.add('hidden');

                const imgUrl = `/view-anchor-image?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(anchor)}`;
                img.onload = function() {
                    placeholder.classList.add('hidden');
                    imgContainer.classList.remove('hidden');
                    // Position highlight hitbox precisely over the yellow section
                    setTimeout(repositionHitbox, 50);
                };
                img.onerror = function() {
                    placeholder.innerHTML = '<p class="text-sm text-red-500">Failed to render page image for this coordinate.</p>';
                    placeholder.classList.remove('hidden');
                    imgContainer.classList.add('hidden');
                };
                img.src = imgUrl;
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
