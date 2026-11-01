"""
diagnose_benchmarks.py — Run diagnostic audit across the 7 benchmark PDFs
Checks:
1. Section distribution and anchor counts
2. Abstract paragraph numbering continuity (are there gaps, skipped numbers?)
3. Sidebar/metadata leakage on Page 1 (e.g. narrow boxes, DOIs, affiliations)
"""

import os
import re
from src.ingestion.indexer import parse_and_index_pdf, IndexedDocument

BENCHMARK_DIR = "data/benchmark"

def audit_paper(pdf_path: str):
    fname = os.path.basename(pdf_path)
    safe_name = fname.encode("ascii", errors="replace").decode("ascii")
    print("\n" + "=" * 90)
    print(f"AUDITING: {safe_name}")
    print("=" * 90)

    try:
        indexed_doc: IndexedDocument = parse_and_index_pdf(pdf_path)
    except Exception as e:
        print(f"  [ERROR] Indexing failed: {e}")
        return

    # 1. Section breakdown
    print("  [Sections & Anchor Counts]:")
    for sec, anchors in indexed_doc.sections.items():
        print(f"    - {sec:<16}: {len(anchors)} anchors (e.g. {anchors[0].anchor_id} .. {anchors[-1].anchor_id})")

    # 2. Page 1 Anchor geometry audit
    p1_anchors = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == 1 and a.anchor_id != "[Doc_Header]"]
    print(f"\n  [Page 1 Anchors ({len(p1_anchors)} total)]:")
    print(f"    {'Anchor ID':<22} | {'BBox [x0, y0, x1, y1]':<30} | {'W x H':<10} | {'First 45 Chars'}")
    print("    " + "-" * 80)
    for a in p1_anchors:
        w_h = f"{a.bbox[2] - a.bbox[0]:.0f}x{a.bbox[3] - a.bbox[1]:.0f}"
        bbox_str = f"[{a.bbox[0]:.1f}, {a.bbox[1]:.1f}, {a.bbox[2]:.1f}, {a.bbox[3]:.1f}]"
        clean_first = a.text.replace("\n", " ").strip()[:45]
        first_45 = clean_first.encode("ascii", errors="replace").decode("ascii")
        print(f"    {a.anchor_id:<22} | {bbox_str:<30} | {w_h:<10} | {first_45}")

    # 3. Detect potential gaps / anomalies in Abstract
    abs_paras = [a for a in indexed_doc.anchor_metadata.values() if a.section == "Abstract" and a.item_type == "para"]
    if abs_paras:
        indices = [a.index for a in abs_paras]
        expected = list(range(1, len(indices) + 1))
        if indices != expected:
            print(f"  [WARN] Abstract paragraph indices not contiguous! Got: {indices}")
        else:
            print(f"  [OK] Abstract paragraph numbers are contiguous: 1..{len(indices)}")

def main():
    files = sorted([os.path.join(BENCHMARK_DIR, f) for f in os.listdir(BENCHMARK_DIR) if f.lower().endswith(".pdf")])
    print(f"Found {len(files)} benchmark papers to audit in {BENCHMARK_DIR}.")
    for f in files:
        audit_paper(f)

if __name__ == "__main__":
    main()
