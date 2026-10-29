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
        
    pix = page.get_pixmap(dpi=150)
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

                <!-- Side-by-Side: Structured Appraisal (Left) & Highlighted Source Evidence (Right) -->
                <div class="grid grid-cols-12 gap-6 items-start">
                    <!-- Left: Clinical Appraisal (7 Columns) -->
                    <div class="col-span-7 bg-white p-6 rounded-lg border border-slate-200 shadow-sm">
                        <div class="flex justify-between items-center mb-4 border-b border-slate-200 pb-2">
                            <h3 class="text-lg font-semibold text-slate-800">Structured Clinical Appraisal</h3>
                            <span class="text-xs text-slate-400 italic">Click any coordinate pill to inspect source text</span>
                        </div>
                        <div id="outputMarkdown" class="prose max-w-none text-slate-800 bg-slate-50 p-6 rounded-lg border border-slate-200 text-sm leading-relaxed"></div>
                    </div>

                    <!-- Right: Interactive Source Inspector (5 Columns, Sticky) -->
                    <div class="col-span-5 bg-white p-6 rounded-lg border border-slate-200 shadow-sm sticky top-6 space-y-4">
                        <div class="border-b border-slate-200 pb-3 flex justify-between items-center">
                            <div>
                                <h3 class="text-base font-semibold text-slate-800">Source Evidence Inspector</h3>
                                <p id="inspectSubtitle" class="text-xs text-slate-500 mt-0.5">Select any coordinate pill on the left</p>
                            </div>
                            <span id="pageBadge" class="hidden px-2.5 py-1 text-xs font-semibold rounded bg-sky-100 text-sky-800 border border-sky-200">Page -</span>
                        </div>

                        <!-- Snippet Text Box -->
                        <div id="snippetBox" class="hidden p-3.5 rounded-md bg-amber-50 border border-amber-200 text-xs text-amber-900 leading-normal">
                            <span class="font-bold uppercase tracking-wider text-[10px] text-amber-700 block mb-1">Extracted Source Text:</span>
                            <p id="snippetText" class="font-serif italic"></p>
                        </div>

                        <!-- Page Image Viewer with Highlight -->
                        <div id="pageViewer" class="relative bg-slate-100 rounded border border-slate-300 min-h-[500px] max-h-[700px] overflow-y-auto flex items-center justify-center p-2">
                            <div id="viewerPlaceholder" class="text-center p-8 text-slate-400">
                                <svg class="w-12 h-12 mx-auto mb-2 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                                <p class="text-sm">Click any inline coordinate pill to load the manuscript page with the exact text highlighted</p>
                            </div>
                            <img id="highlightedImage" class="hidden max-w-full h-auto rounded shadow" alt="Source Page Preview"/>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let currentFilename = '';
            let anchorIndex = {};

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
                const img = document.getElementById('highlightedImage');
                const placeholder = document.getElementById('viewerPlaceholder');

                subtitle.innerText = anchor;

                if (meta) {
                    pageBadge.innerText = 'Page ' + meta.page;
                    pageBadge.classList.remove('hidden');
                    snippetText.innerText = meta.text;
                    snippetBox.classList.remove('hidden');
                } else {
                    pageBadge.classList.add('hidden');
                    snippetBox.classList.add('hidden');
                }

                // Load page image with highlight
                placeholder.classList.remove('hidden');
                img.classList.add('hidden');

                const imgUrl = `/view-anchor-image?filename=${encodeURIComponent(currentFilename)}&anchor=${encodeURIComponent(anchor)}`;
                img.onload = function() {
                    placeholder.classList.add('hidden');
                    img.classList.remove('hidden');
                };
                img.onerror = function() {
                    placeholder.innerHTML = '<p class="text-sm text-red-500">Failed to render page image for this coordinate.</p>';
                    placeholder.classList.remove('hidden');
                    img.classList.add('hidden');
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
