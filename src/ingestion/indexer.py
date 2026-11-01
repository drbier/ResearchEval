import os
import re
import pymupdf
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel

class CoordinateAnchor(BaseModel):
    anchor_id: str
    section: str
    item_type: str  # "para", "table", "fig", "header", "metadata"
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
    'METHODS': 'Methods',
    'METHOD': 'Methods',
    'PATIENTS AND METHODS': 'Methods',
    'MATERIALS AND METHODS': 'Methods',
    'STUDY DESIGN': 'Methods',
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
    'INTERPRETATION': 'Interpretation',
    'INTERPRETATIONS': 'Interpretation',
    'CONCLUSIONS AND RELEVANCE': 'Conclusions',
    'CONCLUSIONS': 'Conclusions',
    'CONCLUSION': 'Conclusions',
    'FUNDING': 'Funding'
}

PRIMARY_ABSTRACT_HEADERS = {
    'BACKGROUND', 'OBJECTIVE', 'METHODS', 'METHOD', 'PATIENTS AND METHODS',
    'MATERIALS AND METHODS', 'FINDINGS', 'RESULTS', 'INTERPRETATION',
    'INTERPRETATIONS', 'CONCLUSIONS', 'CONCLUSION', 'FUNDING'
}

METADATA_CONTENT_REGEX = re.compile(
    r'\b(?:Correspondence(?:\s+to)?|Department\s+of|Hospital|University|Institute|School\s+of\s+Medicine|'
    r'Centre|Center|Clinic|Faculty\s+of|Published\s+Online|doi(?:\.org)?|https?://doi|N\s+Engl\s+J\s+Med|'
    r'Lancet|BMJ|JAMA|Cell\s+Metabolism|Nature|Springer|Elsevier|Wiley|PMID|PMCID|ClinicalTrials\.gov|'
    r'NCT\d{8}|Author\s+Affiliations?|\*Members\s+listed|Contributed\s+equally|Cite\s+this\s+as)\b',
    re.IGNORECASE
)

EXPLICIT_METADATA_HEADER_REGEX = re.compile(
    r'^(?:Correspondence:?|Correspondence\s+to:?|Cite\s+this\s+as:?|Keywords:?|\*Corresponding\s+author:?|'
    r'Open\s+Access\.\s+[©\u00a9]|Copyright\s+[©\u00a9]|Author\s+contributions:?|Competing\s+interests:?)',
    re.IGNORECASE
)

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

