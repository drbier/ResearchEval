import os
import re
import statistics
import pymupdf
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel

MATH_OPERATORS = set("+-*/=<>≤≥±%~^≠≈#&|°")

def compute_numeric_symbol_density(text: str) -> float:
    if not text:
        return 0.0
    count = sum(1 for c in text if c.isdigit() or c in MATH_OPERATORS)
    return count / max(1, len(text))

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
    r'NCT\d{8}|Author\s+Affiliations?|\*Members\s+listed|Contributed\s+equally|Cite\s+this\s+as|'
    r'Received(?:\s*:|\s+\d+)|Accepted(?:\s*:|\s+\d+)|Revised(?:\s*:|\s+\d+))\b',
    re.IGNORECASE
)

EXPLICIT_METADATA_HEADER_REGEX = re.compile(
    r'^(?:Correspondence:?|Correspondence\s+to:?|Cite\s+this\s+as:?|Keywords:?|\*Corresponding\s+author:?|'
    r'Open\s+Access\.\s+[©\u00a9]|Copyright\s+[©\u00a9]|Author\s+contributions:?|Competing\s+interests:?)',
    re.IGNORECASE
)

RUN_IN_DISCUSSION_REGEX = re.compile(
    r'^(Strengths\s+and\s+Limitations(?:\s+of\s+(?:this|the)\s+study)?|Limitations(?:\s+of\s+(?:this|the)\s+study)?|'
    r'Principal\s+Findings|Comments?|Interpretation)(?:[:\.\-\u2013\u2014\s]+)([A-Z].*)',
    re.IGNORECASE
)

DISCLOSURE_BANNER_REGEX = re.compile(
    r'\b(?:Authors?[\'’]?\s+Disclosures?|Disclosure\s+information\s+provided\s+by\s+authors|'
    r'Conflicts?\s+of\s+interest\s+disclosures?|Financial\s+[Dd]isclosures?|'
    r'Author\s+contributions?|Data\s+sharing\s+statement|'
    r'Role\s+of\s+the\s+(?:Sponsors?|Funders?)|Additional\s+Contributions?|'
    r'Disclaimer|Funding/Support)\b',
    re.IGNORECASE
)

CALLOUT_BOX_REGEX = re.compile(
    r'\b(?:Key\s+Objective|Knowledge\s+Generated|Key\s+Points|Research\s+in\s+context|'
    r'Evidence\s+before\s+this\s+study|Added\s+value\s+of\s+this\s+study|What\s+is\s+already\s+known|'
    r'What\s+this\s+study\s+adds|Summary\s+for\s+Patients|Box\s*\d+\b)',
    re.IGNORECASE
)

FIGURE_LEGEND_REGEX = re.compile(
    r'\b(?:confocal\s+microscopy|immunofluorescence|staining\s+of|MFI\s+of|'
    r'Normalised\s+Enrichment\s+Score|Enrichment\s+Score\s*\(NES\)|Enrichment\s+plot|'
    r'Kaplan-Meier|Forest\s+plot|Western\s+blot|Flow\s+cytometr|'
    r'Flow\s+diagram|Trial\s+selection|Consort\s+diagram|PRISMA|'
    r'Boxplots?\s+representing|Graphical\s+representation\s+of|'
    r'Representative\s+(?:confocal|microscopy|images?|photomicrographs?))\b',
    re.IGNORECASE
)

def clean_ocr_text(text: str) -> str:
    """Standardize ligatures, special whitespace, OCR hyphens, font-encoding artifact question marks, and bullet glyphs."""
    if not text:
        return ""
    text = text.replace('\xa0', ' ')
    # Normalize unicode whitespace (thin space, hair space, zero-width space, etc.)
    text = re.sub(r'[\u2000-\u200B\u202F\u205F]', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)

    # Repair font-encoding question mark artifacts (from Latin-1 / WinAnsi fallback)
    # 1. Number range hyphens: '0.87?1.04' -> '0.87-1.04'
    text = re.sub(r'(?<=\d)\s*\?\s*(?=\d)', '-', text)
    # 2. P-value comparisons: 'p?<?0.001' or 'p ? < 0.001' -> 'p < 0.001'
    text = re.sub(r'([pP])\s*\?\s*<\s*\?\s*', r'\1 < ', text)
    text = re.sub(r'([pP])\s*\?\s*([<>=≤≥])\s*\??\s*', r'\1 \2 ', text)
    # 3. Statistical Chi / I-squared: '(? 2 96.06' or '(?\n2 96.06' -> '(Chi² 96.06'
    text = re.sub(r'\(\s*\?\s*\n?\s*2\s+(?=\d)', '(Chi² ', text)
    text = re.sub(r'(?<=\bheterogeneity\s)\(\s*\?\s*\n?\s*2', '(Chi²', text, flags=re.IGNORECASE)
    # 4. Quoted terms with internal hyphens: '?leave?one?out?' -> '"leave-one-out"'
    text = re.sub(r'\?([a-zA-Z0-9]+)\?([a-zA-Z0-9]+)\?([a-zA-Z0-9]+)\?', r'"\1-\2-\3"', text)
    text = re.sub(r'\?([a-zA-Z0-9]+)\?([a-zA-Z0-9]+)\?', r'"\1-\2"', text)
    text = re.sub(r'(?<=\s)\?([a-zA-Z0-9\-_]+)\?(?=[\s,\.;:\)])', r'"\1"', text)

    # Clean OCR pseudo-bullet glyph artifacts (e.g. 'e Dietary uptake...' -> '• Dietary uptake...')
    text = re.sub(r'(?m)^[eo•·\-]\s+(?=[A-Z])', '• ', text)
    # Clean isolated single-character OCR noise artifacts on their own line within blocks (e.g. stray edge margin specks)
    text = re.sub(r'(?m)^\s*[a-zA-Z&@=><§©]\s*$\n?', '', text)
    return text.strip()

