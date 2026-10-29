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
    """Render a high-resolution PNG of the PDF page with the anchor bounding box highlighted."""
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
    
    # If a bounding box exists, apply a bright translucent yellow highlight
    if meta.bbox and len(meta.bbox) == 4:
        rect = pymupdf.Rect(meta.bbox[0], meta.bbox[1], meta.bbox[2], meta.bbox[3])
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(1.0, 0.85, 0.0))  # Vivid golden amber highlight
        annot.update()
        
    # Render at crisp 200 DPI for high legibility
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    doc.close()
    
    return Response(content=img_bytes, media_type="image/png")

@app.get("/view-anchor-crop")
def view_anchor_crop(
    filename: str = Query(...),
    anchor: str = Query(...)
):
    """Render an ultra-clear, zoomed crop of specifically the highlighted paragraph."""
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
    
    if meta.bbox and len(meta.bbox) == 4:
        rect = pymupdf.Rect(meta.bbox[0], meta.bbox[1], meta.bbox[2], meta.bbox[3])
        # Add a subtle highlight
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(1.0, 0.9, 0.2))
        annot.update()
        # Generous padding around the box for context
        crop_rect = pymupdf.Rect(
            max(0, rect.x0 - 25),
            max(0, rect.y0 - 20),
            min(page.rect.width, rect.x1 + 25),
            min(page.rect.height, rect.y1 + 20)
        )
        pix = page.get_pixmap(clip=crop_rect, dpi=250)
    else:
        pix = page.get_pixmap(dpi=200)
        
    img_bytes = pix.tobytes("png")
    doc.close()
    return Response(content=img_bytes, media_type="image/png")

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
            /* Hover zoom / magnifier lens for the manuscript page */
            #imageContainer {
                position: relative;
                overflow: hidden;
                cursor: crosshair;
            }
            #zoomLens {
                position: absolute;
                border: 2px solid #0284c7;
                background-color: rgba(255, 255, 255, 0.95);
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.25), 0 8px 10px -6px rgba(0, 0, 0, 0.2);
                border-radius: 8px;
                pointer-events: none;
                display: none;
                z-index: 50;
                width: 280px;
                height: 180px;
                background-repeat: no-repeat;
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
                                <button onclick="toggleZoomMode()" id="zoomBtn" class="px-2.5 py-1 text-xs font-medium rounded bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-300 transition" title="Toggle 2.5x hover magnifier lens">🔍 Magnifier: ON</button>
                            </div>
                        </div>

                        <!-- Snippet Text Box (Large Readable Typography) -->
                        <div id="snippetBox" class="hidden p-4 rounded-md bg-amber-50 border border-amber-200 text-sm text-amber-950 leading-relaxed shadow-xs">
                            <span class="font-bold uppercase tracking-wider text-[11px] text-amber-800 block mb-1.5 flex items-center gap-1.5">
                                <span>📄 Exact Manuscript Paragraph:</span>
                            </span>
                            <p id="snippetText" class="font-serif italic text-[13.5px]"></p>
                        </div>

                        <!-- Ultra-Clear Zoomed Crop Card -->
                        <div id="cropCard" class="hidden rounded-md border border-sky-200 bg-sky-50/50 p-3">
                            <span class="font-bold uppercase tracking-wider text-[11px] text-sky-800 block mb-1">🔍 High-Resolution Target Excerpt:</span>
                            <img id="cropImage" class="w-full h-auto rounded border border-slate-200 shadow-sm bg-white" alt="Zoomed Excerpt"/>
                        </div>

                        <!-- Full Page Image Viewer with Hover Magnifier -->
                        <div id="pageViewer" class="relative bg-slate-100 rounded border border-slate-300 min-h-[500px] flex-1 overflow-y-auto flex items-center justify-center p-2">
                            <div id="viewerPlaceholder" class="text-center p-8 text-slate-400">
                                <svg class="w-12 h-12 mx-auto mb-2 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                                <p class="text-sm">Click any inline coordinate pill to inspect the source page</p>
                            </div>
                            <div id="imageContainer" class="hidden relative inline-block">
                                <img id="highlightedImage" class="max-w-full h-auto rounded shadow select-none" alt="Source Page Preview"/>
                                <div id="zoomLens"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let currentFilename = '';
            let anchorIndex = {};
            let isMagnifierEnabled = true;

            function toggleZoomMode() {
                isMagnifierEnabled = !isMagnifierEnabled;
                const btn = document.getElementById('zoomBtn');
                const lens = document.getElementById('zoomLens');
                if (isMagnifierEnabled) {
                    btn.innerText = '🔍 Magnifier: ON';
                    btn.classList.add('bg-sky-100', 'text-sky-800');
                    btn.classList.remove('bg-slate-100', 'text-slate-700');
                } else {
                    btn.innerText = '🔍 Magnifier: OFF';
                    btn.classList.remove('bg-sky-100', 'text-sky-800');
                    btn.classList.add('bg-slate-100', 'text-slate-700');
                    lens.style.display = 'none';
                }
            }

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

            // Interactive Magnifier Lens Implementation
            (function initMagnifier() {
                const img = document.getElementById('highlightedImage');
                const lens = document.getElementById('zoomLens');
                const container = document.getElementById('imageContainer');

                container.addEventListener('mousemove', function(e) {
                    if (!isMagnifierEnabled || !img.src) {
                        lens.style.display = 'none';
                        return;
                    }

                    const rect = img.getBoundingClientRect();
                    const x = e.clientX - rect.left;
                    const y = e.clientY - rect.top;

                    // Only activate if inside the image bounds
                    if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
                        lens.style.display = 'none';
                        return;
                    }

                    lens.style.display = 'block';
                    lens.style.backgroundImage = `url('${img.src}')`;

                    // Zoom factor: 2.2x
                    const zoom = 2.2;
                    lens.style.backgroundSize = `${rect.width * zoom}px ${rect.height * zoom}px`;

                    const lensW = lens.offsetWidth;
                    const lensH = lens.offsetHeight;

                    // Position lens centered above mouse
                    let lensX = x - (lensW / 2);
                    let lensY = y - (lensH / 2);

                    lens.style.left = `${lensX}px`;
                    lens.style.top = `${lensY}px`;

                    // Position background to magnify target
                    const bgX = -(x * zoom - lensW / 2);
                    const bgY = -(y * zoom - lensH / 2);
                    lens.style.backgroundPosition = `${bgX}px ${bgY}px`;
                });

                container.addEventListener('mouseleave', function() {
                    lens.style.display = 'none';
                });
            })();

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
                    pageBadge.innerText = 'Page ' + meta.page;
                    pageBadge.classList.remove('hidden');
                    snippetText.innerText = meta.text;
                    snippetBox.classList.remove('hidden');

                    // Load high-resolution cropped excerpt
                    cropImg.src = `/view-anchor-crop?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(anchor)}`;
                    cropCard.classList.remove('hidden');
                } else {
                    pageBadge.classList.add('hidden');
                    snippetBox.classList.add('hidden');
                    cropCard.classList.add('hidden');
                }

                // Load full page image with highlight
                placeholder.classList.remove('hidden');
                imgContainer.classList.add('hidden');

                const imgUrl = `/view-anchor-image?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(anchor)}`;
                img.onload = function() {
                    placeholder.classList.add('hidden');
                    imgContainer.classList.remove('hidden');
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