def detect_section_header(line: str, current_section: Optional[str] = None, page_num: int = 1) -> Optional[str]:
    """Identify common medical manuscript section headers, supporting numbered prefixes and subsections."""
    clean_line = line.strip().strip(':').strip('.').strip('#').strip()
    if not clean_line or len(clean_line) > 55:
        return None
    
    # Strip markdown formatting
    clean_line = re.sub(r'^[#*_\s]+', '', clean_line).strip()
    clean_line = re.sub(r'[:#*_\s\.]+$', '', clean_line).strip()
    
    # Strip leading numbers/roman numerals and section prefixes: e.g. "1.", "1 ", "1.1", "3 ", "Section 3:"
    stripped = re.sub(r'^(?:(?:section|part|sec)\.?\s*)?(?:[0-9]+(?:\.[0-9]+)*|[IVXLCDM]+)[\.\s\-:\)]+\s*', '', clean_line, flags=re.IGNORECASE).strip()
    upper = stripped.upper()
    
    section_map = {
        'ABSTRACT': 'Abstract',
        'SUMMARY': 'Abstract',
        'HIGHLIGHTS': 'Abstract',
        'INTRODUCTION': 'Introduction',
        'BACKGROUND': 'Introduction',
        'METHODS': 'Methods',
        'PATIENTS AND METHODS': 'Methods',
        'MATERIALS AND METHODS': 'Methods',
        'MATERIALS & METHODS': 'Methods',
        'METHODOLOGY': 'Methods',
        'STUDY DESIGN': 'Methods',
        'RESULTS': 'Results',
        'FINDINGS': 'Results',
        'RESULTS AND DISCUSSION': 'Results',
        'DISCUSSION': 'Discussion',
        'LIMITATIONS': 'Discussion',
        'CONCLUSIONS': 'Conclusions',
        'CONCLUSION': 'Conclusions',
        'INTERPRETATION': 'Conclusions',
        'DECLARATIONS': 'References',
        'CONFLICT OF INTEREST': 'References',
        'CONFLICTS OF INTEREST': 'References',
        'COMPETING INTERESTS': 'References',
        'ACKNOWLEDGEMENTS': 'References',
        'ACKNOWLEDGMENT': 'References',
        'ACKNOWLEDGMENTS': 'References',
        'REFERENCES': 'References',
        'LITERATURE CITED': 'References',
        'BIBLIOGRAPHY': 'References',
        'SUPPLEMENTARY INFORMATION': 'Appendix',
        'SUPPLEMENTARY MATERIAL': 'Appendix',
        'SUPPLEMENTARY APPENDIX': 'Appendix',
        'APPENDIX': 'Appendix'
    }
    
    if current_section == 'Abstract':
        is_numbered = bool(re.match(r'^(?:[0-9]+|[IVXLCDM]+)[\.\s\-:\)]+', clean_line))
        has_colon_content = bool(re.search(r'^(?:Methods|Results|Conclusion|Background|Objective|Context)\s*:\s*\S', clean_line, re.IGNORECASE))
        
        if is_numbered:
            for k in section_map:
                if upper == k or upper.startswith(k + ' '):
                    return section_map[k]
            return None
        elif upper in ('INTRODUCTION', 'BACKGROUND') and not has_colon_content:
            return section_map[upper]
        elif page_num >= 2 and upper in section_map and not has_colon_content:
            return section_map[upper]
        elif upper in ('PATIENTS AND METHODS', 'MATERIALS AND METHODS', 'MATERIALS & METHODS', 'STUDY DESIGN'):
            return 'Methods'
        else:
            return None
        
    if upper in section_map:
        return section_map[upper]
    for key in section_map:
        if upper == key:
            return section_map[key]
        if upper.startswith(key + ' '):
            # Guard: do not match inline citations or sentence fragments like "appendix p 18", "appendix (pp 7-10)", "methods see online"
            if key in ('APPENDIX', 'SUPPLEMENTARY', 'SUPPLEMENTARY APPENDIX', 'SUPPLEMENTARY MATERIAL'):
                if re.match(r'^(?:APPENDIX|SUPPLEMENTARY(?:\s+(?:APPENDIX|MATERIAL))?)\s*(?:[0-9A-Z]+|TABLE|FIGURE)?$', upper):
                    return section_map[key]
                continue
            return section_map[key]
    return None

def is_structured_header_line(curr_text: str, prev_text: str = "") -> bool:
    """
    Identifies structured abstract subsection labels (e.g. 'Background', 'Methods', 'Findings', 'Interpretation').
    Guards against accidental splitting on lowercase prose words (e.g. 'exposure to...').
    """
    t = curr_text.strip()
    if not t or t[0].islower():
        return False
    
    # 1. Primary headers (Methods, Background, Findings, Results, Interpretation, Conclusions, Funding)
    # Always start a new paragraph if capitalized and followed by colon, capital letter, bracket, or standalone
    for h in PRIMARY_ABSTRACT_HEADERS:
        m = re.match(r'^(' + re.escape(h) + r')(?:\s*[:\.\-\u2013\u2014|]|\s+([A-Z0-9\(\[])|\s*$)', t, re.IGNORECASE)
        if m:
            matched_kw = m.group(1)
            if matched_kw[0].isupper():
                cont = m.group(2)
                if cont is None or cont.isupper() or cont in "([0-9":
                    return True
            
    # 2. Secondary/Sub-headers (Design, Setting, Participants, Interventions, Outcomes, Exposure)
    # Must have preceding sentence-terminal punctuation or explicit colon to prevent breaking running prose
    for h in STRUCTURED_ABSTRACT_MAP:
        m = re.match(r'^(' + re.escape(h) + r')(?:\s*[:\.\-\u2013\u2014|]|\s+([A-Z0-9\(\[])|\s*$)', t, re.IGNORECASE)
        if m:
            matched_kw = m.group(1)
            if matched_kw[0].isupper():
                if re.match(r'^[A-Za-z\s]+[:\.\-]', t):
                    return True
                if prev_text and re.search(r'[\.\?!:]["\'\]\)]*$', prev_text.strip()):
                    cont = m.group(2)
                    if cont is None or cont.isupper() or cont in "([0-9":
                        return True
            
    return False

