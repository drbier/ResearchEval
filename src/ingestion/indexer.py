import os
import re
import pymupdf
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel

class CoordinateAnchor(BaseModel):
    anchor_id: str
    section: str
    item_type: str  # "para", "table", "fig", "header"
    index: int
    text: str
    page_number: int
    page_width: float
    page_height: float
    bbox: List[float]  # [x0, y0, x1, y1] in PDF points
    overflow_page: Optional[int] = None
    overflow_bbox: Optional[List[float]] = None

class IndexedDocument(BaseModel):
    filename: str
    doc_header: str
    sections: Dict[str, List[CoordinateAnchor]] = {}
    all_anchors: Dict[str, str] = {}  # Map anchor_id to text
    anchor_metadata: Dict[str, CoordinateAnchor] = {}
    raw_text: str = ""

STRUCTURED_ABSTRACT_MAP = {
    'IMPORTANCE': 'Importance',
    'OBJECTIVE': 'Objective',
    'BACKGROUND': 'Background',
    'CONTEXT': 'Context',
    'DESIGN, SETTING, AND PARTICIPANTS': 'Design',
    'DESIGN': 'Design',
    'SETTING': 'Setting',
    'PARTICIPANTS': 'Participants',
    'INTERVENTIONS': 'Intervention',
    'INTERVENTION': 'Intervention',
    'EXPOSURE': 'Exposure',
    'EXPOSURES': 'Exposure',
    'MAIN OUTCOMES AND MEASURES': 'Outcomes',
    'MAIN OUTCOMES': 'Outcomes',
    'OUTCOMES': 'Outcomes',
    'MEASURES': 'Outcomes',
    'RESULTS': 'Results',
    'FINDINGS': 'Results',
    'CONCLUSIONS AND RELEVANCE': 'Conclusions',
    'CONCLUSIONS': 'Conclusions',
    'CONCLUSION': 'Conclusions'
}

