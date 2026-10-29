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
                "section": meta.section,
                "text": meta.text[:250],
                "bbox": meta.bbox
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
            max(0, rect.x0 - 20),
            max(0, rect.y0 - 15),
            min(page.rect.width, rect.x1 + 20),
            min(page.rect.height, rect.y1 + 15)
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
                max(0, rect2.x0 - 20),
                max(0, rect2.y0 - 15),
                min(p_next.rect.width, rect2.x1 + 20),
                min(p_next.rect.height, rect2.y1 + 15)
            )
            pix2 = p_next.get_pixmap(clip=crop_rect2, dpi=250)
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
    return """
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
                cursor: pointer;
                border: 2px dashed rgba(2, 132, 199, 0.6);
                background-color: rgba(2, 132, 199, 0.05);
                border-radius: 4px;
                transition: all 0.15s ease;
                z-index: 20;
            }
            #highlightHitbox:hover {
                border-color: #0284c7;
                background-color: rgba(2, 132, 199, 0.12);
            }
            #sectionPopup {
                position: fixed;
                display: none;
                z-index: 9999;
                max-width: 580px;
                background: #ffffff;
                border: 2px solid #0284c7;
                border-radius: 12px;
                box-shadow: 0 20px 30px -10px rgba(0, 0, 0, 0.35), 0 10px 15px -5px rgba(0, 0, 0, 0.1);
                overflow: hidden;
                pointer-events: none;
                animation: popIn 0.15s ease-out;
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

            <!-- Upload Panel -->
            <div class="bg-white p-6 rounded-lg border border-slate-200 shadow-sm space-y-4">
                <h2 class="text-lg font-semibold text-slate-800">Upload Clinical Research Manuscript (PDF)</h2>
                <div class="flex gap-4 items-center">
                    <input type="file" id="pdfFile" accept=".pdf" class="block w-full text-sm text-slate-600 file:mr-4 file:py-2.5 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-700 cursor-pointer bg-slate-50 p-2 rounded-md border border-slate-200"/>
                    <button onclick="startAppraisal()" id="runBtn" class="bg-sky-600 hover:bg-sky-700 text-white font-semibold px-6 py-2.5 rounded-md transition shadow">Evaluate</button>
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

        <!-- Hover Popup Card for the Highlighted Section -->
        <div id="sectionPopup">
            <div class="bg-sky-700 text-white px-4 py-2 flex justify-between items-center text-xs font-semibold">
                <span id="popupTitle">Highlighted Manuscript Section</span>
                <span class="opacity-80">Full-Section Pop-Up</span>
            </div>
            <div class="p-3 bg-white">
                <img id="popupCropImg" class="w-full h-auto rounded border border-slate-200" alt="Large Section Crop"/>
            </div>
        </div>
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

            // Section Hover Popup Implementation
            (function initSectionPopup() {
                const hitbox = document.getElementById('highlightHitbox');
                const popup = document.getElementById('sectionPopup');
                const popupImg = document.getElementById('popupCropImg');
                const popupTitle = document.getElementById('popupTitle');

                hitbox.addEventListener('mouseenter', function(e) {
                    if (!currentMeta) return;
                    popupTitle.innerText = currentMeta.anchor_id || 'Highlighted Section';
                    popupImg.src = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(currentMeta.anchor_id)}`;
                    
                    // Calculate pop-up coordinates near the cursor but staying within screen bounds
                    popup.style.display = 'block';
                    positionPopup(e);
                });

                hitbox.addEventListener('mousemove', function(e) {
                    positionPopup(e);
                });

                hitbox.addEventListener('mouseleave', function() {
                    popup.style.display = 'none';
                });

                function positionPopup(e) {
                    const margin = 20;
                    const popW = 560;
                    const popH = 340;
                    
                    let left = e.clientX - popW - margin;
                    // If not enough room on the left, put it on the right
                    if (left < 20) {
                        left = e.clientX + margin;
                    }
                    
                    let top = e.clientY - (popH / 2);
                    if (top < 20) top = 20;
                    if (top + popH > window.innerHeight - 20) {
                        top = window.innerHeight - popH - 20;
                    }
                    
                    popup.style.left = left + 'px';
                    popup.style.top = top + 'px';
                }
            })();

            function repositionHitbox() {
                if (!currentMeta || !currentMeta.bbox) return;
                const img = document.getElementById('highlightedImage');
                const hitbox = document.getElementById('highlightHitbox');
                if (!img || img.naturalWidth === 0) return;

                // PDF standard points to rendered image scaling
                // PyMuPDF page standard 72 pt width vs rendered img naturalWidth at 200 DPI
                // Calculate actual scale ratio
                const scaleX = img.clientWidth / (img.naturalWidth / (200 / 72));
                const scaleY = img.clientHeight / (img.naturalHeight / (200 / 72));

                const bbox = currentMeta.bbox;
                const left = bbox[0] * scaleX;
                const top = bbox[1] * scaleY;
                const width = (bbox[2] - bbox[0]) * scaleX;
                const height = (bbox[3] - bbox[1]) * scaleY;

                hitbox.style.left = left + 'px';
                hitbox.style.top = top + 'px';
                hitbox.style.width = width + 'px';
                hitbox.style.height = height + 'px';
                hitbox.style.display = 'block';
            }

            window.addEventListener('resize', repositionHitbox);

            async function startAppraisal() {
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

                    anchorIndex = data.anchor_index || {};

                    document.getElementById('fwId').innerText = data.triage.primary_framework_id + ': ' + data.triage.framework_name;
                    document.getElementById('rulesCount').innerText = data.triage.applicable_rules.length + ' rules';
                    document.getElementById('anchorCount').innerText = data.total_anchors_indexed + ' anchors';

                    let content = data.final_markdown || data.raw_output;

                    // Render formatted markdown with interactive clickable pills
                    if (window.marked) {
                        let html = marked.parse(content);
                        // Convert anchor tags [Section, Para X] into interactive button pills
                        const anchorRegex = /(\[(?:Doc_Header|Supp_[^,\]]+|[A-Za-z\s]+),\s*(?:Para\s+\d+|Table\s+\d+|Fig\s+\d+)\]|\[Doc_Header\])/g;
                        html = html.replace(anchorRegex, function(match) {
                            const enc = encodeURIComponent(match);
                            return `<button onclick="inspectAnchor('${enc}')" class="anchor-pill inline-block px-2 py-0.5 mx-0.5 text-xs font-mono font-semibold bg-sky-50 text-sky-800 hover:bg-sky-600 hover:text-white border border-sky-300 rounded shadow-xs" title="Click to view source page and highlight">${match}</button>`;
                        });
                        document.getElementById('outputMarkdown').innerHTML = html;
                    } else {
                        document.getElementById('outputMarkdown').innerText = content;
                    }

                    resultBox.classList.remove('hidden');
                    spinner.classList.add('hidden');
                    statusIcon.classList.remove('hidden');
                    statusText.innerText = 'Appraisal complete.';

                    // If pills exist, auto-select the first anchor pill to showcase the viewer
                    const firstPill = document.querySelector('.anchor-pill');
                    if (firstPill) {
                        firstPill.click();
                    }
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
                } else {
                    currentMeta = null;
                    pageBadge.classList.add('hidden');
                    snippetBox.classList.add('hidden');
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
