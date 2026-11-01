"""
audit_wonk_corpus.py - High-Throughput Local Structural Audit of WonkProject Papers.

Analyzes PDF layouts, publisher geometries, abstract styles, and section structures
across the local PDF corpus. Uses 0 LLM tokens (100% local PyMuPDF processing).
"""

import os
import sys
import re
import json
import time
from typing import Dict, List, Any, Optional, Tuple
from collections import Counter, defaultdict
import pymupdf

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

DEFAULT_PAPERS_DIR = r"J:\My Drive\WonkProject\Research Reviews\Papers"

STRUCTURED_ABSTRACT_KEYWORDS = [
    'BACKGROUND', 'OBJECTIVE', 'OBJECTIVES', 'AIM', 'AIMS', 'CONTEXT',
    'METHODS', 'PATIENTS AND METHODS', 'MATERIALS AND METHODS', 'STUDY DESIGN',
    'DESIGN', 'SETTING', 'PARTICIPANTS', 'INTERVENTIONS', 'OUTCOMES', 'MEASURES',
    'RESULTS', 'FINDINGS', 'INTERPRETATION', 'INTERPRETATIONS',
    'CONCLUSIONS', 'CONCLUSION', 'SIGNIFICANCE', 'TRIAL REGISTRATION'
]

COMMON_SECTION_PATTERNS = {
    'Introduction': re.compile(r'^(?:(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s*)?(?:INTRODUCTION|BACKGROUND)\b', re.IGNORECASE),
    'Methods': re.compile(r'^(?:(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s*)?(?:MATERIALS?\s+AND\s+METHODS?|PATIENTS?\s+AND\s+METHODS?|METHODS?|METHODOLOGY|STUDY\s+DESIGN|EXPERIMENTAL\s+PROCEDURES?)\b', re.IGNORECASE),
    'Results': re.compile(r'^(?:(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s*)?(?:RESULTS?|FINDINGS?|RESULTS?\s+AND\s+DISCUSSION)\b', re.IGNORECASE),
    'Discussion': re.compile(r'^(?:(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s*)?(?:DISCUSSION|LIMITATIONS?)\b', re.IGNORECASE),
    'Conclusions': re.compile(r'^(?:(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s*)?(?:CONCLUSIONS?|CONCLUSIONS?\s+AND\s+RELEVANCE)\b', re.IGNORECASE),
    'References': re.compile(r'^(?:(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s*)?(?:REFERENCES?|LITERATURE\s+CITED|BIBLIOGRAPHY)\b', re.IGNORECASE)
}