def detect_section_header(line: str, current_section: Optional[str] = None, page_num: int = 1) -> Optional[str]:
    """Identify common medical manuscript section headers, supporting numbered prefixes and subsections."""
    clean_line = line.strip().strip(':').strip('.').strip('#').strip()
    if not clean_line or clean_line[0].islower():
        return None
        
    # Check for run-in discussion header if line starts with commentary/limitation keywords
    if len(clean_line) > 55:
        m_runin = RUN_IN_DISCUSSION_REGEX.match(clean_line)
        if m_runin and current_section in ('Results', 'Methods', 'Introduction'):
            return 'Discussion'
        return None
    
    # Strip markdown formatting
    clean_line = re.sub(r'^[#*_\s]+', '', clean_line).strip()
    clean_line = re.sub(r'[:#*_\s\.]+$', '', clean_line).strip()
    
    # Strip leading numbers/roman numerals and section prefixes: e.g. "1.", "1 ", "1.1", "3 ", "Section 3:"
    stripped = re.sub(r'^(?:(?:section|part|sec)\.?\s*)?(?:[0-9]+(?:\.[0-9]+)*|[IVXLCDM]+)[\.\s\-:\)]+\s*', '', clean_line, flags=re.IGNORECASE).strip()
    upper = stripped.upper()

    # Constraint 2: On Page 1, 'INTERPRETATION' is part of structured abstracts (e.g. The Lancet), not body Discussion
    if page_num == 1 and upper in ('INTERPRETATION', 'INTERPRETATIONS'):
        return None
    
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
        'COMMENT': 'Discussion',
        'COMMENTS': 'Discussion',
        'INTERPRETATION': 'Discussion',
        'LIMITATIONS': 'Discussion',
        'LIMITATION': 'Discussion',
        'STRENGTHS AND LIMITATIONS': 'Discussion',
        'STRENGTHS AND LIMITATIONS OF THIS STUDY': 'Discussion',
        'STRENGTHS AND LIMITATIONS OF THE STUDY': 'Discussion',
        'PRINCIPAL FINDINGS': 'Discussion',
        'MAIN FINDINGS': 'Discussion',
        'CONCLUSIONS': 'Conclusions',
        'CONCLUSION': 'Conclusions',
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
    if re.match(r'^(?:DI\s*ASION|D[I1L][SCU\s]{1,5}[SIO0N]{2,5})$', upper):
        return 'Discussion'
    for key in section_map:
        if upper == key:
            return section_map[key]
        if upper.startswith(key + ' ') or upper.startswith(key + ':') or upper.startswith(key + ' -') or upper.startswith(key + '.'):
            # Guard: do not match inline citations or sentence fragments like "appendix p 18", "appendix (pp 7-10)", "methods see online"
            if key in ('APPENDIX', 'SUPPLEMENTARY', 'SUPPLEMENTARY APPENDIX', 'SUPPLEMENTARY MATERIAL'):
                if re.match(r'^(?:APPENDIX|SUPPLEMENTARY(?:\s+(?:APPENDIX|MATERIAL))?)\s*(?:[0-9A-Z]+|TABLE|FIGURE)?$', upper):
                    return section_map[key]
                continue
            # Guard: do not match running prose clauses like "results and test combination regimens" or "methods used in this trial"
            if key in ('RESULTS', 'METHODS', 'INTRODUCTION', 'DISCUSSION') and not upper.startswith('RESULTS AND DISCUSSION'):
                remainder = upper[len(key):].strip(' :.-')
                if re.match(r'^(?:AND|FROM|IN|OF|USED|SHOWED|WERE|FOR|WITH)\s+[A-Z0-9]+\s+[A-Z0-9]+', remainder):
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
    if re.search(r'The\s+New\s+England\s+Journal\s+of\s+Medicine\s+is\s+produced\s+by\s+NEJM\s+Group', clean_t, re.IGNORECASE):
        return True
    if re.search(r'Please\s+cite\s+this\s+article\s+in\s+press\s+as', clean_t, re.IGNORECASE):
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

    # Condition B2: Recurring Wiley/Cochrane and Academic Running Headers at extreme upper bounds (y1 <= 0.10 * H or y0 <= 0.08 * H)
    if y1 <= (0.10 * h) and (
        re.search(r'Cochrane\s+(?:Library|Database\s+of\s+Systematic\s+Reviews)', clean_t, re.IGNORECASE)
        or re.search(r'\b(?:JAMA(?:\s+Network(?:\s+Open)?)?|The\s+Lancet|BMJ(?:\s+Open)?|New\s+England\s+Journal|NEJM)\b', clean_t, re.IGNORECASE)
        or re.search(r'\b(?:Nutrients|Cancers|Int\.?\s*J\.?\s*Mol\.?\s*Sci|Biomedicines|Cells|Diagnostics|Antioxidants)\s+\d{4},\s+\d+', clean_t, re.IGNORECASE)
        or re.search(r'https?://(?:dx\.)?doi\.org/|\b\d+\s+of\s+\d+\b', clean_t, re.IGNORECASE)
    ):
        return True

    # Condition B3: Browser print timestamps and web print URLs at extreme top margin (y0 <= 0.045 * H)
    if y0 <= (0.045 * h) and (
        re.match(r'^\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}\s+(?:AM|PM)', clean_t)
        or re.search(r'https?://[a-z0-9\.\-]+/(?:pmc/articles|doi)/', clean_t, re.IGNORECASE)
    ):
        return True

    # Condition F: Abbreviation Glossary Filter (multiple definition pairs: "KEY: Definition; KEY: ...")
    abbr_defs = re.findall(r'\b[A-Z0-9]{2,}\s*[:=]\s*[^;]+(?:;|\n|$)', clean_t)
    if len(abbr_defs) >= 3 or (len(abbr_defs) >= 2 and re.search(r'\b(?:Abbreviations?|Glossary|Acronyms?)\b', clean_t, re.IGNORECASE)):
        return True
    if re.search(r'\b[A-Z0-9]{2,}\s*:\s*[A-Z][a-z]+;\s*[A-Z0-9]{2,}\s*:\s*[A-Z]', clean_t):
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

        # Bottom affiliation/correspondence footnote on Page 1 (y0 >= 0.72 * H)
        if page_num == 1 and y0 >= (0.72 * h) and METADATA_CONTENT_REGEX.search(clean_t) and not is_structured_header_line(clean_t):
            return True

    # Condition D: Creative Commons / Open Access / Recurring Wiley-Cochrane license & copyright footers (y0 >= 0.78 * H)
    if y0 >= (0.78 * h) and (
        re.search(r'Creative\s+Commons|Attribution\s+License|creativecommons\.org|licenses/by', clean_t, re.IGNORECASE)
        or re.search(r'Copyright\s+(?:\([Cc]\)|\u00a9|\d{4})|(?:\([Cc]\)|\u00a9)\s*(?:\d{4}\s*)?(?:The\s+Authors?|John\s+Wiley|Wiley|Elsevier|Springer|BMJ|MDPI|Oxford|Lancet)', clean_t, re.IGNORECASE)
        or re.search(r'\b(?:Published\s+by\s+John\s+Wiley|Wiley\s+Periodicals|All\s+rights\s+reserved|\(Review\)\s+Copyright)\b', clean_t, re.IGNORECASE)
        or re.search(r'https?://(?:dx\.)?doi\.org/|Downloaded\s+from\s+[a-z0-9\.\-]+', clean_t, re.IGNORECASE)
        or re.search(r'^[0-9\s\.\(\)\-\u2013/:]*doi:10\.\d{4,9}/[^\n]*$', clean_t, re.IGNORECASE)
    ):
        return True

    # Condition E: Author disclosures and end-matter banners
    if DISCLOSURE_BANNER_REGEX.search(clean_t):
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
            
            # Filter gutter and extreme-margin noise glyphs (e.g. OCR vertical line speckles / artifacts)
            filtered_spans = []
            for s_idx, s in enumerate(valid_spans):
                st = s["text"].strip()
                sx0 = s["bbox"][0]
                sx1 = s["bbox"][2]
                if page_num <= 2:
                    if right_gutter_min <= sx0 <= right_gutter_max and len(st) <= 2 and not st.isalnum():
                        continue
                    if right_gutter_min <= sx0 <= right_gutter_max and len(st) == 1 and st.isdigit():
                        continue
                # Filter extreme margin scanner artifacts (x >= 0.93*w or x <= 0.05*w)
                if sx0 >= 0.93 * w and len(st) <= 2:
                    prev_s = valid_spans[s_idx - 1] if s_idx > 0 else None
                    if not prev_s or (sx0 - prev_s["bbox"][2]) >= 10.0:
                        continue
                if sx1 <= 0.05 * w and len(st) <= 2:
                    next_s = valid_spans[s_idx + 1] if s_idx + 1 < len(valid_spans) else None
                    if not next_s or (next_s["bbox"][0] - sx1) >= 10.0:
                        continue
                filtered_spans.append(s)
            valid_spans = filtered_spans
            if not valid_spans:
                continue

            # Right margin cleaving on Page 1 (split main column from right sidebar at x >= 0.78 * w only if sidebar contains metadata)
            if page_num == 1:
                main_spans_right = [s for s in valid_spans if s["bbox"][2] <= (0.805 * w)]
                sidebar_spans_right = [s for s in valid_spans if s["bbox"][0] >= (0.780 * w)]
                if main_spans_right and sidebar_spans_right:
                    gutter = sidebar_spans_right[0]["bbox"][0] - main_spans_right[-1]["bbox"][2]
                    t_side_test = " ".join(s["text"].strip() for s in sidebar_spans_right).strip()
                    if gutter >= 12.0 and METADATA_CONTENT_REGEX.search(t_side_test):
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
                        if t_side_test:
                            raw_lines.append({
                                "text": t_side_test,
                                "bbox": [
                                    min(s["bbox"][0] for s in sidebar_spans_right),
                                    min(s["bbox"][1] for s in sidebar_spans_right),
                                    max(s["bbox"][2] for s in sidebar_spans_right),
                                    max(s["bbox"][3] for s in sidebar_spans_right)
                                ],
                                "spans": sidebar_spans_right
                            })
                        continue

            # Stage 1B: OCR Gutter Cleaving (split lines straddling the center gutter due to OCR artifacts or wide gutter gaps)
            x0 = min(s["bbox"][0] for s in valid_spans)
            x1 = max(s["bbox"][2] for s in valid_spans)
            if x0 < 0.40 * w and x1 > 0.60 * w:
                cleaved = False
                for i in range(len(valid_spans)):
                    mid_x = (valid_spans[i]["bbox"][0] + valid_spans[i]["bbox"][2]) / 2.0
                    st = valid_spans[i]["text"].strip()
                    if 0.42 * w <= mid_x <= 0.58 * w:
                        # Case A: OCR delimiter glyph
                        if re.match(r'^[_—–\|\-]+$', st) or st in ('I', 'l', ':', ';', '|'):
                            left_s = valid_spans[:i]
                            right_s = valid_spans[i+1:]
                            if left_s and right_s:
                                t_l = " ".join(s["text"].strip() for s in left_s)
                                t_r = " ".join(s["text"].strip() for s in right_s)
                                if len(t_l) >= 2 and len(t_r) >= 2:
                                    raw_lines.append({
                                        "text": t_l,
                                        "bbox": [min(s["bbox"][0] for s in left_s), min(s["bbox"][1] for s in left_s), max(s["bbox"][2] for s in left_s), max(s["bbox"][3] for s in left_s)],
                                        "spans": left_s
                                    })
                                    raw_lines.append({
                                        "text": t_r,
                                        "bbox": [min(s["bbox"][0] for s in right_s), min(s["bbox"][1] for s in right_s), max(s["bbox"][2] for s in right_s), max(s["bbox"][3] for s in right_s)],
                                        "spans": right_s
                                    })
                                    cleaved = True
                                    break
                        # Case B: wide gutter gap between columns
                        elif i < len(valid_spans) - 1:
                            gap = valid_spans[i+1]["bbox"][0] - valid_spans[i]["bbox"][2]
                            next_is_header = valid_spans[i+1]["text"].strip().upper() in (
                                'COMMENT', 'COMMENTS', 'DISCUSSION', 'RESULTS', 'METHODS', 
                                'INTRODUCTION', 'CONCLUSIONS', 'CONCLUSION'
                            )
                            if gap >= 10.0 or (next_is_header and gap >= 6.0):
                                left_s = valid_spans[:i+1]
                                right_s = valid_spans[i+1:]
                                t_l = " ".join(s["text"].strip() for s in left_s)
                                t_r = " ".join(s["text"].strip() for s in right_s)
                                if len(t_l) >= 2 and len(t_r) >= 2:
                                    raw_lines.append({
                                        "text": t_l,
                                        "bbox": [min(s["bbox"][0] for s in left_s), min(s["bbox"][1] for s in left_s), max(s["bbox"][2] for s in left_s), max(s["bbox"][3] for s in left_s)],
                                        "spans": left_s
                                    })
                                    raw_lines.append({
                                        "text": t_r,
                                        "bbox": [min(s["bbox"][0] for s in right_s), min(s["bbox"][1] for s in right_s), max(s["bbox"][2] for s in right_s), max(s["bbox"][3] for s in right_s)],
                                        "spans": right_s
                                    })
                                    cleaved = True
                                    break
                if cleaved:
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

