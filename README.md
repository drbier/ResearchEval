# Research Evaluation App - Clinical Research Appraiser

Deterministic Clinical Research Appraiser that ingests primary medical literature, clinical trial protocols, systematic reviews, and real-world evidence (RWE), generating assertive, structured appraisals grounded with exact inline coordinate anchors (e.g., `[Doc_Header]`, `[Methods, Para 4]`, `[Results, Table 2]`).

---

## 1. Verified Model Tier (Google Gemini)
* **Primary High-Speed Inference**: `gemini-3.8-flash` (GA tier, 1M token input context, native PDF parsing, structured output)
* **Deep Methodological Escalation**: `gemini-3.1-pro-preview` (Frontier reasoning for complex multi-arm designs, Bayesian network meta-analyses)

---

## 2. Directory Architecture & Knowledge Bases

```
D:\SSD-Drive\Antigravity\ResearchEval\
├── data\
│   ├── triagedb.json       # Master Triage Matrix (FW_A through FW_H)
│   ├── rulesdb.json        # Methodological Rules (RoB 2, CONSORT Harms, STROBE, REMARK, etc.)
│   ├── lexicondb.json      # Plain-language statistical definitions & caveats (HR, NNT, iRECIST, etc.)
│   └── schemadb.json       # Framework Output Schemas & mandatory headers
├── src\
│   ├── ingestion\
│   │   └── indexer.py      # Layout-aware PDF chunker & coordinate anchor mapper
│   ├── triage\
│   │   └── classifier.py   # Deterministic triage classifier & sub-feature tagger
│   ├── appraisal\
│   │   ├── generator.py    # Scoped prompt assembler & Gemini synthesis invoker
│   │   └── sanitizer.py    # Regex disclaimer stripper & coordinate verification filter
│   └── api\
│       └── server.py       # FastAPI application & interactive web UI
├── tests\
│   └── test_pipeline.py    # End-to-end regression unit test suite
└── Reference_papers\       # Primary evidence base (CONSORT, RoB 2, PRISMA, STROBE, etc.)
```

---

## 3. Quickstart & Running the App

### Requirements
* Python 3.11+
* Packages installed: `pymupdf`, `pydantic`, `fastapi`, `uvicorn`, `google-genai`, `python-docx`

### Launch the Web UI & API
Open a terminal (PowerShell or Bash) and execute:
```powershell
Set-Location "D:\SSD-Drive\Antigravity\ResearchEval"
$env:PYTHONPATH="D:\SSD-Drive\Antigravity\ResearchEval"
python src/api/server.py
```
Then navigate to:
👉 **`http://localhost:8000`**

### Running the Test Suite
```powershell
Set-Location "D:\SSD-Drive\Antigravity\ResearchEval"
$env:PYTHONPATH="D:\SSD-Drive\Antigravity\ResearchEval"
python -m unittest tests/test_pipeline.py
```

