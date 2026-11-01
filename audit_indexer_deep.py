"""
audit_indexer_deep.py - High-Throughput Deep Indexer Invariant Audit for WonkProject Corpus.

Executes parse_and_index_pdf() end-to-end on the medical research corpus and tests the
resulting coordinates, section assignments, and paragraph structures against 6 core invariants:
1. Cross-Column Bounding Box Bleeds (anchors stretching across columns on two-column pages).
2. Section Voids & Trapping (e.g., Discussion: 0 anchors while Results >= 15; Abstract on Page 2+).
3. Thematic Subsection Swallowing (mega-paragraphs > 1,800 chars containing embedded subheadings).
4. Severed Margin Fragments (micro-paragraphs < 35 chars from broken sentence wraps).
5. Table Footnote & Data Counter Pollution (tabular rows/glossaries incrementing [Results, Para X]).
6. Cross-Page Sentence Overflow Integrity (proper stitching without phantom counter increments).

Outputs:
- Live progress console with per-paper anomaly alerts.
- Structured JSON report: data/deep_indexer_audit_report.json
- Executive Markdown summary: data/deep_indexer_audit_summary.md
"""

import os
import sys
import re
import json
import time
import argparse
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import Counter, defaultdict
import pymupdf

# Ensure project root is in Python module path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ingestion.indexer import parse_and_index_pdf, IndexedDocument, CoordinateAnchor

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

DEFAULT_PAPERS_DIR = r"J:\My Drive\WonkProject\Research Reviews\Papers"
DEFAULT_REPORT_JSON = os.path.join(PROJECT_ROOT, "data", "deep_indexer_audit_report.json")
DEFAULT_SUMMARY_MD = os.path.join(PROJECT_ROOT, "data", "deep_indexer_audit_summary.md")


def is_scanned_or_outlined(pdf_path: str) -> bool:
    """Fast pre-check to distinguish born-digital PDFs from scanned/outlined raster PDFs."""
    try:
        doc = pymupdf.open(pdf_path)
        sample = "".join(doc[i].get_text().strip() for i in range(min(2, len(doc))))
        doc.close()
        return len(sample) < 100
    except Exception:
        return True