TABLE_FOOTNOTE_REGEX = re.compile(
    r'(?:^|\b)(?:Abbreviations?|Footnotes?|Notes?|Source|Data\s+source|Legend)\s*:|'
    r'\b(?:Multivariable\s+analysis|Cox\s+regression|Asterisk|Boldface\s+indicates|hazard\s+models?|'
    r'relative\s+risk|odds\s+ratio|confidence\s+interval|comorbidity\s+index|primary\s+care\s+visits|'
    r'standard\s+deviation|interquartile\s+range|'
    r'values\s+are\s+(?:n|means?|percentages?|medians?|hazard\s+ratios?|numbers?)|'
    r'hazard\s+ratios?\s*\((?:95%\s*)?confidence\s+intervals?\)|'
    r'percentages?\s+may\s+not|proportional\s+hazards\s+estimate|'
    r'GRADE\s+evidence|Risk\s+difference|'
    r'HIGH:\s*There\s+is\s+complete\s+confidence|'
    r'MODERATE:\s*There\s+is\s+moderate\s+confidence|'
    r'LOW:\s*There\s+is\s+low\s+confidence|'
    r'(?:further\s+)?adjusted\s+(?:\([^\)]+\)\s+)?for\b|'
    r'adjusted\s+for\s+(?:age|sex|gender|covariates|confounders|multivariable)|'
    r'Models?\s+\d+:\s*(?:Adjusted|Unadjusted)|'
    r'Per\s+\d+\s*(?:h|unit|sd|increment)\s+increment|'
    r'(?:Quartile|Quintile|Tertile|Decile)\s+ranges?:|'
    r'Quartile\s+\d+\s*:)\b',
    re.IGNORECASE
)

