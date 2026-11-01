"""
diagnose_anchors.py — Phase 0 Empirical Diagnostic Script
Extracts and inspects raw coordinate anchors from target PDFs to identify
interleaved sidebar metadata, margin notes, and counter-skipping causes.
"""

import os
import sys
from src.ingestion.indexer import parse_and_index_pdf, IndexedDocument

TARGET_PDFS = [
    # 1. PACIFIC trial paper (complex 2-column + right margin metadata sidebar)
    "data/uploads/Differential impact of PPI on ImmunotherapyS.pdf",
    # 2. Standard medical paper without margin sidebar
    "data/uploads/The association between dietary creatine intake and cancer in U.S. adults- insights from NHANES 2007-2018S.pdf"
]

def dump_anchors_for_pdf(pdf_path: str, max_anchors: int = 150):
    if not os.path.exists(pdf_path):
        print(f"[ERROR] Target file not found: {pdf_path}")
        return

    print("=" * 120)
    print(f"DOCUMENT: {os.path.basename(pdf_path)}")
    print("=" * 120)

    indexed_doc: IndexedDocument = parse_and_index_pdf(pdf_path)
    anchors = list(indexed_doc.anchor_metadata.values())

    print(f"Total Anchors Extracted: {len(anchors)}")
    print(f"{'Section':<14} | {'Anchor ID':<22} | {'Pg':<3} | {'BBox [x0, y0, x1, y1]':<32} | {'W x H':<11} | {'First 50 Chars'}")
    print("-" * 120)

    for idx, anc in enumerate(anchors[:max_anchors]):
        clean_text = anc.text.replace("\n", " ").strip()
        first_50 = clean_text[:50] + ("..." if len(clean_text) > 50 else "")
        bbox_str = f"[{anc.bbox[0]:.1f}, {anc.bbox[1]:.1f}, {anc.bbox[2]:.1f}, {anc.bbox[3]:.1f}]"
        w_h = f"{anc.bbox[2] - anc.bbox[0]:.0f}x{anc.bbox[3] - anc.bbox[1]:.0f}"
        print(f"{anc.section:<14} | {anc.anchor_id:<22} | {anc.page_number:<3} | {bbox_str:<32} | {w_h:<11} | {first_50}")

    if len(anchors) > max_anchors:
        print(f"\n... [{len(anchors) - max_anchors} additional anchors omitted for brevity] ...\n")

if __name__ == "__main__":
    for pdf in TARGET_PDFS:
        dump_anchors_for_pdf(pdf)