def audit_single_pdf(file_path: str) -> Dict[str, Any]:
    filename = os.path.basename(file_path)
    result = {
        "filename": filename,
        "path": file_path,
        "is_hidden_file": filename.startswith('.'),
        "page_count": 0,
        "is_scanned": False,
        "has_text": True,
        "publisher_family": "Unknown",
        "layout_style": "Unknown",
        "has_abstract": False,
        "abstract_type": "None",  # Unstructured, Structured-Inline, Structured-MultiBlock, None
        "abstract_page": 1,
        "abstract_subheadings_detected": [],
        "sections_detected": [],
        "missing_standard_sections": [],
        "has_numbered_headers": False,
        "table_count": 0,
        "fig_count": 0,
        "risk_flags": [],
        "page1_geometry": {}
    }

    try:
        doc = pymupdf.open(file_path)
    except Exception as e:
        result["has_text"] = False
        result["risk_flags"].append(f"PDF open error: {str(e)[:100]}")
        return result

    result["page_count"] = len(doc)
    if len(doc) == 0:
        result["has_text"] = False
        result["risk_flags"].append("Empty PDF (0 pages)")
        return result

    # Check for scanned / outlined vector PDF (fonts converted to paths)
    first_pages_text = "".join(doc[i].get_text() for i in range(min(2, len(doc)))).strip()
    is_vector_or_scanned = len(first_pages_text) < 150

    p0 = doc[0]
    p0_w = float(p0.rect.width)
    p0_h = float(p0.rect.height)
    
    tessdata_path = "data/tessdata"
    has_tess = os.path.exists(os.path.join(tessdata_path, "eng.traineddata"))

    if is_vector_or_scanned:
        result["is_scanned"] = True
        result["risk_flags"].append("Outlined/Scanned PDF (requires Tesseract OCR)")
        if has_tess:
            try:
                tp0 = p0.get_textpage_ocr(tessdata=tessdata_path, dpi=150, full=True)
                p0_text = tp0.extractText()
                p0_blocks = tp0.extractBLOCKS()
            except Exception:
                p0_text = ""
                p0_blocks = []
        else:
            p0_text = ""
            p0_blocks = []
    else:
        p0_text = p0.get_text()
        p0_blocks = p0.get_text("blocks")
    p0_lower = p0_text.lower()

    # Detect publisher family
    if "mdpi" in p0_lower or "nutrients" in p0_lower or "cancers" in p0_lower or "pharmaceuticals" in p0_lower:
        result["publisher_family"] = "MDPI"
    elif "bmj" in p0_lower:
        result["publisher_family"] = "BMJ"
    elif "lancet" in p0_lower:
        result["publisher_family"] = "The Lancet"
    elif "new england journal" in p0_lower or "nejm" in p0_lower:
        result["publisher_family"] = "NEJM"
    elif "jama" in p0_lower or "jamanetwork" in p0_lower:
        result["publisher_family"] = "JAMA"
    elif "cell metabolism" in p0_lower or "cell press" in p0_lower:
        result["publisher_family"] = "Cell Press"
    elif "elsevier" in p0_lower or "sciencedirect" in p0_lower:
        result["publisher_family"] = "Elsevier"
    elif "springer" in p0_lower or "nature" in p0_lower or "biomed central" in p0_lower or "bmc" in p0_lower:
        result["publisher_family"] = "Springer/Nature/BMC"
    elif "frontiers in" in p0_lower or "frontiersin.org" in p0_lower:
        result["publisher_family"] = "Frontiers"
    elif "wiley" in p0_lower:
        result["publisher_family"] = "Wiley"
    elif "plos" in p0_lower:
        result["publisher_family"] = "PLOS"
    elif "circulation" in p0_lower or "ahajournals" in p0_lower:
        result["publisher_family"] = "AHA"

    # Analyze column structure on page 2 or 1
    sample_page = doc[1] if len(doc) > 1 else doc[0]
    sample_blocks = sample_page.get_text("blocks")
    prose_blocks = [b for b in sample_blocks if len(b[4].strip()) > 100]
    
    if prose_blocks:
        x0s = [b[0] for b in prose_blocks]
        widths = [b[2] - b[0] for b in prose_blocks]
        med_width = sorted(widths)[len(widths) // 2]
        min_x0 = min(x0s)

        if med_width < sample_page.rect.width * 0.45:
            result["layout_style"] = "Two-Column"
        elif min_x0 >= sample_page.rect.width * 0.20:
            result["layout_style"] = "Asymmetric Single-Column (Indented Left Margin)"
        else:
            result["layout_style"] = "Standard Single-Column"

    # Check Abstract Style
    found_abstract = False
    for p_idx in range(min(2, len(doc))):
        if p_idx == 0:
            p_text = p0_text
        elif is_vector_or_scanned and has_tess:
            try:
                p_text = doc[p_idx].get_textpage_ocr(tessdata=tessdata_path, dpi=150, full=True).extractText()
            except Exception:
                p_text = doc[p_idx].get_text()
        else:
            p_text = doc[p_idx].get_text()

        m_abs = re.search(r'\b(?:ABSTRACT|Summary)\b', p_text, re.IGNORECASE)
        if m_abs:
            found_abstract = True
            result["has_abstract"] = True
            result["abstract_page"] = p_idx + 1
            
            # Extract abstract text snippet
            abs_start = m_abs.end()
            abs_window = p_text[abs_start:abs_start + 2500]
            
            # Check for structured subheadings
            detected_subheads = []
            for kw in STRUCTURED_ABSTRACT_KEYWORDS:
                if re.search(r'(?:^|\n|\b)' + re.escape(kw) + r'\s*[:\.\-]', abs_window, re.IGNORECASE):
                    detected_subheads.append(kw)
                    
            if detected_subheads:
                result["abstract_subheadings_detected"] = detected_subheads
                result["abstract_type"] = "Structured"
                if any(k in ('METHODS', 'MATERIALS AND METHODS', 'RESULTS', 'FINDINGS') for k in detected_subheads):
                    result["risk_flags"].append(f"Abstract contains '{', '.join(detected_subheads[:3])}' subheadings (Section Leaking Risk)")
            else:
                result["abstract_type"] = "Unstructured"
            break

    if not found_abstract:
        result["abstract_type"] = "None/Unlabeled"
        result["risk_flags"].append("No explicit Abstract header found (Clinical letter, Editorial, or immediate body)")

    # Scan Sections across entire paper
    sections_found = set()
    has_numbered = False
    total_tables = 0
    total_figs = 0

    for p_idx, page in enumerate(doc):
        blocks = page.get_text("blocks")
        for b in blocks:
            b_text = b[4].strip()
            lines = [l.strip() for l in b_text.split('\n') if l.strip()]
            if not lines:
                continue

            first_line = lines[0]
            
            # Check numbered headers like "1. Introduction", "2. Methods"
            if re.match(r'^(?:[0-9]+|[IVXLCDM]+)[\.\s\-:]+\s+[A-Z]', first_line):
                has_numbered = True

            # Match sections
            for sec_name, pattern in COMMON_SECTION_PATTERNS.items():
                if pattern.match(first_line):
                    sections_found.add(sec_name)

            # Detect Tables & Figures
            if re.search(r'^(?:Table|Tab\.)\s*[0-9A-Za-z]+', first_line, re.IGNORECASE):
                total_tables += 1
            elif re.search(r'^(?:Figure|Fig\.)\s*[0-9A-Za-z]+', first_line, re.IGNORECASE):
                total_figs += 1

    result["has_numbered_headers"] = has_numbered
    result["sections_detected"] = sorted(list(sections_found))
    result["table_count"] = total_tables
    result["fig_count"] = total_figs

    # Check standard section coverage
    standard_expected = ['Methods', 'Results']
    missing = [s for s in standard_expected if s not in sections_found]
    if missing:
        result["missing_standard_sections"] = missing
        result["risk_flags"].append(f"Missing core section header: {', '.join(missing)}")

    if total_tables >= 8:
        result["risk_flags"].append(f"High table density ({total_tables} tables) - Table block fragmentation risk")

    return result


def audit_corpus(papers_dir: str = DEFAULT_PAPERS_DIR, max_papers: Optional[int] = None) -> Dict[str, Any]:
    print("=" * 80)
    print(f"WONKPROJECT PAPERS CORPUS AUDIT (0 LLM Tokens)")
    print(f"Target Directory: {papers_dir}")
    print("=" * 80)

    if not os.path.exists(papers_dir):
        print(f"[ERROR] Directory does not exist: {papers_dir}")
        return {}

    all_files = []
    for root, _, files in os.walk(papers_dir):
        for f in files:
            if f.lower().endswith(".pdf"):
                all_files.append(os.path.join(root, f))

    all_files.sort()
    total_found = len(all_files)
    print(f"Found {total_found} total PDF papers in repository.")

    if max_papers and max_papers < total_found:
        print(f"Scanning sample of {max_papers} papers as requested...")
        files_to_scan = all_files[:max_papers]
    else:
        print(f"Auditing ALL {total_found} papers locally...")
        files_to_scan = all_files

    start_time = time.time()
    results = []
    
    for idx, fpath in enumerate(files_to_scan):
        fname = os.path.basename(fpath)
        safe_fname = fname.encode('ascii', errors='replace').decode('ascii')[:45]
        sys.stdout.write(f"\r[{idx+1}/{len(files_to_scan)}] Auditing: {safe_fname:<45}")
        sys.stdout.flush()
        
        res = audit_single_pdf(fpath)
        results.append(res)

    duration = time.time() - start_time
    print(f"\n\nAudit completed in {duration:.2f} seconds ({duration/len(files_to_scan)*1000:.1f}ms per paper).")

    # Aggregate Statistics
    publishers = Counter(r["publisher_family"] for r in results)
    layouts = Counter(r["layout_style"] for r in results)
    abstract_types = Counter(r["abstract_type"] for r in results)
    scanned_count = sum(1 for r in results if r["is_scanned"])
    hidden_count = sum(1 for r in results if r["is_hidden_file"])
    numbered_header_count = sum(1 for r in results if r["has_numbered_headers"])
    
    # Collect all unique risk flags
    risk_summary = Counter()
    papers_with_risks = []
    for r in results:
        if r["risk_flags"]:
            papers_with_risks.append({
                "filename": r["filename"],
                "publisher": r["publisher_family"],
                "risks": r["risk_flags"]
            })
            for rf in r["risk_flags"]:
                # Normalize risk message key
                norm_rf = re.sub(r"'.*?'|\d+", "X", rf)
                risk_summary[norm_rf] += 1

    summary = {
        "total_audited": len(results),
        "duration_seconds": round(duration, 2),
        "scanned_pdf_count": scanned_count,
        "hidden_file_count": hidden_count,
        "numbered_headers_count": numbered_header_count,
        "publisher_distribution": dict(publishers.most_common()),
        "layout_distribution": dict(layouts.most_common()),
        "abstract_type_distribution": dict(abstract_types.most_common()),
        "risk_flag_frequencies": dict(risk_summary.most_common()),
        "anomaly_papers": papers_with_risks,
        "detailed_results": results
    }

    # Print Dashboard Report
    print("\n" + "=" * 80)
    print("                     CORPUS AUDIT SUMMARY DASHBOARD                     ")
    print("=" * 80)
    print(f"Total Papers Audited : {len(results)}")
    print(f"Scanned / Bitmap PDFs: {scanned_count}")
    print(f"Hidden (Dot) Files   : {hidden_count}")
    print(f"Numbered Sections    : {numbered_header_count} ({(numbered_header_count/len(results))*100:.1f}%)")
    print(f"Unnumbered Sections  : {len(results)-numbered_header_count} ({((len(results)-numbered_header_count)/len(results))*100:.1f}%)")

    print("\n--- PUBLISHER FAMILIES ---")
    for pub, cnt in publishers.most_common():
        print(f"  {pub:<25}: {cnt:>3} papers ({cnt/len(results)*100:.1f}%)")

    print("\n--- COLUMN & LAYOUT FAMILIES ---")
    for lay, cnt in layouts.most_common():
        print(f"  {lay:<42}: {cnt:>3} papers ({cnt/len(results)*100:.1f}%)")

    print("\n--- ABSTRACT STRUCTURES ---")
    for atype, cnt in abstract_types.most_common():
        print(f"  {atype:<25}: {cnt:>3} papers ({cnt/len(results)*100:.1f}%)")

    print("\n--- DETECTED MODEL / INDEXER VARIATION RISKS ---")
    for rf, cnt in risk_summary.most_common():
        print(f"  [{cnt:>3} papers] {rf}")

    # Save to JSON
    os.makedirs("data", exist_ok=True)
    report_path = "data/wonk_corpus_audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Detailed audit report saved to: {report_path}")

    return summary


if __name__ == "__main__":
    max_p = None
    if len(sys.argv) > 1:
        try:
            max_p = int(sys.argv[1])
        except ValueError:
            pass
    audit_corpus(DEFAULT_PAPERS_DIR, max_papers=max_p)