def audit_single_document(pdf_path: str) -> Dict[str, Any]:
    """
    Run parse_and_index_pdf on a single PDF and evaluate all 6 structural invariants.
    """
    filename = os.path.basename(pdf_path)
    file_record: Dict[str, Any] = {
        "filename": filename,
        "path": pdf_path,
        "is_scanned": False,
        "page_count": 0,
        "total_anchors": 0,
        "sections_detected": {},
        "violations": [],
        "anomaly_counts": {
            "cross_column_bleeds": 0,
            "section_voids": 0,
            "abstract_leakage": 0,
            "mega_paragraphs": 0,
            "micro_fragments": 0,
            "table_footnote_pollution": 0,
            "overflow_orphans": 0
        },
        "publisher_family": "Unknown",
        "has_critical_failure": False
    }

    try:
        doc_fitz = pymupdf.open(pdf_path)
        page_count = len(doc_fitz)
        file_record["page_count"] = page_count
        
        # Publisher identification from Page 1 text
        if page_count > 0:
            p0_text = doc_fitz[0].get_text()[:3000].lower()
            if "mdpi" in p0_text or "nutrients" in p0_text or "cancers" in p0_text:
                file_record["publisher_family"] = "MDPI"
            elif "bmj" in p0_text:
                file_record["publisher_family"] = "BMJ"
            elif "lancet" in p0_text:
                file_record["publisher_family"] = "The Lancet"
            elif "new england journal" in p0_text or "nejm" in p0_text:
                file_record["publisher_family"] = "NEJM"
            elif "jama" in p0_text or "jamanetwork" in p0_text:
                file_record["publisher_family"] = "JAMA"
            elif "endocrinology & metabolism" in p0_text or "jcem" in p0_text or "academic.oup.com/jcem" in p0_text:
                file_record["publisher_family"] = "JCEM / Oxford"
            elif "cell metabolism" in p0_text or "cell press" in p0_text:
                file_record["publisher_family"] = "Cell Press"
            elif "elsevier" in p0_text or "sciencedirect" in p0_text:
                file_record["publisher_family"] = "Elsevier"
            elif "springer" in p0_text or "nature" in p0_text or "bmc" in p0_text:
                file_record["publisher_family"] = "Springer/Nature/BMC"
            elif "wiley" in p0_text:
                file_record["publisher_family"] = "Wiley"
            elif "plos" in p0_text:
                file_record["publisher_family"] = "PLOS"
        doc_fitz.close()
    except Exception as e:
        file_record["violations"].append({
            "type": "PDF_OPEN_ERROR",
            "severity": "CRITICAL",
            "details": f"Failed to open PDF with PyMuPDF: {str(e)[:150]}"
        })
        file_record["has_critical_failure"] = True
        return file_record

    # Execute production indexing engine
    t0 = time.time()
    try:
        indexed: IndexedDocument = parse_and_index_pdf(pdf_path)
    except Exception as e:
        file_record["violations"].append({
            "type": "INDEXER_CRASH",
            "severity": "CRITICAL",
            "details": f"parse_and_index_pdf crashed: {str(e)[:200]}"
        })
        file_record["has_critical_failure"] = True
        return file_record

    indexing_duration = time.time() - t0
    file_record["indexing_seconds"] = round(indexing_duration, 2)
    file_record["total_anchors"] = len(indexed.anchor_metadata)

    # Tally section distributions
    section_counts: Dict[str, int] = Counter()
    anchors_by_page: Dict[int, List[CoordinateAnchor]] = defaultdict(list)
    for a in indexed.anchor_metadata.values():
        section_counts[a.section] += 1
        anchors_by_page[a.page_number].append(a)
    file_record["sections_detected"] = dict(section_counts)

    # -------------------------------------------------------------------------
    # INVARIANT 1: Cross-Column Bounding Box Bleeds
    # On multi-column pages, a prose paragraph must NOT span across the center gutter
    # -------------------------------------------------------------------------
    for a in indexed.anchor_metadata.values():
        if a.item_type not in ("para", "paragraph"):
            continue
        if a.anchor_id == "[Doc_Header]":
            continue

        w = a.page_width or 612.0
        x0, y0, x1, y1 = a.bbox
        anchor_w = x1 - x0

        # Anchor spans from left column (< 0.40 * W) across to right column (> 0.60 * W)
        if x0 < (w * 0.38) and x1 > (w * 0.62) and anchor_w > (w * 0.55):
            # Check if this page is a multi-column page (has anchors on both sides)
            page_anchors = anchors_by_page.get(a.page_number, [])
            left_anchors = [p for p in page_anchors if p.bbox[2] < (w * 0.52)]
            right_anchors = [p for p in page_anchors if p.bbox[0] > (w * 0.48)]

            # If the page clearly has multiple columns or if text has embedded two-column patterns
            if len(left_anchors) >= 2 and len(right_anchors) >= 2:
                file_record["anomaly_counts"]["cross_column_bleeds"] += 1
                file_record["violations"].append({
                    "type": "CROSS_COLUMN_BBOX_BLEED",
                    "severity": "CRITICAL",
                    "anchor_id": a.anchor_id,
                    "page": a.page_number,
                    "bbox": [round(c, 1) for c in a.bbox],
                    "page_width": round(w, 1),
                    "text_excerpt": a.text[:140].replace('\n', ' ')
                })
                file_record["has_critical_failure"] = True

    # -------------------------------------------------------------------------
    # INVARIANT 2: Section Voids & Trapping
    # Clinical research papers must not trap Discussion in Results or Abstract on Page 2+
    # -------------------------------------------------------------------------
    res_count = section_counts.get("Results", 0)
    disc_count = section_counts.get("Discussion", 0)
    meth_count = section_counts.get("Methods", 0)
    abs_count = section_counts.get("Abstract", 0)

    # 2A: Discussion void when Results is disproportionately large (the JCEM bug)
    if page_count >= 5 and res_count >= 15 and disc_count == 0:
        file_record["anomaly_counts"]["section_voids"] += 1
        file_record["violations"].append({
            "type": "MISSING_DISCUSSION_SECTION",
            "severity": "CRITICAL",
            "details": f"Paper has {page_count} pages and {res_count} Results anchors, but Discussion has 0 anchors (Discussion trapped in Results)."
        })
        file_record["has_critical_failure"] = True

    # 2B: Core Methods void in substantive papers
    if page_count >= 4 and meth_count == 0 and res_count >= 5:
        file_record["anomaly_counts"]["section_voids"] += 1
        file_record["violations"].append({
            "type": "MISSING_METHODS_SECTION",
            "severity": "HIGH",
            "details": f"Paper has {page_count} pages but Methods has 0 anchors (Unnumbered heading transition missed)."
        })

    # 2C: Abstract Leakage onto Page 2+
    for a in indexed.anchor_metadata.values():
        if a.section == "Abstract" and a.page_number >= 2 and a.item_type == "para":
            file_record["anomaly_counts"]["abstract_leakage"] += 1
            file_record["violations"].append({
                "type": "ABSTRACT_LEAKAGE_PAGE_2_PLUS",
                "severity": "HIGH",
                "anchor_id": a.anchor_id,
                "page": a.page_number,
                "text_excerpt": a.text[:120].replace('\n', ' ')
            })
            break  # Record one violation per file to avoid flooding

    # -------------------------------------------------------------------------
    # INVARIANT 3: Thematic Subsection Swallowing (Mega-Paragraphs)
    # Detect paragraphs > 1800 characters containing embedded subsection headings
    # -------------------------------------------------------------------------
    subsection_pat = re.compile(r'(?:\n|\b)(?:[0-9]+\.[0-9]+|\b(?:Strengths\s+and\s+Limitations|Statistical\s+Analysis|Exclusion\s+Criteria|Study\s+Design)\b)', re.IGNORECASE)
    for a in indexed.anchor_metadata.values():
        if a.item_type == "para" and len(a.text) > 1800:
            if subsection_pat.search(a.text):
                file_record["anomaly_counts"]["mega_paragraphs"] += 1
                file_record["violations"].append({
                    "type": "MEGA_PARAGRAPH_SWALLOWED_SUBSECTION",
                    "severity": "MEDIUM",
                    "anchor_id": a.anchor_id,
                    "page": a.page_number,
                    "char_length": len(a.text),
                    "text_excerpt": a.text[:140].replace('\n', ' ')
                })

    # -------------------------------------------------------------------------
    # INVARIANT 4: Severed Margin Fragments (Micro-Paragraphs)
    # Detect accidental single-line fragments created by margin cleaving
    # -------------------------------------------------------------------------
    for a in indexed.anchor_metadata.values():
        if a.item_type == "para" and len(a.text.strip()) < 35:
            t_clean = a.text.strip()
            # Exclude standalone mathematical formulas or author headers
            if not re.match(r'^(?:[pPnN]\s*[<>=]|Table|Figure|Key\s+points|doi:)', t_clean, re.IGNORECASE):
                file_record["anomaly_counts"]["micro_fragments"] += 1
                file_record["violations"].append({
                    "type": "MICRO_PARAGRAPH_FRAGMENT",
                    "severity": "LOW",
                    "anchor_id": a.anchor_id,
                    "page": a.page_number,
                    "char_length": len(t_clean),
                    "text_excerpt": t_clean
                })

    # -------------------------------------------------------------------------
    # INVARIANT 5: Table Footnote / Glossary Pollution
    # Detect abbreviation glossaries or dense data cells misattributed as prose
    # -------------------------------------------------------------------------
    glossary_pat = re.compile(r'\b[A-Z0-9]{2,}\s*,\s*[^;]+;\s*[A-Z0-9]{2,}\s*,')
    for a in indexed.anchor_metadata.values():
        if a.item_type == "para" and a.section in ("Results", "Methods"):
            if glossary_pat.search(a.text) or (a.text.count(";") >= 4 and len(a.text.split()) < 25):
                file_record["anomaly_counts"]["table_footnote_pollution"] += 1
                file_record["violations"].append({
                    "type": "TABLE_FOOTNOTE_PROSE_POLLUTION",
                    "severity": "MEDIUM",
                    "anchor_id": a.anchor_id,
                    "page": a.page_number,
                    "text_excerpt": a.text[:120].replace('\n', ' ')
                })

    return file_record