ABBREVIATION_GLOSSARY_REGEX = re.compile(
    r'\b[A-Z0-9]{2,}\s*,\s*[^;]+;\s*[A-Z0-9]{2,}\s*,',
    re.IGNORECASE
)

def is_footnote_or_table_banner(line_text: str, bbox: Any, height: float, width: float) -> bool:
    """
    Explicitly differentiates localized full-width table footnotes/banners from genuine full-width body paragraphs.
    Table footnotes: localized in lower 65% (y > 0.35 * H) or immediate header banner (y < 0.15 * H),
    or containing abbreviation glossaries, statistical models, footnote markers (*, †, ‡, §, ¶, ¢, £).
    Genuine full-width body paragraphs: running prose sentences without footnote markers.
    """
    t = line_text.strip()
    if not t:
        return False
    
    # Guard: Substantive numbered subsection headers are body prose, never table footnotes
    if re.match(r'^\d+\.\d+\.?\s+[A-Z]', t):
        return False

    # 1. Direct content match for table footnotes / abbreviations
    if TABLE_FOOTNOTE_REGEX.search(t) or ABBREVIATION_GLOSSARY_REGEX.search(t):
        return True
        
    # 2. Footnote symbols with statistical or explanatory content
    if re.match(r'^(?:[\*\†\‡\§\¶\¢\£\#\+\d\-\u2022]\s*)+(?:p\s*[<>=]|\b(?:HR|OR|RR|CI)\b|Model|Adjusted|Values|Data|Asterisk|N\s*[=:]|Quartile|Cancer\s+mortality)', t, re.IGNORECASE):
        return True

    # 3. Geometric location + localized notation: mid-page or bottom with statistical symbols
    y0 = bbox[1]
    if y0 >= height * 0.35 and (
        re.search(r'[\*\†\‡\§\¶\¢\£]|p\s*[<>=]|hazard\s+ratios?|confidence\s+intervals?|Quartile\s+ranges?|adjusted\s+for', t, re.IGNORECASE)
        or re.search(r'\b(?:CI|HR|OR|RR)\b', t)
    ):
        return True
        
    # 4. Running publisher watermarks/citations
    if len(t) < 140 and re.search(r'\b(?:Downloaded\s+from|Please\s+cite\s+this|The\s+New\s+England\s+Journal\s+of\s+Medicine|BMJ\s+Open|JAMA\s+Network)\b', t, re.IGNORECASE):
        return True
        
    return False

