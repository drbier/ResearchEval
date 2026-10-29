import os
import shutil
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

from src.ingestion.indexer import parse_and_index_pdf
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
        
        # Instantiate engine with runtime key if supplied
        eval_engine = SynthesisEngine(DATA_DIR, api_key=api_key) if api_key else engine
        result = eval_engine.generate_appraisal(indexed, model_override=model_override)
        
        # Attach indexed anchors summary for UI inspection
        result["total_anchors_indexed"] = len(indexed.all_anchors)
        result["sections_detected"] = list(indexed.sections.keys())
        result["document_header"] = indexed.doc_header
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temporary upload if needed, or leave for caching
        pass

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
    </head>
    <body class="bg-slate-50 text-slate-800 min-h-screen p-8">
        <div class="max-w-5xl mx-auto space-y-6">
            <header class="border-b border-slate-200 pb-4 flex justify-between items-center bg-white p-6 rounded-lg shadow-sm">
                <div>
                    <h1 class="text-3xl font-bold text-sky-700">Research Evaluation App</h1>
                    <p class="text-slate-500 text-sm mt-1">Deterministic Clinical Research Appraiser with Exact Coordinate Grounding</p>
                </div>
                <div class="text-right text-xs text-slate-500">
                    <span class="inline-block px-3 py-1 bg-sky-50 text-sky-700 rounded-full border border-sky-200 font-medium">Model: gemini-3.8-flash</span>
                </div>
            </header>

            <div class="bg-white p-6 rounded-lg border border-slate-200 shadow-sm space-y-4">
                <h2 class="text-xl font-semibold text-slate-800">1. Upload Clinical Research Paper (PDF)</h2>
                <div class="flex gap-4 items-center">
                    <input type="file" id="pdfFile" accept=".pdf" class="block w-full text-sm text-slate-600 file:mr-4 file:py-2.5 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-700 cursor-pointer bg-slate-50 p-2 rounded-md border border-slate-200"/>
                    <button onclick="startAppraisal()" id="runBtn" class="bg-sky-600 hover:bg-sky-700 text-white font-semibold px-6 py-2.5 rounded-md transition shadow">Evaluate</button>
                </div>
            </div>

            <div id="statusBox" class="hidden p-4 rounded-lg bg-white border border-slate-200 shadow-sm space-y-2">
                <div class="flex items-center gap-2">
                    <div id="spinner" class="animate-spin rounded-full h-4 w-4 border-2 border-sky-600 border-t-transparent"></div>
                    <span id="statusIcon" class="hidden text-emerald-600 font-bold">✓</span>
                    <span id="statusText" class="text-sm font-medium text-slate-700">Processing...</span>
                </div>
            </div>

            <div id="resultBox" class="hidden space-y-6">
                <div class="grid grid-cols-3 gap-4">
                    <div class="bg-white p-5 rounded-lg border border-slate-200 shadow-sm">
                        <span class="text-xs uppercase tracking-wider font-semibold text-slate-400">Framework ID</span>
                        <p id="fwId" class="text-lg font-bold text-sky-700 mt-1">-</p>
                    </div>
                    <div class="bg-white p-5 rounded-lg border border-slate-200 shadow-sm">
                        <span class="text-xs uppercase tracking-wider font-semibold text-slate-400">Triggered Rules</span>
                        <p id="rulesCount" class="text-lg font-bold text-sky-700 mt-1">0</p>
                    </div>
                    <div class="bg-white p-5 rounded-lg border border-slate-200 shadow-sm">
                        <span class="text-xs uppercase tracking-wider font-semibold text-slate-400">Coordinate Anchors Indexed</span>
                        <p id="anchorCount" class="text-lg font-bold text-emerald-600 mt-1">0</p>
                    </div>
                </div>

                <div class="bg-white p-6 rounded-lg border border-slate-200 shadow-sm">
                    <h3 class="text-lg font-semibold text-slate-800 mb-4 border-b border-slate-200 pb-2">Structured Clinical Appraisal</h3>
                    <div id="outputMarkdown" class="prose max-w-none text-slate-800 bg-slate-50 p-6 rounded-lg border border-slate-200 text-sm leading-relaxed"></div>
                </div>
            </div>
        </div>

        <script>
            async function startAppraisal() {
                const fileInput = document.getElementById('pdfFile');
                if (!fileInput.files[0]) {
                    alert('Please select a PDF file to appraise.');
                    return;
                }

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

                    document.getElementById('fwId').innerText = data.triage.primary_framework_id + ': ' + data.triage.framework_name;
                    document.getElementById('rulesCount').innerText = data.triage.applicable_rules.length + ' rules';
                    document.getElementById('anchorCount').innerText = data.total_anchors_indexed + ' anchors';

                    let content = data.final_markdown || (data.status === 'ready_for_inference_key_needed' ? 
                        ('### System Ready for Inference\\n\\n' +
                         'Triage Result: ' + data.triage.primary_framework_id + ' (' + data.triage.framework_name + ')\\n' +
                         'Triggered Rules (' + data.active_rules_count + '):\\n- ' + data.triage.applicable_rules.join('\\n- ') + '\\n\\n' +
                         '**Note**: A Gemini API key is required on the server to execute the final LLM text generation.') : data.raw_output);

                    // Render formatted markdown with highlighted coordinate anchors
                    if (window.marked) {
                        let html = marked.parse(content);
                        // Highlight coordinate anchors in badge style
                        html = html.replace(/(\[(?:Doc_Header|Supp_[^,\]]+|[A-Za-z\s]+),\s*(?:Para\s+\d+|Table\s+\d+|Fig\s+\d+)\]|\[Doc_Header\])/g, '<span class="inline-block px-1.5 py-0.5 mx-0.5 text-xs font-mono font-medium bg-sky-100 text-sky-800 border border-sky-300 rounded shadow-xs">$1</span>');
                        document.getElementById('outputMarkdown').innerHTML = html;
                    } else {
                        document.getElementById('outputMarkdown').innerText = content;
                    }

                    resultBox.classList.remove('hidden');
                    
                    // Stop and hide the spinner, show green checkmark
                    spinner.classList.add('hidden');
                    statusIcon.classList.remove('hidden');
                    statusText.innerText = 'Appraisal complete.';
                } catch (err) {
                    spinner.classList.add('hidden');
                    alert('Error: ' + err.message);
                    statusText.innerText = 'Failed: ' + err.message;
                } finally {
                    runBtn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