def is_junk_block(b, page, text: str) -> bool:
    """Filter out publisher watermarks, barcodes, margin running heads, and disconnected axis fragments."""
    h = page.rect.height
    clean_t = text.strip()
    
    # 1. Top/bottom running headers and footers (must start near margin AND be brief, not entire paragraphs)
    if b[1] < 55 and len(clean_t) < 160 and (re.search(r'JAMA|Lancet|BMJ|Frontiers|Nature|Science|Springer|Elsevier|GeroScience|\d{4}|Vol[:\.]|https?://|doi:|doi\.org|[©\u00a9]', clean_t, re.IGNORECASE) or len(clean_t) < 40):
        return True
    if b[1] > h - 55 and len(clean_t) < 160 and (re.search(r'JAMA|Lancet|BMJ|Frontiers|Nature|Science|Springer|Elsevier|Vol[:\.]|1\s+3|\d{1,4}|doi:|https?://', clean_t, re.IGNORECASE) or len(clean_t) < 30):
        return True
    # 2. Publisher license, repository downloads, watermarks anywhere on page
    if re.search(r'Open Access\.\s+This is an open access article', clean_t, re.IGNORECASE):
        return True
    if re.search(r'Downloaded from\s+[a-z0-9\.\-]+', clean_t, re.IGNORECASE):
        return True
    if re.search(r'^(?:[0-9\s\.\(\)\-\u2013/:]*doi:10\.\d{4,9}/[^\n]*)$', clean_t, re.IGNORECASE):
        return True
    if re.search(r'^(?:JAMA Network Open\.\s*\d{4}[^\n]*doi:[^\n]*)$', clean_t, re.IGNORECASE):
        return True
    # 3. Publisher volume tags, barcodes, pagination marks
    if re.search(r'^(?:Vol[:\.]+\s*\(?\d+\)?|1\s+3|\d{1,5}|[0-9\s\.\(\)\-\u2013/:]+)$', clean_t, re.IGNORECASE):
        return True
    # 4. Disconnected plot/axis labels without word structure, or single isolated punctuation
    if len(clean_t) <= 2 and not clean_t.isalnum():
        return True
    if len(clean_t) < 25 and not re.search(r'[a-zA-Z]{3,}', clean_t):
        return True
    if len(clean_t) < 15 and re.search(r'crossmark|sciencedirect|elsevier|springer|wiley', clean_t, re.IGNORECASE):
        return True
    if len(clean_t) <= 6 and (clean_t.endswith(']') or not clean_t.isalnum()):
        return True
    # 5. Standalone copyright notice
    if re.match(r'^[©\u00a9]\s*The\s+Author', clean_t, re.IGNORECASE):
        return True
    return False

def is_non_prose_metadata_block(b: Tuple[float, float, float, float], page, text: str, page_num: int) -> bool:
    """
    Stage 2: Strict Conjunction Metadata Exclusion Filter (GEOMETRY AND CONTENT).
    Identifies publisher sidebars, affiliations, DOIs, and correspondence blocks
    so they are completely excluded from paragraph counters.
    """
    w = float(page.rect.width)
    h = float(page.rect.height)
    clean_t = text.strip()
    if not clean_t:
        return True

    x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
    block_w = x1 - x0
    block_h = y1 - y0

    # Condition C: Explicit Metadata Header
    if EXPLICIT_METADATA_HEADER_REGEX.search(clean_t):
        return True

    # Condition B: Extreme Aspect Ratio Banners
    # Vertical margin date/license banner (e.g. BMJ date banner: width <= 0.028 * W, height >= 0.06 * H)
    if block_w <= (0.028 * w) and block_h >= (0.06 * h):
        return True
    # Horizontal micro-running DOI/tag banner
    if block_h <= (0.016 * h) and len(clean_t) < 65 and re.search(r'doi|https?://|vol|issue|issn', clean_t, re.IGNORECASE):
        return True

    # Condition A: Dynamic Sidebar Conjunction (GEOMETRY AND CONTENT) on Pages 1-2
    if page_num <= 2:
        is_sidebar_geometry = (x0 >= (0.56 * w)) and (block_w <= (0.35 * w))
        if is_sidebar_geometry and METADATA_CONTENT_REGEX.search(clean_t):
            return True

        # Left-margin correspondence/author block (e.g. BMJ left margin notes: x1 <= 0.30 * W)
        is_left_margin_geometry = (x1 <= (0.30 * w)) and (block_w <= (0.28 * w))
        if is_left_margin_geometry and METADATA_CONTENT_REGEX.search(clean_t) and not is_structured_header_line(clean_t):
            return True

    return False

