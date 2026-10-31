import os
import sys
import re
from typing import List, Dict, Any, Optional
import pymupdf
from pydantic import BaseModel, Field

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

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
    
    # Common standard sections and clinical trial subheadings
    section_map = {
        'ABSTRACT': 'Abstract',
        'INTRODUCTION': 'Introduction',
        'BACKGROUND': 'Introduction',
        'METHODS': 'Methods',
        'PATIENTS AND METHODS': 'Methods',
        'MATERIALS AND METHODS': 'Methods',
        'STUDY DESIGN': 'Methods',
        'PATIENT POPULATION': 'Methods',
        'TREATMENT PLAN': 'Methods',
        'ASSESSMENTS': 'Methods',
        'STATISTICAL ANALYSIS': 'Methods',
        'RESULTS': 'Results',
        'FINDINGS': 'Results',
        'EFFICACY': 'Results',
        'SAFETY': 'Results',
        'TREATMENT EXPOSURE': 'Results',
        'DISCUSSION': 'Discussion',
        'CONCLUSIONS': 'Discussion',
        'CONCLUSION': 'Discussion',
        'LIMITATIONS': 'Discussion',
        'LIMITATIONS OF THE STUDY': 'Discussion',
        'LIMITATIONS OF OUR WORK': 'Discussion',
        'RESOURCE AVAILABILITY': 'Methods',
        'STAR METHODS': 'Methods',
        'STAR*METHODS': 'Methods',
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

def is_junk_block(b, page, text: str) -> bool:
    """Filter out publisher watermarks, barcodes, margin running heads, and disconnected axis fragments."""
    h = page.rect.height
    clean_t = text.strip()
    
    # 1. Top/bottom running headers and footers
    if b[1] < 45 and (re.search(r'GeroScience|\d{4}|Vol[:\.]|https?://|[©\u00a9]', clean_t) or len(clean_t) < 40):
        return True
    if b[3] > h - 45 and (re.search(r'Vol[:\.]|1\s+3|\d{1,4}', clean_t) or len(clean_t) < 30):
        return True
    # 2. Publisher volume tags, barcodes, pagination marks
    if re.search(r'^(?:Vol[:\.]+\s*\(?\d+\)?|1\s+3|\d{1,5}|[0-9\s\.\(\)\-\u2013/:]+)$', clean_t, re.IGNORECASE):
        return True
    # 3. Disconnected plot/axis labels without word structure
    if len(clean_t) < 25 and not re.search(r'[a-zA-Z]{3,}', clean_t):
        return True
    # 4. Standalone copyright notice
    if re.match(r'^[©\u00a9]\s*The\s+Author', clean_t, re.IGNORECASE):
        return True
    return False

def extract_clean_page_lines(page, textpage=None) -> List[Dict[str, Any]]:
    """Extract individual text lines with exact bounding boxes, splitting lines accidentally merged across columns."""
    d = page.get_text("dict", textpage=textpage)
    width = float(page.rect.width)
    mid_x = width * 0.5
    
    clean_lines = []
    
    for b in d.get("blocks", []):
        if "lines" not in b:
            continue
        for l in b["lines"]:
            spans = l.get("spans", [])
            valid_spans = [s for s in spans if s.get("text", "").strip()]
            if not valid_spans:
                continue
                
            left_spans = [s for s in valid_spans if s["bbox"][2] <= mid_x + 10]
            right_spans = [s for s in valid_spans if s["bbox"][0] >= mid_x - 10]
            
            # If line has spans on both sides of center and there is an unmistakable gutter between them
            if left_spans and right_spans and (min(s["bbox"][0] for s in right_spans) - max(s["bbox"][2] for s in left_spans)) >= 8.0:
                t_left = " ".join(s["text"].strip() for s in left_spans if s["text"].strip())
                t_right = " ".join(s["text"].strip() for s in right_spans if s["text"].strip())
                if t_left:
                    clean_lines.append({
                        "text": t_left,
                        "bbox": [
                            min(s["bbox"][0] for s in left_spans),
                            min(s["bbox"][1] for s in left_spans),
                            max(s["bbox"][2] for s in left_spans),
                            max(s["bbox"][3] for s in left_spans)
                        ],
                        "col": 1
                    })
                if t_right:
                    clean_lines.append({
                        "text": t_right,
                        "bbox": [
                            min(s["bbox"][0] for s in right_spans),
                            min(s["bbox"][1] for s in right_spans),
                            max(s["bbox"][2] for s in right_spans),
                            max(s["bbox"][3] for s in right_spans)
                        ],
                        "col": 2
                    })
            else:
                line_text = " ".join(s["text"].strip() for s in valid_spans if s["text"].strip())
                if len(valid_spans) > 1:
                    x0 = min(s["bbox"][0] for s in valid_spans)
                    x1 = max(s["bbox"][2] for s in valid_spans)
                    # Filter out single-span OCR width glitches that extend across gutter
                    if sum(1 for s in valid_spans if s["bbox"][0] >= mid_x - 10) >= len(valid_spans) * 0.7:
                        x0 = max(x0, min(s["bbox"][0] for s in valid_spans if s["bbox"][0] >= mid_x - 10))
                        col = 2
                    elif sum(1 for s in valid_spans if s["bbox"][2] <= mid_x + 10) >= len(valid_spans) * 0.7:
                        x1 = min(x1, max(s["bbox"][2] for s in valid_spans if s["bbox"][2] <= mid_x + 10))
                        col = 1
                    else:
                        col = 0
                else:
                    x0 = valid_spans[0]["bbox"][0]
                    x1 = valid_spans[0]["bbox"][2]
                    col = 1 if x1 <= mid_x + 10 else (2 if x0 >= mid_x - 10 else 0)
                    
                y0 = min(s["bbox"][1] for s in valid_spans)
                y1 = max(s["bbox"][3] for s in valid_spans)
                clean_lines.append({
                    "text": line_text,
                    "bbox": [x0, y0, x1, y1],
                    "col": col
                })
                
    return clean_lines

def cluster_column_lines(lines: List[Dict[str, Any]], max_vgap: float = 14.0) -> List[Any]:
    """Cluster lines strictly within a single column into cohesive paragraphs with tight bounding boxes."""
    if not lines:
        return []
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    x0_values = sorted([l["bbox"][0] for l in lines])
    col_left_margin = x0_values[len(x0_values) // 5]
    
    clusters = []
    curr = [lines[0]]
    
    for l in lines[1:]:
        prev = curr[-1]
        vgap = l["bbox"][1] - prev["bbox"][3]
        prev_text = prev["text"].strip()
        
        is_break = False
        if vgap > max_vgap:
            is_break = True
        elif vgap > 5.0 and re.search(r'[\.\?!:]["\'\]\)]*$', prev_text):
            is_break = True
        elif (l["bbox"][0] - col_left_margin) >= 7.0 and re.search(r'[\.\?!:]["\'\]\)]*$', prev_text):
            is_break = True
            
        if is_break:
            clusters.append(curr)
            curr = [l]
        else:
            curr.append(l)
            
    if curr:
        clusters.append(curr)
        
    blocks = []
    for cl in clusters:
        # Group fragments on same horizontal baseline
        cl.sort(key=lambda item: (round(item["bbox"][1] / 3.0), item["bbox"][0]))
        merged_line_texts = []
        curr_row = [cl[0]]
        for item in cl[1:]:
            if abs(item["bbox"][1] - curr_row[-1]["bbox"][1]) <= 3.5:
                curr_row.append(item)
            else:
                curr_row.sort(key=lambda r: r["bbox"][0])
                merged_line_texts.append(" ".join(r["text"] for r in curr_row))
                curr_row = [item]
        if curr_row:
            curr_row.sort(key=lambda r: r["bbox"][0])
            merged_line_texts.append(" ".join(r["text"] for r in curr_row))
            
        block_text = "\n".join(merged_line_texts)
        x0 = min(item["bbox"][0] for item in cl)
        y0 = min(item["bbox"][1] for item in cl)
        x1 = max(item["bbox"][2] for item in cl)
        y1 = max(item["bbox"][3] for item in cl)
        blocks.append((x0, y0, x1, y1, block_text, 0, 0))
        
    return blocks

def decompose_page_into_blocks(page, textpage=None) -> List[Any]:
    """Deconstructs page lines into strictly column-isolated blocks in true academic reading order."""
    lines = extract_clean_page_lines(page, textpage=textpage)
    if not lines:
        return page.get_text("blocks", textpage=textpage) if textpage else page.get_text("blocks")
        
    width = float(page.rect.width)
    height = float(page.rect.height)
    mid_x = width * 0.5
    
    col1_lines = [l for l in lines if l["col"] == 1]
    col2_lines = [l for l in lines if l["col"] == 2]
    full_lines = [l for l in lines if l["col"] == 0]
    
    is_two_column = len(col1_lines) >= 4 and len(col2_lines) >= 4
    if is_two_column:
        top_full = cluster_column_lines([l for l in full_lines if l["bbox"][3] < height * 0.35], max_vgap=18.0)
        col1_blocks = cluster_column_lines(col1_lines, max_vgap=14.0)
        col2_blocks = cluster_column_lines(col2_lines, max_vgap=14.0)
        bot_full = cluster_column_lines([l for l in full_lines if l["bbox"][1] >= height * 0.35], max_vgap=18.0)
        return top_full + col1_blocks + col2_blocks + bot_full
    else:
        return cluster_column_lines(lines, max_vgap=14.0)

def order_page_blocks(raw_blocks, page) -> List[Any]:
    """Filter junk blocks while preserving the column-aware reading order."""
    valid = []
    for b in raw_blocks:
        t = b[4].strip().replace('\xa0', ' ')
        if not t or is_junk_block(b, page, t):
            continue
        valid.append((b, t))
    return valid

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
    
    # Locate local Tessdata directory for automatic OCR fallback on scanned PDFs
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tessdata_dir = os.path.join(base_dir, "data", "tessdata")
    has_tessdata = os.path.exists(os.path.join(tessdata_dir, "eng.traineddata"))
    
    # Detect if PDF contains selectable digital text or is a scanned/flattened image PDF
    sample_text = "".join(doc[i].get_text().strip() for i in range(min(5, len(doc))))
    is_scanned_pdf = (len(sample_text) < 100) and has_tessdata
    if is_scanned_pdf:
        safe_name = filename.encode('ascii', errors='replace').decode('ascii')
        print(f"[Indexer] Scanned / image-only PDF detected ({safe_name}). Activating high-precision OCR pipeline...")

    # Step 1: Extract Document Header (First ~500 words or Page 1 Top)
    if is_scanned_pdf and has_tessdata:
        try:
            tp0 = doc[0].get_textpage_ocr(tessdata=tessdata_dir, dpi=200, full=True)
            page1_text = tp0.extractText()
        except Exception:
            page1_text = doc[0].get_text() if len(doc) > 0 else ""
    else:
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
        
        if is_scanned_pdf and has_tessdata:
            try:
                tp = page.get_textpage_ocr(tessdata=tessdata_dir, dpi=200, full=True)
                page_text = tp.extractText()
                raw_blocks = decompose_page_into_blocks(page, textpage=tp)
            except Exception as e:
                print(f"[Indexer] Warning: OCR failed on page {page_num}: {e}")
                page_text = page.get_text("text")
                raw_blocks = decompose_page_into_blocks(page)
        else:
            page_text = page.get_text("text")
            raw_blocks = decompose_page_into_blocks(page)

        full_text_accumulator.append(page_text)
        
        # Order blocks according to two-column human reading layout, filtering junk
        blocks = order_page_blocks(raw_blocks, page)
        for b, block_text in blocks:
            # Check lines for section header (supports standalone lines and short headers)
            lines = [l.strip() for l in block_text.split('\n') if l.strip()]
            for l_idx, line in enumerate(lines[:5]):
                detected = detect_section_header(line)
                if detected:
                    current_section = detected
                    if len(lines) == 1:
                        block_text = ""
                    elif l_idx == 0:
                        block_text = "\n".join(lines[1:]).strip()
                    break
            
            if not block_text:
                continue
            
            # Distinguish narrative discussion sentences from true Table/Figure captions
            is_narrative = bool(re.search(
                r'^(?:Fig(?:ure)?|Table)\s*\d+\s+(?:shows?|presents?|displays?|depicts?|illustrates?|demonstrates?|compares?|indicates?|reveals?|summarizes?|lists?|reports?|provides?|plots?|evaluates?)\b',
                block_text, re.IGNORECASE
            ))
            
            is_table = False
            is_fig = False
            
            if not is_narrative:
                tbl_match = re.match(r'^(?:Table\s*(\d+)[\s\.:\-\u2013\u2014|]+(?![a-z]))', block_text, re.IGNORECASE)
                fig_match = re.match(r'^(?:Fig(?:ure)?\.?\s*(\d+)[\s\.:\-\u2013\u2014|]+(?![a-z]))', block_text, re.IGNORECASE)
                if tbl_match:
                    is_table = True
                    tbl_num = tbl_match.group(1)
                    anchor_id = f"[{current_section}, Table {tbl_num}]"
                    item_type = "table"
                    idx = int(tbl_num)
                elif fig_match:
                    is_fig = True
                    fig_num = fig_match.group(1)
                    anchor_id = f"[{current_section}, Fig {fig_num}]"
                    item_type = "fig"
                    idx = int(fig_num)
            
            if not is_table and not is_fig:
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
            
    # Post-process: Check only the last body paragraph on the page if it overflows mid-sentence
    for i in range(len(doc) - 1):
        p_curr = i + 1
        p_next = i + 2
        
        # Find paragraph anchors on current page
        anchors_on_curr = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == p_curr and a.item_type == "para"]
        if not anchors_on_curr:
            continue
            
        last_para = anchors_on_curr[-1]
        t = last_para.text.strip()
        # If line ends without terminal punctuation and is not a short header/fragment
        if t and len(t) > 60 and not re.search(r'[\.\?!:]["\'\]\)]*$', t):
            blocks_next = order_page_blocks(doc[i + 1].get_text("blocks"), doc[i + 1])
            for b_next, b_text in blocks_next:
                if detect_section_header(b_text.split('\n')[0]):
                    break
                # Only merge if next block starts with lowercase or continuation word
                if re.match(r'^[a-z0-9]|^(?:and|or|of|to|with|in|that|which|the|is|was|are|were)\b', b_text, re.IGNORECASE):
                    last_para.overflow_page = p_next
                    last_para.overflow_bbox = [float(b_next[0]), float(b_next[1]), float(b_next[2]), float(b_next[3])]
                    last_para.overflow_text = b_text
                    
                    merged_text = f"{last_para.text} {b_text}"
                    last_para.text = merged_text
                    indexed_doc.all_anchors[last_para.anchor_id] = merged_text
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