def _calculate_column_split_for_lines(lines_to_check: List[Dict[str, Any]], width: float, min_lines_per_col: int = 8) -> Tuple[float, bool]:
    """Calculate the column split x-coordinate and two-column status for a given set of lines."""
    w = int(width)
    if not lines_to_check:
        return width * 0.5, False

    coverage = [0] * w
    for l in lines_to_check:
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
        
    if best_start is not None and best_len >= 8 and min_cov <= 5:
        split_x = best_start + (best_len / 2.0)
        if 0.40 * width <= split_x <= 0.60 * width:
            left_count = sum(1 for l in lines_to_check if l["bbox"][2] < split_x)
            right_count = sum(1 for l in lines_to_check if l["bbox"][0] > split_x)
            straddle_count = sum(1 for l in lines_to_check if l["bbox"][0] < split_x - 20 and l["bbox"][2] > split_x + 20)
            max_allowed_straddle = max(3, int(0.12 * (left_count + right_count)))
            wide_straddles = sum(
                1 for l in lines_to_check 
                if l["bbox"][0] < split_x - 30 and l["bbox"][2] > split_x + 30 
                and (l["bbox"][2] - l["bbox"][0]) >= 0.45 * width 
                and len(l.get("text", "").strip()) >= 20
            )
            if wide_straddles < 5 and left_count >= min_lines_per_col and right_count >= min_lines_per_col and straddle_count <= max_allowed_straddle:
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
            left_count = sum(1 for l in lines_to_check if l["bbox"][2] < best_x)
            right_count = sum(1 for l in lines_to_check if l["bbox"][0] > best_x)
            straddle_count = sum(1 for l in lines_to_check if l["bbox"][0] < best_x - 20 and l["bbox"][2] > best_x + 20)
            max_allowed_straddle = max(3, int(0.12 * (left_count + right_count)))
            wide_straddles = sum(
                1 for l in lines_to_check 
                if l["bbox"][0] < best_x - 30 and l["bbox"][2] > best_x + 30 
                and (l["bbox"][2] - l["bbox"][0]) >= 0.45 * width 
                and len(l.get("text", "").strip()) >= 20
            )
            if wide_straddles < 5 and left_count >= min_lines_per_col and right_count >= min_lines_per_col and straddle_count <= max_allowed_straddle:
                return float(best_x), True
            
    return width * 0.5, False