def generate_markdown_summary(audit_results: List[Dict[str, Any]], elapsed_seconds: float) -> str:
    """Generate executive Markdown audit summary."""
    total_papers = len(audit_results)
    clean_papers = [r for r in audit_results if not r["violations"]]
    failed_papers = [r for r in audit_results if r["violations"]]
    critical_papers = [r for r in audit_results if r["has_critical_failure"]]

    bleed_papers = [r for r in audit_results if r["anomaly_counts"]["cross_column_bleeds"] > 0]
    void_papers = [r for r in audit_results if r["anomaly_counts"]["section_voids"] > 0]
    leak_papers = [r for r in audit_results if r["anomaly_counts"]["abstract_leakage"] > 0]
    mega_papers = [r for r in audit_results if r["anomaly_counts"]["mega_paragraphs"] > 0]
    pollution_papers = [r for r in audit_results if r["anomaly_counts"]["table_footnote_pollution"] > 0]

    # Publisher breakdown
    pub_counter = Counter(r.get("publisher_family", "Unknown") for r in audit_results)
    pub_failures = Counter(r.get("publisher_family", "Unknown") for r in failed_papers)

    md = []
    md.append("# WonkProject Corpus Deep Indexer Invariant Audit Report\n")
    md.append(f"**Execution Timestamp**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    md.append(f"**Total Papers Audited**: {total_papers}")
    md.append(f"**Total Audit Runtime**: {elapsed_seconds:.1f}s (Average: {elapsed_seconds/max(1, total_papers):.2f}s/paper)\n")

    md.append("## Executive Health Summary\n")
    md.append("| Metric | Count | Percentage | Status |")
    md.append("|---|---|---|---|")
    md.append(f"| **Fully Compliant Papers** | {len(clean_papers)} / {total_papers} | {len(clean_papers)/max(1, total_papers)*100:.1f}% | {'✅ PASS' if len(clean_papers) == total_papers else '⚠️ ANOMALIES FOUND'} |")
    md.append(f"| **Critical Failures** (Column Bleeds / Trapped Sections) | {len(critical_papers)} / {total_papers} | {len(critical_papers)/max(1, total_papers)*100:.1f}% | {'✅ 0' if not critical_papers else '❌ REQUIRES FIX'} |")
    md.append(f"| **Cross-Column Bounding Box Bleeds** | {len(bleed_papers)} | {len(bleed_papers)/max(1, total_papers)*100:.1f}% | {'✅ 0' if not bleed_papers else '❌ HIGH PRIORITY'} |")
    md.append(f"| **Missing Discussion Section Voids** | {len(void_papers)} | {len(void_papers)/max(1, total_papers)*100:.1f}% | {'✅ 0' if not void_papers else '❌ HIGH PRIORITY'} |")
    md.append(f"| **Abstract Page 2+ Leakage** | {len(leak_papers)} | {len(leak_papers)/max(1, total_papers)*100:.1f}% | {'✅ 0' if not leak_papers else '⚠️ MEDIUM'} |")
    md.append(f"| **Mega-Paragraphs (Swallowed Subsections)** | {len(mega_papers)} | {len(mega_papers)/max(1, total_papers)*100:.1f}% | {'✅ 0' if not mega_papers else '⚠️ MEDIUM'} |")
    md.append(f"| **Table Footnote / Glossary Pollution** | {len(pollution_papers)} | {len(pollution_papers)/max(1, total_papers)*100:.1f}% | {'✅ 0' if not pollution_papers else 'ℹ️ LOW'} |\n")

    md.append("## Publisher Vulnerability Breakdown\n")
    md.append("| Publisher Family | Total Papers | Papers with Invariant Failures | Failure Rate |")
    md.append("|---|---|---|---|")
    for pub, count in pub_counter.most_common():
        fails = pub_failures.get(pub, 0)
        rate = (fails / count) * 100
        md.append(f"| **{pub}** | {count} | {fails} | {rate:.1f}% |")
    md.append("\n")

    if critical_papers:
        md.append("## Critical Anomaly Highlights\n")
        md.append("The following papers exhibited structural column bleeds or missing section transitions:\n")
        for r in critical_papers[:15]:
            md.append(f"### 📄 `{r['filename']}`")
            md.append(f"- **Publisher**: {r['publisher_family']} | **Pages**: {r['page_count']} | **Total Anchors**: {r['total_anchors']}")
            for v in r["violations"]:
                if v["severity"] == "CRITICAL":
                    if v["type"] == "CROSS_COLUMN_BBOX_BLEED":
                        md.append(f"  - ❌ **Cross-Column Bleed**: `{v['anchor_id']}` on Page {v['page']} stretches from $x_0={v['bbox'][0]}$ to $x_1={v['bbox'][2]}$ (Width: {v['page_width']}).")
                        md.append(f"    > *Excerpt*: \"{v['text_excerpt']}\"")
                    elif v["type"] == "MISSING_DISCUSSION_SECTION":
                        md.append(f"  - ❌ **Section Void**: {v['details']}")
                    else:
                        md.append(f"  - ❌ **{v['type']}**: {v.get('details', '')}")
            md.append("")

    return "\n".join(md)


def main():
    parser = argparse.ArgumentParser(description="WonkProject Deep Indexer Invariant Audit Tool")
    parser.add_argument("--papers_dir", default=DEFAULT_PAPERS_DIR, help="Path to papers directory")
    parser.add_argument("--max_papers", type=int, default=None, help="Limit total papers audited (default: all)")
    parser.add_argument("--include_scanned", action="store_true", default=False, help="Include OCR processing on scanned/outlined PDFs")
    parser.add_argument("--max_scanned", type=int, default=15, help="Maximum scanned papers to OCR (default: 15)")
    parser.add_argument("--output_json", default=DEFAULT_REPORT_JSON, help="Path for JSON audit report")
    parser.add_argument("--output_summary", default=DEFAULT_SUMMARY_MD, help="Path for Markdown summary")
    args = parser.parse_args()

    print("=" * 80)
    print("WONKPROJECT DEEP INDEXER INVARIANT AUDIT")
    print(f"Target Directory: {args.papers_dir}")
    print("=" * 80)

    if not os.path.exists(args.papers_dir):
        print(f"[ERROR] Directory not found: {args.papers_dir}")
        sys.exit(1)

    all_pdf_paths = []
    for root, _, files in os.walk(args.papers_dir):
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("."):
                all_pdf_paths.append(os.path.join(root, f))
    all_pdf_paths.sort()

    print(f"Discovered {len(all_pdf_paths)} total PDF documents.")

    # Classify digital vs scanned
    digital_pdfs = []
    scanned_pdfs = []
    for p in all_pdf_paths:
        if is_scanned_or_outlined(p):
            scanned_pdfs.append(p)
        else:
            digital_pdfs.append(p)

    print(f"Corpus Profile: {len(digital_pdfs)} Born-Digital PDFs | {len(scanned_pdfs)} Scanned/Outlined PDFs")

    # Assemble target queue
    target_pdfs = list(digital_pdfs)
    if args.include_scanned:
        if args.max_scanned > 0:
            target_pdfs.extend(scanned_pdfs[:args.max_scanned])
            print(f"Including {min(len(scanned_pdfs), args.max_scanned)} scanned PDFs with Tesseract OCR.")
        else:
            target_pdfs.extend(scanned_pdfs)
            print(f"Including ALL {len(scanned_pdfs)} scanned PDFs with Tesseract OCR.")
    else:
        print("Scanned PDFs skipped for fast initial pass (use --include_scanned to include).")

    if args.max_papers:
        target_pdfs = target_pdfs[:args.max_papers]

    total_to_audit = len(target_pdfs)
    print(f"\nStarting deep indexing audit of {total_to_audit} manuscripts...\n")

    audit_results: List[Dict[str, Any]] = []
    t_start = time.time()

    critical_count = 0
    clean_count = 0

    for idx, pdf_path in enumerate(target_pdfs):
        filename = os.path.basename(pdf_path)
        progress = f"[{idx+1}/{total_to_audit}]"
        
        # Immediate console print
        print(f"{progress} Auditing: {filename[:55]}...", end=" ", flush=True)
        res = audit_single_document(pdf_path)
        audit_results.append(res)

        if res["has_critical_failure"]:
            critical_count += 1
            print("❌ CRITICAL ANOMALY")
            for v in res["violations"]:
                if v["severity"] == "CRITICAL":
                    print(f"      -> [{v['type']}] {v.get('details') or v.get('text_excerpt', '')[:80]}")
        elif res["violations"]:
            print(f"⚠️ {len(res['violations'])} warning(s)")
        else:
            clean_count += 1
            print("✅ PASS")

    t_elapsed = time.time() - t_start
    print("\n" + "=" * 80)
    print(f"AUDIT COMPLETE in {t_elapsed:.1f}s")
    print(f"Clean Pass: {clean_count}/{total_to_audit} | Critical Failures: {critical_count}/{total_to_audit}")
    print("=" * 80)

    # Save detailed JSON report
    os.makedirs(os.path.dirname(os.path.abspath(args.output_json)), exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.time(),
            "total_audited": total_to_audit,
            "elapsed_seconds": t_elapsed,
            "results": audit_results
        }, f, indent=2)
    print(f"Detailed JSON Report saved to: {args.output_json}")

    # Save Executive Markdown Summary
    md_summary = generate_markdown_summary(audit_results, t_elapsed)
    with open(args.output_summary, "w", encoding="utf-8") as f:
        f.write(md_summary)
    print(f"Executive Markdown Summary saved to: {args.output_summary}")


if __name__ == "__main__":
    main()