def clean_ocr_text(text: str) -> str:
    """Standardize ligatures, special whitespace, OCR hyphens, and bullet glyph artifacts."""
    if not text:
        return ""
    text = text.replace('\xa0', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    # Clean OCR pseudo-bullet glyph artifacts (e.g. 'e Dietary uptake...' -> '• Dietary uptake...')
    text = re.sub(r'(?m)^[eo•·\-]\s+(?=[A-Z])', '• ', text)
    return text.strip()

def detect_section_header(line: str) -> Optional[str]:
    """Identify common medical manuscript section headers."""
    clean_line = line.strip().strip(':').strip('.').strip('#').strip()
    upper = clean_line.upper()
    
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
    
    if len(clean_line) < 45:
        if upper in section_map:
            return section_map[upper]
        for key in section_map:
            if clean_line.upper().startswith(key + ' ') or clean_line.upper() == key:
                return section_map[key]
    return None

def is_structured_header_line(text: str) -> bool:
    t = text.strip().upper()
    for h in STRUCTURED_ABSTRACT_MAP:
        if re.match(r'^' + re.escape(h) + r'(?:[\s\.:\-\u2013\u2014|]+.*)?$', t):
            return True
    return False

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

def extract_raw_page_lines(page, textpage=None) -> List[Dict[str, Any]]:
    d = page.get_text("dict", textpage=textpage)
    raw_lines = []
    for b in d.get("blocks", []):
        if "lines" not in b:
            continue
        for l in b["lines"]:
            spans = l.get("spans", [])
            valid_spans = [s for s in spans if s.get("text", "").strip()]
            if not valid_spans:
                continue
            line_text = " ".join(s["text"].strip() for s in valid_spans)
            x0 = min(s["bbox"][0] for s in valid_spans)
            y0 = min(s["bbox"][1] for s in valid_spans)
            x1 = max(s["bbox"][2] for s in valid_spans)
            y1 = max(s["bbox"][3] for s in valid_spans)
            raw_lines.append({
                "text": line_text,
                "bbox": [x0, y0, x1, y1],
                "spans": valid_spans
            })
    return raw_lines

def detect_page_column_split(lines: List[Dict[str, Any]], width: float, height: float) -> Tuple[float, bool]:
    w = int(width)
    body_lines = [
        l for l in lines 
        if l["bbox"][1] >= height * 0.15 and l["bbox"][3] <= height * 0.90 and len(l.get("text", "").strip()) >= 2
    ]
    if not body_lines:
        return width * 0.5, False
        
    coverage = [0] * w
    for l in body_lines:
        x0 = max(0, int(l["bbox"][0]))
        x1 = min(w, int(l["bbox"][2]))
        for x in range(x0, x1):
            coverage[x] += 1
            
    start_x = int(w * 0.35)
    end_x = int(w * 0.75)
    band = coverage[start_x:end_x]
    if not band:
        return width * 0.5, False
        
    min_cov = min(band)
    threshold = max(min_cov, 1)
    
    best_start = None
    best_len = 0
    curr_start = None
    curr_len = 0
    
    for idx, cov in enumerate(band):
        if cov <= threshold:
            if curr_start is None:
                curr_start = start_x + idx
                curr_len = 1
            else:
                curr_len += 1
        else:
            if curr_start is not None:
                if curr_len > best_len:
                    best_len = curr_len
                    best_start = curr_start
                curr_start = None
                curr_len = 0
    if curr_start is not None and curr_len > best_len:
        best_len = curr_len
        best_start = curr_start
        
    if best_start is not None and best_len >= 8:
        split_x = best_start + (best_len / 2.0)
        left_count = sum(1 for l in body_lines if l["bbox"][2] < split_x)
        right_count = sum(1 for l in body_lines if l["bbox"][0] > split_x)
        if left_count >= 5 and right_count >= 5:
            return split_x, True
            
    return width * 0.5, False

def extract_clean_page_lines(page, textpage=None) -> List[Dict[str, Any]]:
    """Extract individual text lines with exact bounding boxes, accurately handling multi-column gutters."""
    raw_lines = extract_raw_page_lines(page, textpage=textpage)
    width = float(page.rect.width)
    height = float(page.rect.height)
    
    split_x, is_two_col = detect_page_column_split(raw_lines, width, height)
    
    unmerged_lines = []
    for l in raw_lines:
        valid_spans = l["spans"]
        if not is_two_col:
            unmerged_lines.append({
                "text": l["text"],
                "bbox": l["bbox"],
                "col": 0
            })
            continue
            
        left_spans = [s for s in valid_spans if s["bbox"][2] <= split_x + 8]
        right_spans = [s for s in valid_spans if s["bbox"][0] >= split_x - 8]
        
        # If line has spans on both sides of split_x with an unmistakable gutter between them
        if left_spans and right_spans and (min(s["bbox"][0] for s in right_spans) - max(s["bbox"][2] for s in left_spans)) >= 8.0:
            t_left = " ".join(s["text"].strip() for s in left_spans if s["text"].strip())
            t_right = " ".join(s["text"].strip() for s in right_spans if s["text"].strip())
            if t_left:
                unmerged_lines.append({
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
                unmerged_lines.append({
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
            line_text = l["text"]
            x0 = l["bbox"][0]
            x1 = l["bbox"][2]
            if x1 <= split_x + 8:
                col = 1
            elif x0 >= split_x - 8:
                col = 2
            else:
                col = 0
            unmerged_lines.append({
                "text": line_text,
                "bbox": l["bbox"],
                "col": col
            })
            
    # Merge horizontal line fragments within each column that share the same baseline
    merged_lines = []
    target_cols = [0, 1, 2] if is_two_col else [0]
    for target_col in target_cols:
        col_subset = [l for l in unmerged_lines if l["col"] == target_col]
        if not col_subset:
            continue
        col_subset.sort(key=lambda item: (round(item["bbox"][1] / 3.0), item["bbox"][0]))
        curr_row = [col_subset[0]]
        for item in col_subset[1:]:
            if abs(item["bbox"][1] - curr_row[-1]["bbox"][1]) <= 3.5:
                curr_row.append(item)
            else:
                curr_row.sort(key=lambda r: r["bbox"][0])
                merged_lines.append({
                    "text": " ".join(r["text"] for r in curr_row),
                    "bbox": [
                        min(r["bbox"][0] for r in curr_row),
                        min(r["bbox"][1] for r in curr_row),
                        max(r["bbox"][2] for r in curr_row),
                        max(r["bbox"][3] for r in curr_row)
                    ],
                    "col": target_col
                })
                curr_row = [item]
        if curr_row:
            curr_row.sort(key=lambda r: r["bbox"][0])
            merged_lines.append({
                "text": " ".join(r["text"] for r in curr_row),
                "bbox": [
                    min(r["bbox"][0] for r in curr_row),
                    min(r["bbox"][1] for r in curr_row),
                    max(r["bbox"][2] for r in curr_row),
                    max(r["bbox"][3] for r in curr_row)
                ],
                "col": target_col
            })
            
    return merged_lines

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
        curr_text = l["text"].strip()
        
        is_break = False
        if is_structured_header_line(curr_text):
            is_break = True
        elif vgap > max_vgap:
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
        merged_line_texts = [item["text"] for item in cl]
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
        
    height = float(page.rect.height)
    
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
    
    indexed_doc = IndexedDocument(filename=filename, doc_header="")
    full_text_accumulator: List[str] = []
    
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tessdata_dir = os.path.join(base_dir, "data", "tessdata")
    has_tessdata = os.path.exists(os.path.join(tessdata_dir, "eng.traineddata"))
    
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
        
        blocks = order_page_blocks(raw_blocks, page)
        for b, block_text in blocks:
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
            
            # Clean OCR bullet glyph artifacts within block text
            block_text = clean_ocr_text(block_text)
            
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
        
        anchors_on_curr = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == p_curr and a.item_type == "para"]
        if not anchors_on_curr:
            continue
            
        last_para = anchors_on_curr[-1]
        t = last_para.text.strip()
        if not re.search(r'[\.\?!:]["\'\]\)]*$', t) and len(t) > 60:
            anchors_on_next = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == p_next and a.item_type == "para"]
            if anchors_on_next:
                first_next = anchors_on_next[0]
                last_para.overflow_page = p_next
                last_para.overflow_bbox = first_next.bbox
                last_para.text = f"{last_para.text} {first_next.text}"
                indexed_doc.all_anchors[last_para.anchor_id] = last_para.text
                
    indexed_doc.raw_text = clean_ocr_text("\n\n".join(full_text_accumulator))
    doc.close()
    return indexed_doc