def detect_page_column_split(lines: List[Dict[str, Any]], width: float, height: float, page_num: int = 1) -> Tuple[float, bool]:
    w = int(width)
    body_lines = [
        l for l in lines 
        if l["bbox"][1] >= height * 0.06 and l["bbox"][3] <= height * 0.94 and len(l.get("text", "").strip()) >= 2
    ]
    if not body_lines:
        return width * 0.5, False
        
    # Footnote-Insulation: isolate localized table footnotes/banners so they do not distort column detection
    prose_body_lines = [
        l for l in body_lines 
        if not is_footnote_or_table_banner(l.get("text", ""), l["bbox"], height, width)
    ]
    analysis_lines = prose_body_lines if len(prose_body_lines) >= 8 else body_lines

    # Zone-Aware Two-Column Split for Page 1:
    # Separate Page 1 into an Upper Zone (y <= 0.50H) and Lower Zone (y > 0.45H)
    # before executing the column boundary calculation. In academic layouts (Nature, Elsevier, JAMA),
    # the Upper Zone contains a full-width title/abstract while the Lower Zone is dual-column.
    # Evaluating candidate Lower Zone thresholds (0.45H, 0.50H, 0.55H, 0.58H) prevents the full-width
    # abstract straddles from suppressing the column split calculation.
    if page_num == 1:
        for y_cut in (0.45, 0.50, 0.55, 0.58):
            lower_lines = [l for l in analysis_lines if l["bbox"][1] > height * y_cut]
            if len(lower_lines) >= 8:
                split_x, is_two_col = _calculate_column_split_for_lines(lower_lines, width, min_lines_per_col=4)
                if is_two_col:
                    return split_x, True

    split_x, is_two_col = _calculate_column_split_for_lines(analysis_lines, width, min_lines_per_col=8)
    if not is_two_col and page_num >= 3:
        # Generalized Zone-Aware Two-Column Split for Interior / End-Matter pages:
        # Many medical journals (JAMA, The Lancet, NEJM) feature 2-column Discussion or Results
        # in the upper half of the page (y <= 0.55H), while the lower half contains 3-column boxed author
        # affiliations, disclosures, or references spanning across the gutter.
        for y_top_cut in (0.50, 0.52, 0.55):
            upper_lines = [l for l in analysis_lines if l["bbox"][3] <= height * y_top_cut and len(l.get("text", "").strip()) >= 2]
            if len(upper_lines) >= 8:
                u_split_x, u_two_col = _calculate_column_split_for_lines(upper_lines, width, min_lines_per_col=4)
                if u_two_col:
                    lower_wide_prose = sum(
                        1 for l in analysis_lines 
                        if l["bbox"][1] > height * y_top_cut 
                        and (l["bbox"][2] - l["bbox"][0]) >= 0.45 * width 
                        and len(l.get("text", "").strip()) >= 20
                    )
                    if lower_wide_prose < 3:
                        return u_split_x, True
    return split_x, is_two_col

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
            
    split_x, is_two_col = detect_page_column_split(non_sidebar_lines, width, height, page_num=page_num)
    
    unmerged_lines = []
    for l in non_sidebar_lines:
        valid_spans = l.get("spans", [])
        line_t = l.get("text", "")
        # Localized full-width table footnotes/banners route directly to full_lines (col=0) without cleaving
        if is_two_col and is_footnote_or_table_banner(line_t, l["bbox"], height, width):
            unmerged_lines.append({
                "text": line_t,
                "bbox": l["bbox"],
                "col": 0
            })
            continue

        if not is_two_col or not valid_spans:
            unmerged_lines.append({
                "text": line_t,
                "bbox": l["bbox"],
                "col": 0
            })
            continue
            
        # Filter noise glyphs that straddle split_x
        filtered_spans = [
            s for s in valid_spans 
            if not (s["bbox"][0] <= split_x <= s["bbox"][2] and len(s["text"].strip()) <= 2)
        ]
        left_spans = [s for s in filtered_spans if s["bbox"][2] <= split_x]
        right_spans = [s for s in filtered_spans if s["bbox"][0] >= split_x]
        
        # Gutter cleaving: cleave across split_x when text spans exist on both sides of the column split
        if left_spans and right_spans and (min(s["bbox"][0] for s in right_spans) - max(s["bbox"][2] for s in left_spans)) >= 2.0:
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
            prev_h = curr_row[-1]["bbox"][3] - curr_row[-1]["bbox"][1]
            item_h = item["bbox"][3] - item["bbox"][1]
            # Standard prose fragments allow h_gap <= 6.0; header/title fragments with enlarged font (h >= 13.0) or short words allow h_gap <= 20.0
            max_allowed_h_gap = 20.0 if (prev_h >= 13.0 or item_h >= 13.0 or len(curr_row[-1]["text"]) <= 3 or len(item["text"]) <= 5) else 6.0
            if abs(item["bbox"][1] - curr_row[-1]["bbox"][1]) <= 3.5 and h_gap <= max_allowed_h_gap:
                curr_row.append(item)
            else:
                curr_row.sort(key=lambda r: r["bbox"][0])
                r_text = clean_ocr_text(" ".join(r["text"] for r in curr_row))
                r_text = re.sub(r'[\s\|\.\-]{3,}$', '', r_text).strip()
                if re.match(r'^Di\s*asion$', r_text, re.IGNORECASE):
                    r_text = "Discussion"
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
            if re.match(r'^Di\s*asion$', r_text, re.IGNORECASE):
                r_text = "Discussion"
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
        # 1. Structured header, subsection heading (e.g. 2.1, 2.2), or main section title line always starts a new cluster
        if is_structured_header_line(curr_text, prev_text):
            is_break = True
        elif detect_section_header(curr_text):
            is_break = True
        elif re.match(r'^\d+\.\d+(?:\.\d+)*\.?\s+[A-Z]', curr_text):
            is_break = True
        # 2. Substantial vertical leading gap with sentence-terminal punctuation
        elif (vgap > max(7.5, 0.85 * median_h) or (l["bbox"][3] - l["bbox"][1] >= 1.35 * median_h and vgap > 5.0)) and re.search(r'[\.\?!:]["\'\]\)]*$', prev_text):
            is_break = True
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

        # Compute font profile and vertical leading (vgap) for block
        span_sizes = [float(s.get("size", 10.0)) for item in cl for s in item.get("spans", []) if s.get("text", "").strip()]
        dom_font = float(statistics.median(span_sizes)) if span_sizes else 10.0

        vgaps = []
        if len(cl) > 1:
            for idx in range(len(cl) - 1):
                vg = abs(cl[idx+1]["bbox"][3] - cl[idx]["bbox"][3])
                if vg > 0.5:
                    vgaps.append(vg)
        med_vgap = float(statistics.median(vgaps)) if vgaps else 0.0

        metrics = {
            "font_size": dom_font,
            "vgap": med_vgap,
            "line_count": len(cl)
        }
        blocks.append((x0, y0, x1, y1, block_text, 0, 0, metrics))
        
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
        top_split_y = height * 0.70 if page_num == 1 else height * 0.35
        top_full = cluster_column_lines([l for l in full_lines if l["bbox"][3] <= top_split_y], max_vgap=18.0, page_width=width)
        col1_blocks = cluster_column_lines(col1_lines, max_vgap=14.0, page_width=width)
        col2_blocks = cluster_column_lines(col2_lines, max_vgap=14.0, page_width=width)
        bot_full = cluster_column_lines([l for l in full_lines if l["bbox"][1] > top_split_y], max_vgap=18.0, page_width=width)
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
        if not t:
            continue
        if is_junk_block(b, page, t) and not is_non_prose_metadata_block(b, page, t, 1):
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

    header_lines = []
    for l in page1_text.split('\n'):
        l_str = l.strip()
        if not l_str:
            continue
        clean_u = l_str.strip(':.-# ').upper()
        if clean_u in ('ABSTRACT', 'SUMMARY', '1. INTRODUCTION', 'INTRODUCTION') or is_structured_header_line(l_str):
            break
        header_lines.append(l_str)
        if len(header_lines) >= 15:
            break

    doc_header = "\n".join(header_lines)[:1500] if header_lines else page1_text[:500]
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
        bbox=[30.0, 30.0, float(doc[0].rect.width) - 30.0 if len(doc) > 0 else 560.0, 160.0]
    )
    
    active_table_anchor = None
    active_table_page = 0
    last_para_anchor: Optional[CoordinateAnchor] = None
    
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

        # Determine dominant body font size of the page (for born-digital documents)
        page_body_font = 10.0
        if not is_scanned_pdf:
            try:
                page_dict = page.get_text("dict")
                font_char_counts = {}
                for b_dict in page_dict.get("blocks", []):
                    if "lines" not in b_dict:
                        continue
                    for l_dict in b_dict["lines"]:
                        for s_dict in l_dict.get("spans", []):
                            sz = round(float(s_dict.get("size", 10.0)), 1)
                            t_len = len(s_dict.get("text", "").strip())
                            if t_len > 0:
                                font_char_counts[sz] = font_char_counts.get(sz, 0) + t_len
                if font_char_counts:
                    page_body_font = max(font_char_counts.items(), key=lambda item: item[1])[0]
            except Exception:
                page_body_font = 10.0

        # Invariant 2: Abstract Boundary Enforcement
        # An abstract is strictly confined to Pages 1-2. If prose continues past Page 2
        # in a multi-page document without an explicit header, transition to Introduction.
        # Single-page clinical letters (len(doc) == 1) remain untouched.
        if current_section == "Abstract" and len(doc) > 1 and page_num >= 3:
            current_section = "Introduction"
            active_table_anchor = None

        for b, block_text in blocks:
            metrics = b[7] if len(b) > 7 and isinstance(b[7], dict) else {}
            block_font_size = float(metrics.get("font_size", 10.0))
            block_vgap = float(metrics.get("vgap", 0.0))
            block_line_count = int(metrics.get("line_count", 1))
            lines = [l.strip() for l in block_text.split('\n') if l.strip()]

            # Check for run-in discussion headers (e.g. 'Strengths and Limitations Compared with...')
            if lines and current_section in ('Results', 'Methods', 'Introduction'):
                m_runin = RUN_IN_DISCUSSION_REGEX.match(lines[0])
                if m_runin:
                    # Constraint 2: On Page 1, 'Interpretation' is an abstract conclusion, never a body Discussion transition
                    if page_num == 1 and m_runin.group(1).upper() in ('INTERPRETATION', 'INTERPRETATIONS'):
                        pass
                    else:
                        current_section = 'Discussion'
                        active_table_anchor = None
                        remainder = m_runin.group(2).strip()
                        lines[0] = remainder
                        block_text = "\n".join(lines).strip()

            for l_idx, line in enumerate(lines[:5]):
                detected = detect_section_header(line, current_section, page_num=page_num)
                if not detected and current_section == "Header":
                    clean_u = line.strip().strip(':').strip('.').strip('#').strip().upper()
                    if clean_u == 'ABSTRACT' or clean_u == 'SUMMARY' or is_structured_header_line(line):
                        detected = 'Abstract'
                if detected:
                    if detected != current_section:
                        current_section = detected
                        active_table_anchor = None
                        m_runin = RUN_IN_DISCUSSION_REGEX.match(line)
                        if m_runin and len(lines) == 1:
                            block_text = m_runin.group(2).strip()
                            break
                        elif m_runin and l_idx == 0:
                            lines[0] = m_runin.group(2).strip()
                            block_text = "\n".join(lines).strip()
                            break
                        elif len(lines) == 1:
                            block_text = ""
                        elif l_idx == 0:
                            block_text = "\n".join(lines[1:]).strip()
                        break
                    elif len(lines) == 1:
                        # Standalone repeated section header line
                        block_text = ""
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
            
            # Stage 2 Table Footnote / Legend Gate:
            if current_section != "Abstract" and is_footnote_or_table_banner(block_text, b, float(page.rect.height), float(page.rect.width)):
                meta_anchor_id = f"[{current_section}, TableNote p{page_num}_{int(b[1])}]"
                anchor_meta = CoordinateAnchor(
                    anchor_id=meta_anchor_id,
                    section=current_section,
                    item_type="table",
                    index=0,
                    text=block_text,
                    page_number=page_num,
                    page_width=float(page.rect.width),
                    page_height=float(page.rect.height),
                    bbox=[float(b[0]), float(b[1]), float(b[2]), float(b[3])]
                )
                indexed_doc.anchor_metadata[meta_anchor_id] = anchor_meta
                continue

            first_3_lines = " ".join(lines[:3])
            raw_block_text = b[4] if len(b) > 4 else block_text
            is_narrative = bool(re.search(
                r'\b(?:Fig(?:ure)?|Table)\s*\d+\s+(?:shows?|presents?|displays?|depicts?|illustrates?|demonstrates?|compares?|indicates?|reveals?|summarizes?|lists?|reports?|provides?|plots?|evaluates?)\b',
                first_3_lines, re.IGNORECASE
            ))
            
            fig_match = None
            table_match = None
            table_cont_match = None
            for l in lines[:3]:
                if not fig_match:
                    fig_match = re.match(r'^(?:Fig(?:ure)?\.?|FIG(?:URE)?\.?)\s*(\d+[A-Za-z]?)', l.strip(), re.IGNORECASE)
                if not table_match:
                    table_match = re.match(r'^(?:Table|TABLE)\s*(\d+[A-Za-z]?|[IVXLCDM]+)\b', l.strip())
                if not table_cont_match:
                    table_cont_match = re.match(r'^(?:Table|TABLE)\s*(\d+[A-Za-z]?|[IVXLCDM]+)\s*[\.\:\-\–—]?\s*(?:\(?\s*Cont(?:inued|\.)?\s*\)?|\bcontinued\b)\b', l.strip(), re.IGNORECASE)

            table_title_match = re.search(r'\b(?:Characteristics\s+of\s+\d+|Baseline\s+characteristics|Demographic\s+and\s+clinical\s+characteristics|Patient\s+characteristics|Study\s+characteristics|Characteristics\s+of\s+(?:included\s+)?studies|Summary\s+of\s+findings(?:\s+table)?)\b', first_3_lines, re.IGNORECASE)
            
            # Table continuation detection:
            # 1. Explicit continuation header (e.g. 'Table 2. Cont.')
            # 2. Repeated table number on continuation page matching active_table_anchor
            is_table_continuation = False
            if table_cont_match:
                c_num = table_cont_match.group(1)
                cand_anchor = f"[{current_section}, Table {c_num}]"
                if cand_anchor in indexed_doc.anchor_metadata or active_table_anchor == cand_anchor:
                    active_table_anchor = cand_anchor
                    active_table_page = page_num
                    is_table_continuation = True
            elif table_match and active_table_anchor and page_num > active_table_page:
                num_str = table_match.group(1)
                if active_table_anchor == f"[{current_section}, Table {num_str}]":
                    active_table_page = page_num
                    is_table_continuation = True

            if is_table_continuation:
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

            if fig_match and not is_narrative:
                active_table_anchor = None
                item_type = "fig"
                num_str = fig_match.group(1)
                digits = re.findall(r'\d+', num_str)
                idx_num = int(digits[0]) if digits else 1
                anchor_id = f"[{current_section}, Fig {num_str}]"
            elif (table_match or table_title_match) and not is_narrative:
                item_type = "table"
                if table_match:
                    num_str = table_match.group(1)
                    anchor_id = f"[{current_section}, Table {num_str}]"
                else:
                    anchor_id = f"[{current_section}, Table p{page_num}_{int(b[1])}]"
                active_table_anchor = anchor_id
                active_table_page = page_num
            elif FIGURE_LEGEND_REGEX.search(block_text) or FIGURE_LEGEND_REGEX.search(raw_block_text):
                active_table_anchor = None
                item_type = "fig"
                idx_num = 0
                anchor_id = f"[{current_section}, FigLegend p{page_num}_{int(b[1])}]"
            elif CALLOUT_BOX_REGEX.search(block_text) or CALLOUT_BOX_REGEX.search(raw_block_text) or re.search(r'\b(?:Can\s+a\s+model\s+combining|Key\s+Objective)\b', block_text, re.IGNORECASE):
                active_table_anchor = None
                item_type = "box"
                idx_num = 0
                anchor_id = f"[{current_section}, Box p{page_num}_{int(b[1])}]"
            else:
                def is_table_content_block(text: str) -> bool:
                    t = text.strip()
                    if not t:
                        return False
                    # 1. Abbreviation glossary (e.g. 'Hcy, homocysteine; BMI, body mass index;')
                    if re.search(r'\b[A-Z0-9]{2,}\s*,\s*[^;]+;\s*[A-Z0-9]{2,}\s*,', t):
                        return True
                    # 2. Footnote or statistical note header
                    if re.match(r'^(?:(?:\*{1,3}|†|‡|§)?\s*p\s*[<>=]|Note:|Abbreviations?:|Footnotes?:|Source:)', t, re.IGNORECASE):
                        return True
                    # 3. Dense tabular layout (short lines, high numeric/symbol content)
                    lines_in_block = [l.strip() for l in t.splitlines() if l.strip()]
                    if len(lines_in_block) >= 3:
                        wpl = len(t.split()) / len(lines_in_block)
                        if wpl <= 6.0:
                            return True
                    # 4. Table study rows, regimens, cohort data, or statistical summaries
                    if re.search(r'\b(?:Intermittent:|Continuous:|Induction\s+only|Trial|Study VII|SWOG|ICELAND|Total\s+Cholesterol|HR\s*\(?95%|RR\s*\(?95%|OR\s*\(?95%|p\s*[<>=]|CI\s*[\d\.\-]+)\b', t, re.IGNORECASE):
                        return True
                    if re.search(r'\bHR[†*‡§¶\s]+(?:HR[†*‡§¶\s]+)?95%\s*CI\b', t):
                        return True
                    # 5. Table rows with study author/year tags (e.g. 'Calais da Silva 2009', 'Crook 2012')
                    if re.match(r'^[A-Z][a-zA-Z\s\.\-]+\s*(?:et\s+al\.?\s*)?\(?\d{4}\)?', t) or re.match(r'^[A-Z][a-zA-Z\s\.\-]+\d{4}\b', t):
                        return True
                    # 6. GRADE evidence profiles, Risk of Bias judgment rows, or Certainty ratings
                    if re.search(r'[⨁\u2a01]|(?:Downgraded\s+due\s+to|Certainty\s+of\s+evidence|Risk\s+of\s+bias|Quality\s+assessment)', t, re.IGNORECASE):
                        return True
                    if re.search(r'\b(?:Low|Moderate|High|Critical|Unclear)\s+(?:Low|Moderate|High|Critical|Unclear)\b', t):
                        return True
                    # 7. Continuation markers or repeated table column headers
                    if re.search(r'\b(?:Table|TABLE)\s*\d+.*(?:Cont|continued)\b', t, re.IGNORECASE):
                        return True
                    if re.search(r'\b(?:Bias\s+Due\s+to|Overall\s+Judgment|Exposure\s+Assessment|Missing\s+Data|Selective\s+Reporting)\b', t, re.IGNORECASE):
                        return True
                    # 8. Numeric density & leading compression table indicators
                    density = compute_numeric_symbol_density(t)
                    if density >= 0.18:
                        return True
                    if not is_scanned_pdf and block_vgap > 0 and block_vgap <= (0.85 * block_font_size) and len(lines_in_block) >= 2:
                        return True
                    return False

                if active_table_anchor and (page_num <= active_table_page + 1) and is_table_content_block(block_text):
                    active_table_page = page_num
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

                # Constraint 1: Numeric Density Filter
                # Classify blocks with numeric/symbol density >= 18% AND a negative font differential (or tight leading) as 'table'
                density = compute_numeric_symbol_density(block_text)
                block_w = float(b[2] - b[0])
                is_full_w = block_w >= (0.55 * float(page.rect.width))

                is_dense_numeric_table = (
                    density >= 0.18 and (
                        block_font_size <= page_body_font - 0.5 
                        or (block_vgap > 0 and block_vgap <= 11.0)
                        or (block_vgap > 0 and block_vgap <= 0.95 * block_font_size)
                        or len(lines) >= 3
                    )
                )

                # Constraint 2: Leading Compression Filter (conditionally for born-digital documents)
                # Classify full-width blocks with compressed vertical leading (vgap <= 0.85 * font_size) as 'table'
                is_compressed_leading_table = (
                    not is_scanned_pdf
                    and is_full_w
                    and len(lines) >= 2
                    and block_vgap > 0
                    and block_vgap <= (0.85 * block_font_size)
                    and not is_structured_header_line(lines[0])
                    and not re.match(r'^(?:Conclusions?:|Results?:|Methods?:|Background?:|Introduction:)', lines[0], re.IGNORECASE)
                )

                if current_section != "Abstract" and (is_dense_numeric_table or is_compressed_leading_table):
                    item_type = "table"
                    idx_num = 0
                    anchor_id = f"[{current_section}, Table p{page_num}_{int(b[1])}]"
                    active_table_anchor = anchor_id
                    active_table_page = page_num
                elif current_section in ("References", "Bibliography"):
                    item_type = "ref"
                    if current_section not in section_para_counters:
                        section_para_counters[current_section] = 0
                    section_para_counters[current_section] += 1
                    idx_num = section_para_counters[current_section]
                    anchor_id = f"[{current_section}, Ref {idx_num}]"
                elif current_section in ("Appendix", "Metadata"):
                    item_type = "metadata"
                    if current_section not in section_para_counters:
                        section_para_counters[current_section] = 0
                    section_para_counters[current_section] += 1
                    idx_num = section_para_counters[current_section]
                    anchor_id = f"[{current_section}, Meta {idx_num}]"
                else:
                    item_type = "para"

                    # Check if this paragraph is an overflow continuation of a previous paragraph cut across physical pages
                    if (
                        last_para_anchor
                        and last_para_anchor.section == current_section
                        and page_num > last_para_anchor.page_number
                        and not re.search(r'[\.\?!:]["\'\]\)]*$', last_para_anchor.text.strip())
                        and len(last_para_anchor.text.strip()) > 60
                        and block_text.strip()
                        and block_text.strip()[0].islower()
                        and not last_para_anchor.overflow_page
                    ):
                        last_para_anchor.overflow_page = page_num
                        last_para_anchor.overflow_bbox = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
                        last_para_anchor.text = f"{last_para_anchor.text}\n{block_text}"
                        indexed_doc.all_anchors[last_para_anchor.anchor_id] = last_para_anchor.text
                        continue

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
            if item_type == "para":
                last_para_anchor = anchor

    indexed_doc.raw_text = "\n\n".join(full_text_accumulator)
    doc.close()
    return indexed_doc
