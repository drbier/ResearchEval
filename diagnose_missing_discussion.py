"""
diagnose_missing_discussion.py
Extracts OCR layout blocks and section-detection diagnostics across the Page 5/6
boundary of 'A metronomic schedule as salvage chemotherapy...'.
"""
import os
import sys
import pymupdf

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from audit_indexer_deep import DEFAULT_PAPERS_DIR, TESSDATA_LOCAL
from src.ingestion.indexer import decompose_page_into_blocks, detect_section_header, order_page_blocks

def main():
    target_filename = "A metronomic schedule as salvage chemotherapy for upper gastrointestinal tract cancerS.pdf"
    pdf_path = os.path.join(DEFAULT_PAPERS_DIR, target_filename)
    if not os.path.exists(pdf_path):
        print(f"Error: Target PDF not found at {pdf_path}")
        return

    doc = pymupdf.open(pdf_path)
    print("=" * 80)
    print(f"DIAGNOSTIC: Section Trapping on '{target_filename}'")
    print(f"Total Pages: {len(doc)} | Scanned OCR: True")
    print("=" * 80)

    for page_num in [5, 6]:
        page = doc[page_num - 1]
        print(f"\n--- PAGE {page_num} (Dimensions: {page.rect.width:.1f} x {page.rect.height:.1f}) ---")
        tp = page.get_textpage_ocr(tessdata=TESSDATA_LOCAL, dpi=200, full=True)
        raw_blocks = decompose_page_into_blocks(page, textpage=tp, page_num=page_num)
        ordered = order_page_blocks(raw_blocks, page)
        
        target_slice = ordered[-15:] if page_num == 5 else ordered[:15]
        label = "Final 15 blocks" if page_num == 5 else "First 15 blocks"
        print(f"Total Blocks on Page: {len(ordered)} | Displaying {label}:\n")

        for idx, (b, text) in enumerate(target_slice):
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            first_line = lines[0] if lines else ""
            detected = detect_section_header(first_line, current_section="Results", page_num=page_num)
            
            bbox_str = f"[{b[0]:.1f}, {b[1]:.1f}, {b[2]:.1f}, {b[3]:.1f}]"
            print(f"  Block #{idx+1} {bbox_str} | Detected: {detected or 'None'}")
            print(f"    Line 1: {repr(first_line[:100])}")
            if len(lines) > 1:
                print(f"    Line 2: {repr(lines[1][:100])}")
            if len(lines) > 2:
                print(f"    Line 3: {repr(lines[2][:100])}")
            print()

    doc.close()

if __name__ == "__main__":
    main()