def extract_raw_page_lines(page, textpage=None, page_num: int = 1) -> List[Dict[str, Any]]:
    """
    Stage 1: Extract individual text lines with dynamic gutter cleaving.
    Splits right margin text from main prose lines on Pages 1-2 before baseline merging.
    """
    d = page.get_text("dict", textpage=textpage)
    raw_lines = []
    w = float(page.rect.width)
    
    right_gutter_min = 0.77 * w
    right_gutter_max = 0.82 * w

    for b in d.get("blocks", []):
        if "lines" not in b:
            continue
        for l in b["lines"]:
            spans = l.get("spans", [])
            valid_spans = [s for s in spans if s.get("text", "").strip()]
            if not valid_spans:
                continue
            
            # Filter gutter noise glyphs on Pages 1-2 (e.g. OCR vertical line speckles / artifacts)
            if page_num <= 2:
                filtered_spans = []
                for s in valid_spans:
                    st = s["text"].strip()
                    sx0 = s["bbox"][0]
                    if right_gutter_min <= sx0 <= right_gutter_max and len(st) <= 2 and not st.isalnum():
                        continue
                    if right_gutter_min <= sx0 <= right_gutter_max and len(st) == 1 and st.isdigit():
                        continue
                    filtered_spans.append(s)
                valid_spans = filtered_spans
                if not valid_spans:
                    continue

            # Right margin cleaving on Pages 1-2 (split main column from right sidebar at x >= 0.78 * w)
            if page_num <= 2:
                main_spans_right = [s for s in valid_spans if s["bbox"][2] <= (0.805 * w)]
                sidebar_spans_right = [s for s in valid_spans if s["bbox"][0] >= (0.780 * w)]
                if main_spans_right and sidebar_spans_right and (sidebar_spans_right[0]["bbox"][0] - main_spans_right[-1]["bbox"][2]) >= 4.0:
                    t_main = " ".join(s["text"].strip() for s in main_spans_right).strip()
                    if t_main:
                        raw_lines.append({
                            "text": t_main,
                            "bbox": [
                                min(s["bbox"][0] for s in main_spans_right),
                                min(s["bbox"][1] for s in main_spans_right),
                                max(s["bbox"][2] for s in main_spans_right),
                                max(s["bbox"][3] for s in main_spans_right)
                            ],
                            "spans": main_spans_right
                        })
                    t_side = " ".join(s["text"].strip() for s in sidebar_spans_right).strip()
                    if t_side:
                        raw_lines.append({
                            "text": t_side,
                            "bbox": [
                                min(s["bbox"][0] for s in sidebar_spans_right),
                                min(s["bbox"][1] for s in sidebar_spans_right),
                                max(s["bbox"][2] for s in sidebar_spans_right),
                                max(s["bbox"][3] for s in sidebar_spans_right)
                            ],
                            "spans": sidebar_spans_right
                        })
                    continue

            line_text = " ".join(s["text"].strip() for s in valid_spans)
            x0 = min(s["bbox"][0] for s in valid_spans)
            y0 = min(s["bbox"][1] for s in valid_spans)
            x1 = max(s["bbox"][2] for s in valid_spans)
            y1 = max(s["bbox"][3] for s in valid_spans)
            
            # Drop pure punctuation noise lines
            alnum = re.sub(r'[^a-zA-Z0-9]', '', line_text)
            if len(alnum) == 0 and len(line_text) <= 3:
                continue
                
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
            
    start_x = int(w * 0.40)
    end_x = int(w * 0.60)
    band = coverage[start_x:end_x]
    if not band:
        return width * 0.5, False
        
    min_cov = min(band)
    threshold = max(min_cov, 1)
    
    # 1. Clear / near-empty vertical gutter detection
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
        
    if best_start is not None and best_len >= 8 and min_cov <= 3:
        split_x = best_start + (best_len / 2.0)
        if 0.40 * width <= split_x <= 0.60 * width:
            left_count = sum(1 for l in body_lines if l["bbox"][2] < split_x)
            right_count = sum(1 for l in body_lines if l["bbox"][0] > split_x)
            straddle_count = sum(1 for l in body_lines if l["bbox"][0] < split_x - 20 and l["bbox"][2] > split_x + 20)
            if left_count >= 8 and right_count >= 8 and straddle_count <= 3:
                return split_x, True

    # 2. Valley detector for pages with wide cross-column tables or minor OCR bleed
    best_x = None
    best_ratio = 999.0
    for x in range(start_x + 5, end_x - 5):
        left_peak = max(coverage[max(0, x-60):max(1, x-10)])
        right_peak = max(coverage[min(w-1, x+10):min(w, x+60)])
        valley = sum(coverage[x-2:x+3]) / 5.0
        if left_peak >= 12 and right_peak >= 12:
            ratio = valley / min(left_peak, right_peak)
            if ratio < 0.65 and ratio < best_ratio:
                best_ratio = ratio
                best_x = x
    if best_x is not None:
        if 0.40 * width <= best_x <= 0.60 * width:
            left_count = sum(1 for l in body_lines if l["bbox"][2] < best_x)
            right_count = sum(1 for l in body_lines if l["bbox"][0] > best_x)
            straddle_count = sum(1 for l in body_lines if l["bbox"][0] < best_x - 20 and l["bbox"][2] > best_x + 20)
            if left_count >= 8 and right_count >= 8 and straddle_count <= 3:
                return float(best_x), True
            
    return width * 0.5, False

