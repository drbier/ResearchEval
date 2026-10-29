import os
import re
from typing import List, Dict, Any, Optional
import pymupdf
from pydantic import BaseModel, Field

class CoordinateAnchor(BaseModel):
    anchor_id: str
    section: str
    item_type: str  # 'header', 'para', 'table', 'fig', 'supp'
    index: int
    text: str
    page_number: int
    page_width: float = 595.0
    page_height: float = 842.0
    bbox: Optional[List[float]] = None  # [x0, y0, x1, y1] on the page
    overflow_page: Optional[int] = None
    overflow_bbox: Optional[List[float]] = None
    overflow_text: Optional[str] = None

class IndexedDocument(BaseModel):
    filename: str
    doc_header: str
    sections: Dict[str, List[CoordinateAnchor]] = Field(default_factory=dict)
    all_anchors: Dict[str, str] = Field(default_factory=dict)  # anchor_id -> text
    anchor_metadata: Dict[str, CoordinateAnchor] = Field(default_factory=dict)  # anchor_id -> CoordinateAnchor
    raw_text: str = ""

def clean_text(text: str) -> str:
    """Normalize whitespace and strip spurious control characters."""
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def detect_section_header(line: str) -> Optional[str]:
    """Identify common medical manuscript section headers."""
    clean_line = line.strip().strip(':').strip('.').strip('#').strip()
    upper = clean_line.upper()
    
    # Common standard sections
    section_map = {
        'ABSTRACT': 'Abstract',
        'INTRODUCTION': 'Introduction',
        'BACKGROUND': 'Introduction',
        'METHODS': 'Methods',
        'PATIENTS AND METHODS': 'Methods',
        'MATERIALS AND METHODS': 'Methods',
        'STUDY DESIGN': 'Methods',
        'RESULTS': 'Results',
        'FINDINGS': 'Results',
        'DISCUSSION': 'Discussion',
        'CONCLUSIONS': 'Discussion',
        'CONCLUSION': 'Discussion',
        'LIMITATIONS': 'Discussion',
        'SUPPLEMENTARY MATERIAL': 'Supplementary',
        'SUPPLEMENTARY APPENDIX': 'Supplementary',
        'APPENDIX': 'Supplementary',
        'REFERENCES': 'References'
    }
    
    # Header heuristics: short length, uppercase or title case match
    if len(clean_line) < 45:
        if upper in section_map:
            return section_map[upper]
        for key in section_map:
            if clean_line.upper().startswith(key + ' ') or clean_line.upper() == key:
                return section_map[key]
    return None

def parse_and_index_pdf(pdf_path: str) -> IndexedDocument:
    """Parse a medical paper PDF into structured, coordinate-indexed blocks."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    doc = pymupdf.open(pdf_path)
    filename = os.path.basename(pdf_path)
    
    current_section = "Introduction"
    section_para_counters: Dict[str, int] = {}
    section_table_counters: Dict[str, int] = {}
    section_fig_counters: Dict[str, int] = {}
    
    indexed_doc = IndexedDocument(filename=filename, doc_header="")
    full_text_accumulator: List[str] = []
    
    # Step 1: Extract Document Header (First ~500 words or Page 1 Top)
    page1_text = doc[0].get_text() if len(doc) > 0 else ""
    header_lines = [l.strip() for l in page1_text.split('\n') if l.strip()]
    doc_header = "\n".join(header_lines[:35])[:2500]
    indexed_doc.doc_header = doc_header
    indexed_doc.all_anchors["[Doc_Header]"] = doc_header
    indexed_doc.anchor_metadata["[Doc_Header]"] = CoordinateAnchor(
        anchor_id="[Doc_Header]",
        section="Header",
        item_type="header",
        index=0,
        text=doc_header,
        page_number=1,
        page_width=float(doc[0].rect.width) if len(doc) > 0 else 595.0,
        page_height=float(doc[0].rect.height) if len(doc) > 0 else 842.0,
        bbox=[30.0, 30.0, float(doc[0].rect.width) - 30.0 if len(doc) > 0 else 560.0, 240.0]
    )
    
    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        page_text = page.get_text("text")
        full_text_accumulator.append(page_text)
        
        # Split by double newline or block clusters
        blocks = page.get_text("blocks")
        for b in blocks:
            block_text = clean_text(b[4])
            if not block_text:
                continue
            
            # Check for section header
            first_line = block_text.split('\n')[0].strip()
            detected = detect_section_header(first_line)
            if detected:
                current_section = detected
                # If block had only the header, move to next
                if len(first_line) == len(block_text):
                    continue
                else:
                    block_text = block_text[len(first_line):].strip()
            
            if not block_text:
                continue
            
            # Detect tables or figures
            is_table = bool(re.search(r'^(Table\s+\d+|TABLE\s+\d+)', block_text, re.IGNORECASE))
            is_fig = bool(re.search(r'^(Fig(?:ure)?\.?\s+\d+)', block_text, re.IGNORECASE))
            
            if is_table:
                section_table_counters[current_section] = section_table_counters.get(current_section, 0) + 1
                t_idx = section_table_counters[current_section]
                anchor_id = f"[{current_section}, Table {t_idx}]"
                item_type = "table"
                idx = t_idx
            elif is_fig:
                section_fig_counters[current_section] = section_fig_counters.get(current_section, 0) + 1
                f_idx = section_fig_counters[current_section]
                anchor_id = f"[{current_section}, Fig {f_idx}]"
                item_type = "fig"
                idx = f_idx
            else:
                section_para_counters[current_section] = section_para_counters.get(current_section, 0) + 1
                p_idx = section_para_counters[current_section]
                anchor_id = f"[{current_section}, Para {p_idx}]"
                item_type = "para"
                idx = p_idx
            
            anchor_obj = CoordinateAnchor(
                anchor_id=anchor_id,
                section=current_section,
                item_type=item_type,
                index=idx,
                text=block_text,
                page_number=page_num,
                page_width=float(page.rect.width),
                page_height=float(page.rect.height),
                bbox=[float(b[0]), float(b[1]), float(b[2]), float(b[3])]
            )
            
            if current_section not in indexed_doc.sections:
                indexed_doc.sections[current_section] = []
            indexed_doc.sections[current_section].append(anchor_obj)
            indexed_doc.all_anchors[anchor_id] = block_text
            indexed_doc.anchor_metadata[anchor_id] = anchor_obj
            
    # Post-process: Check for paragraphs ending mid-sentence that overflow to next page
    for i in range(len(doc) - 1):
        p_curr = i + 1
        p_next = i + 2
        
        # Find paragraph anchors on current page
        anchors_on_curr = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == p_curr and a.item_type == "para"]
        if not anchors_on_curr:
            continue
            
        # Check all paragraphs on the page that end without terminal punctuation
        for candidate in anchors_on_curr:
            t = candidate.text.strip()
            # If line ends without period, question mark, exclamation point, or colon
            if t and not re.search(r'[\.\?!:]["\'\]\)]*$', t):
                # Search next page for the continuation block
                blocks_next = doc[i + 1].get_text("blocks")
                for b_next in blocks_next:
                    b_text = clean_text(b_next[4])
                    # Skip running header, volume number, and page numbers
                    if not b_text or len(b_text) < 10 or re.match(r'^(?:Vol\.|GeroScience|\d{3,}|\d+\s+\d+)', b_text):
                        continue
                    
                    # If this block continues the sentence (e.g. starts with lowercase or continuation word)
                    candidate.overflow_page = p_next
                    candidate.overflow_bbox = [float(b_next[0]), float(b_next[1]), float(b_next[2]), float(b_next[3])]
                    candidate.overflow_text = b_text
                    
                    # Merge text so downstream readers get the complete sentence
                    merged_text = f"{candidate.text} {b_text}"
                    candidate.text = merged_text
                    indexed_doc.all_anchors[candidate.anchor_id] = merged_text
                    break

    indexed_doc.raw_text = clean_text("\n\n".join(full_text_accumulator))
    return indexed_doc

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    test_pdf = r"D:\SSD-Drive\Antigravity\ResearchEval\Reference_papers\2.Statistics\Interpreting_the_results_of_noninferiority_trials-.pdf"
    if os.path.exists(test_pdf):
        indexed = parse_and_index_pdf(test_pdf)
        print(f"Indexed PDF: {indexed.filename}")
        print(f"Total Anchors: {len(indexed.all_anchors)}")
        print("Sections detected:", list(indexed.sections.keys()))
        for k in list(indexed.all_anchors.keys())[:8]:
            sample = indexed.all_anchors[k].replace("\n", " ")[:80]
            print(f"{k} -> {sample}...")