def extract_clean_page_lines(page, textpage=None, page_num: int = 1) -> List[Dict[str, Any]]:
    """Extract individual text lines with exact bounding boxes, accurately isolating sidebars from main columns."""
    raw_lines = extract_raw_page_lines(page, textpage=textpage, page_num=page_num)
    width = float(page.rect.width)
    height = float(page.rect.height)
    
    # Check if page has an indented left margin layout (e.g. BMJ where main body starts at x >= 0.18 * W)
    prose_x0s = [l["bbox"][0] for l in raw_lines if (l["bbox"][2] - l["bbox"][0]) >= (0.30 * width)]
    has_left_sidebar_layout = (len(prose_x0s) >= 5 and sorted(prose_x0s)[len(prose_x0s) // 5] >= (0.18 * width))

    non_sidebar_lines = []
    sidebar_lines = []
    
    for l in raw_lines:
        x0, y0, x1, y1 = l["bbox"]
        line_w = x1 - x0
        if page_num <= 2 and x0 >= (0.77 * width) and line_w <= (0.24 * width) and METADATA_CONTENT_REGEX.search(l["text"]):
            sidebar_lines.append({"text": l["text"], "bbox": l["bbox"], "col": 3, "spans": l.get("spans", [])})
        elif page_num <= 2 and has_left_sidebar_layout and x1 <= (0.24 * width) and line_w <= (0.22 * width) and METADATA_CONTENT_REGEX.search(l["text"]) and not is_structured_header_line(l["text"]):
            sidebar_lines.append({"text": l["text"], "bbox": l["bbox"], "col": 4, "spans": l.get("spans", [])})
        else:
            non_sidebar_lines.append(l)
            
    split_x, is_two_col = detect_page_column_split(non_sidebar_lines, width, height)
    
    unmerged_lines = []
    for l in non_sidebar_lines:
        valid_spans = l.get("spans", [])
        if not is_two_col or not valid_spans:
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
            
    unmerged_lines.extend(sidebar_lines)
    
    # Merge horizontal line fragments within each column that share the same baseline
    merged_lines = []
    target_cols = [0, 1, 2, 3, 4]
    for target_col in target_cols:
        col_subset = [l for l in unmerged_lines if l["col"] == target_col]
        if not col_subset:
            continue
        col_subset.sort(key=lambda item: (round(item["bbox"][1] / 3.0), item["bbox"][0]))
        curr_row = [col_subset[0]]
        for item in col_subset[1:]:
            h_gap = item["bbox"][0] - curr_row[-1]["bbox"][2]
            if abs(item["bbox"][1] - curr_row[-1]["bbox"][1]) <= 3.5 and h_gap <= 6.0:
                curr_row.append(item)
            else:
                curr_row.sort(key=lambda r: r["bbox"][0])
                r_text = clean_ocr_text(" ".join(r["text"] for r in curr_row))
                r_text = re.sub(r'[\s\|\.\-]{3,}$', '', r_text).strip()
                if r_text:
                    merged_lines.append({
                        "text": r_text,
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
            r_text = clean_ocr_text(" ".join(r["text"] for r in curr_row))
            r_text = re.sub(r'[\s\|\.\-]{3,}$', '', r_text).strip()
            if r_text:
                merged_lines.append({
                    "text": r_text,
                    "bbox": [
                        min(r["bbox"][0] for r in curr_row),
                        min(r["bbox"][1] for r in curr_row),
                        max(r["bbox"][2] for r in curr_row),
                        max(r["bbox"][3] for r in curr_row)
                    ],
                    "col": target_col
                })
            
    return merged_lines

def cluster_column_lines(lines: List[Dict[str, Any]], max_vgap: float = 14.0, page_width: float = 612.0) -> List[Any]:
    """
    Stage 3: Spacing- and Indentation-Bounded Cohesive Clustering.
    Clusters lines within a column into cohesive paragraphs, respecting structured subheadings,
    inter-paragraph leading gaps, and paragraph indentations.
    """
    if not lines:
        return []
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    x0_values = sorted([l["bbox"][0] for l in lines])
    col_left_margin = x0_values[len(x0_values) // 5]
    
    # Calculate median line height/leading for dynamic gap thresholds
    heights = [(l["bbox"][3] - l["bbox"][1]) for l in lines if (l["bbox"][3] - l["bbox"][1]) > 4.0]
    median_h = sorted(heights)[len(heights) // 2] if heights else 10.0
    paragraph_gap_threshold = max(max_vgap, 1.45 * median_h)
    
    clusters = []
    curr = [lines[0]]
    
    for l in lines[1:]:
        prev = curr[-1]
        vgap = l["bbox"][1] - prev["bbox"][3]
        prev_text = prev["text"].strip()
        curr_text = l["text"].strip()
        
        is_break = False
        # 1. Structured header or main section title line always starts a new cluster
        if is_structured_header_line(curr_text, prev_text):
            is_break = True
        elif detect_section_header(curr_text):
            is_break = True
        # 2. Substantial vertical leading gap with sentence-terminal punctuation
        elif vgap > paragraph_gap_threshold and re.search(r'[\.\?!:]["\'\]\)]*$', prev_text):
            is_break = True
        elif vgap > (max_vgap * 1.5):
            is_break = True
        # 3. Standard paragraph indentation with preceding sentence termination
        elif (l["bbox"][0] - col_left_margin) >= (0.015 * page_width) and re.search(r'[\.\?!:]["\'\]\)]*$', prev_text):
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

def decompose_page_into_blocks(page, textpage=None, page_num: int = 1) -> List[Any]:
    """Deconstructs page lines into strictly column-isolated blocks in true academic reading order."""
    lines = extract_clean_page_lines(page, textpage=textpage, page_num=page_num)
    if not lines:
        return page.get_text("blocks", textpage=textpage) if textpage else page.get_text("blocks")
        
    width = float(page.rect.width)
    height = float(page.rect.height)
    
    col1_lines = [l for l in lines if l["col"] == 1]
    col2_lines = [l for l in lines if l["col"] == 2]
    full_lines = [l for l in lines if l["col"] == 0]
    side3_lines = [l for l in lines if l["col"] == 3]
    side4_lines = [l for l in lines if l["col"] == 4]
    
    is_two_column = len(col1_lines) >= 4 and len(col2_lines) >= 4
    result_blocks = []
    if is_two_column:
        top_full = cluster_column_lines([l for l in full_lines if l["bbox"][3] < height * 0.35], max_vgap=18.0, page_width=width)
        col1_blocks = cluster_column_lines(col1_lines, max_vgap=14.0, page_width=width)
        col2_blocks = cluster_column_lines(col2_lines, max_vgap=14.0, page_width=width)
        bot_full = cluster_column_lines([l for l in full_lines if l["bbox"][1] >= height * 0.35], max_vgap=18.0, page_width=width)
        result_blocks = top_full + col1_blocks + col2_blocks + bot_full
    else:
        result_blocks = cluster_column_lines(full_lines, max_vgap=14.0, page_width=width)
        
    # Append isolated sidebar blocks after main prose
    if side4_lines:
        result_blocks.extend(cluster_column_lines(side4_lines, max_vgap=14.0, page_width=width))
    if side3_lines:
        result_blocks.extend(cluster_column_lines(side3_lines, max_vgap=14.0, page_width=width))
        
    return result_blocks

def order_page_blocks(raw_blocks, page) -> List[Any]:
    """Sort blocks into true column-based reading order while filtering out junk margin blocks."""
    clean_blocks = []
    for b in raw_blocks:
        t = b[4].strip()
        if not t or is_junk_block(b, page, t):
            continue
        clean_blocks.append((b, t))
        
    return clean_blocks

def parse_and_index_pdf(pdf_path: str) -> IndexedDocument:
    """
    Ingest a medical research PDF and index each paragraph with high-precision bounding box coordinates.
    Employs the 3-stage pre-counter exclusion and cleaving pipeline to guarantee contiguous numbering.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
    filename = os.path.basename(pdf_path)
    doc = pymupdf.open(pdf_path)
    
    current_section = "Header"
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
    
    active_table_anchor = None
    active_table_page = 0
    
    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        
        if is_scanned_pdf and has_tessdata:
            try:
                tp = page.get_textpage_ocr(tessdata=tessdata_dir, dpi=200, full=True)
                page_text = tp.extractText()
                raw_blocks = decompose_page_into_blocks(page, textpage=tp, page_num=page_num)
            except Exception as e:
                print(f"[Indexer] Warning: OCR failed on page {page_num}: {e}")
                page_text = page.get_text("text")
                raw_blocks = decompose_page_into_blocks(page, page_num=page_num)
        else:
            page_text = page.get_text("text")
            raw_blocks = decompose_page_into_blocks(page, page_num=page_num)

        full_text_accumulator.append(page_text)
        
        blocks = order_page_blocks(raw_blocks, page)
        for b, block_text in blocks:
            lines = [l.strip() for l in block_text.split('\n') if l.strip()]
            for l_idx, line in enumerate(lines[:5]):
                detected = detect_section_header(line, current_section, page_num=page_num)
                if not detected and current_section == "Header":
                    clean_u = line.strip().strip(':').strip('.').strip('#').strip().upper()
                    if clean_u == 'ABSTRACT' or clean_u == 'SUMMARY' or is_structured_header_line(line):
                        detected = 'Abstract'
                if detected:
                    current_section = detected
                    active_table_anchor = None
                    if len(lines) == 1:
                        block_text = ""
                    elif l_idx == 0:
                        block_text = "\n".join(lines[1:]).strip()
                    break
            
            if not block_text:
                continue
            
            # Clean OCR bullet glyph artifacts within block text
            block_text = clean_ocr_text(block_text)
            block_text = re.sub(r'[\s\|\.\-]{3,}$', '', block_text).strip()
            if not block_text:
                continue

            if current_section == "Header":
                # Front matter preceding abstract/intro belongs to [Doc_Header]
                continue

            # Stage 2 Pre-Counter Gate: Check for non-prose metadata (sidebars, affiliations, DOIs, correspondence)
            if is_non_prose_metadata_block(b, page, block_text, page_num):
                # Metadata blocks do NOT consume a paragraph index; they are recorded as metadata items
                meta_anchor_id = f"[{current_section}, Meta p{page_num}_{int(b[1])}]"
                anchor_meta = CoordinateAnchor(
                    anchor_id=meta_anchor_id,
                    section=current_section,
                    item_type="metadata",
                    index=0,
                    text=block_text,
                    page_number=page_num,
                    page_width=float(page.rect.width),
                    page_height=float(page.rect.height),
                    bbox=[float(b[0]), float(b[1]), float(b[2]), float(b[3])]
                )
                indexed_doc.anchor_metadata[meta_anchor_id] = anchor_meta
                continue
            
            is_narrative = bool(re.search(
                r'^(?:Fig(?:ure)?|Table)\s*\d+\s+(?:shows?|presents?|displays?|depicts?|illustrates?|demonstrates?|compares?|indicates?|reveals?|summarizes?|lists?|reports?|provides?|plots?|evaluates?)\b',
                block_text, re.IGNORECASE
            ))
            
            fig_match = re.match(r'^(?:Fig(?:ure)?\.?|FIG\.?)\s*(\d+[A-Za-z]?)', block_text, re.IGNORECASE)
            table_match = re.match(r'^(?:Table)\s*(\d+[A-Za-z]?)', block_text, re.IGNORECASE)
            
            if fig_match and not is_narrative:
                active_table_anchor = None
                item_type = "fig"
                num_str = fig_match.group(1)
                digits = re.findall(r'\d+', num_str)
                idx_num = int(digits[0]) if digits else 1
                anchor_id = f"[{current_section}, Fig {num_str}]"
            elif table_match and not is_narrative:
                item_type = "table"
                num_str = table_match.group(1)
                digits = re.findall(r'\d+', num_str)
                idx_num = int(digits[0]) if digits else 1
                anchor_id = f"[{current_section}, Table {num_str}]"
                active_table_anchor = anchor_id
                active_table_page = page_num
            else:
                def is_table_content_block(text: str) -> bool:
                    t = text.strip()
                    if not t:
                        return False
                    # 1. Abbreviation glossary (e.g. 'Hcy, homocysteine; BMI, body mass index;')
                    if re.search(r'\b[A-Z0-9]{2,}\s*,\s*[^;]+;\s*[A-Z0-9]{2,}\s*,', t):
                        return True
                    # 2. Footnote or statistical note header
                    if re.match(r'^(?:(?:\*{1,3}|†|‡|§)?\s*p\s*[<>=]|Note:|Abbreviations?:|Footnotes?:)', t, re.IGNORECASE):
                        return True
                    # 3. Dense tabular layout (short lines, high numeric/symbol content)
                    lines_in_block = [l.strip() for l in t.splitlines() if l.strip()]
                    if len(lines_in_block) >= 3:
                        wpl = len(t.split()) / len(lines_in_block)
                        if wpl <= 4.5:
                            return True
                    return False

                if active_table_anchor and (page_num <= active_table_page + 1) and is_table_content_block(block_text):
                    t_meta = indexed_doc.anchor_metadata.get(active_table_anchor)
                    if t_meta:
                        t_meta.bbox[0] = min(t_meta.bbox[0], float(b[0]))
                        t_meta.bbox[1] = min(t_meta.bbox[1], float(b[1]))
                        t_meta.bbox[2] = max(t_meta.bbox[2], float(b[2]))
                        t_meta.bbox[3] = max(t_meta.bbox[3], float(b[3]))
                        indexed_doc.all_anchors[active_table_anchor] = (
                            indexed_doc.all_anchors.get(active_table_anchor, "") + "\n" + block_text
                        ).strip()
                    continue

                active_table_anchor = None
                item_type = "para"
                if current_section not in section_para_counters:
                    section_para_counters[current_section] = 0
                section_para_counters[current_section] += 1
                idx_num = section_para_counters[current_section]
                anchor_id = f"[{current_section}, Para {idx_num}]"
                
            anchor = CoordinateAnchor(
                anchor_id=anchor_id,
                section=current_section,
                item_type=item_type,
                index=idx_num,
                text=block_text,
                page_number=page_num,
                page_width=float(page.rect.width),
                page_height=float(page.rect.height),
                bbox=[float(b[0]), float(b[1]), float(b[2]), float(b[3])]
            )
            
            indexed_doc.all_anchors[anchor_id] = block_text
            indexed_doc.anchor_metadata[anchor_id] = anchor
            if current_section not in indexed_doc.sections:
                indexed_doc.sections[current_section] = []
            indexed_doc.sections[current_section].append(anchor)

    # Overflow stitching for sentences cut across physical page breaks
    for p_idx in range(len(doc) - 1):
        p_curr = p_idx + 1
        p_next = p_idx + 2
        anchors_on_curr = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == p_curr and a.item_type == "para"]
        if not anchors_on_curr:
            continue
        last_para = anchors_on_curr[-1]
        t = last_para.text.strip()
        if not re.search(r'[\.\?!:]["\'\]\)]*$', t) and len(t) > 60:
            anchors_on_next = [a for a in indexed_doc.anchor_metadata.values() if a.page_number == p_next and a.item_type == "para"]
            if anchors_on_next:
                first_next_para = anchors_on_next[0]
                t_next = first_next_para.text.strip()
                if t_next and t_next[0].islower():
                    last_para.overflow_page = p_next
                    last_para.overflow_bbox = first_next_para.bbox
                    
    indexed_doc.raw_text = "\n\n".join(full_text_accumulator)
    doc.close()
    return indexed_doc
