import re
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field

class SanitizationResult(BaseModel):
    cleaned_markdown: str
    stripped_disclaimers: List[str] = Field(default_factory=list)
    stripped_fillers: List[str] = Field(default_factory=list)
    verified_anchors: List[str] = Field(default_factory=list)
    invalid_anchors: List[str] = Field(default_factory=list)
    is_valid: bool = True

DISCLAIMER_PATTERNS = [
    r'(?i)(?:please\s+note\s+that\s+)?this\s+(?:analysis|synthesis|document|summary|evaluation)\s+is\s+(?:intended\s+)?for\s+informational\s+(?:and\s+educational\s+)?purposes\s+only[^\n]*',
    r'(?i)not\s+intended\s+to\s+(?:provide|replace)\s+(?:medical|clinical)\s+advice[^\n]*',
    r'(?i)consult\s+(?:a|your)\s+(?:qualified\s+)?(?:physician|healthcare\s+provider|doctor)[^\n]*',
    r'(?i)disclaimer:\s*[^\n]+'
]

FILLER_PATTERNS = [
    r'(?i)^(?:i\s+hope\s+this\s+helps|let\s+me\s+know\s+if\s+you\s+need|feel\s+free\s+to\s+ask|as\s+an\s+ai|certainly|here\s+is\s+(?:the|your)\s+analysis)[^\n]*\n?',
    r'(?i)\n(?:i\s+hope\s+this\s+helps|let\s+me\s+know\s+if\s+you\s+need|feel\s+free\s+to\s+ask|as\s+an\s+ai|thank\s+you)[^\n]*$'
]

def clean_latex_math(text: str) -> str:
    """Clean LaTeX math markup, dollar-sign wrappers, and macros into clean clinical Unicode text."""
    if not text:
        return ""
    # 1. Replace \text{...}, \mathrm{...}, \mathbf{...} with inner content
    text = re.sub(r'\\(?:text|mathrm|mathbf|mathit|mathsf)\{([^}]+)\}', r'\1', text)

    # 2. Convert common superscripts: ^+ -> ⁺, ^- -> ⁻, ^2 -> ², ^3 -> ³, etc.
    sup_map = {
        r'\^\+': '⁺',
        r'\^-': '⁻',
        r'\^2': '²',
        r'\^3': '³',
        r'\^0': '⁰',
        r'\^1': '¹',
        r'\^4': '⁴',
    }
    for pat, sup in sup_map.items():
        text = re.sub(pat, sup, text)

    # 3. Common Greek letters and mathematical symbols
    greek_and_math = [
        (r'\\alpha\b', 'α'),
        (r'\\beta\b', 'β'),
        (r'\\gamma\b', 'γ'),
        (r'\\delta\b', 'δ'),
        (r'\\epsilon\b', 'ε'),
        (r'\\theta\b', 'θ'),
        (r'\\lambda\b', 'λ'),
        (r'\\mu\b', 'μ'),
        (r'\\pi\b', 'π'),
        (r'\\sigma\b', 'σ'),
        (r'\\tau\b', 'τ'),
        (r'\\phi\b', 'φ'),
        (r'\\chi\b', 'χ'),
        (r'\\omega\b', 'ω'),
        (r'\\pm\b', '±'),
        (r'\\times\b', '×'),
        (r'\\geq?\b', '≥'),
        (r'\\leq?\b', '≤'),
        (r'\\neq\b', '≠'),
        (r'\\approx\b', '≈'),
        (r'\\infty\b', '∞'),
        (r'\\rightarrow\b', '→'),
        (r'\\to\b', '→'),
    ]
    for macro, sym in greek_and_math:
        text = re.sub(macro, sym, text)

    # 4. Strip $...$ and $$...$$ LaTeX math wrappers
    text = re.sub(r'\$\$([^\$]+?)\$\$', r'\1', text)
    text = re.sub(r'\$([^\$\n]+?)\$', r'\1', text)

    # 5. Clean any residual escaped backslashes in front of words
    text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)

    return text

def sanitize_and_verify_appraisal(markdown_text: str, valid_anchor_set: Dict[str, str]) -> SanitizationResult:
    """Strip disclaimers, conversational pleasantries, and verify coordinate anchors."""
    cleaned = markdown_text
    stripped_disclaimers: List[str] = []
    stripped_fillers: List[str] = []
    
    # 1. Clean LaTeX Math & Format Artifacts
    cleaned = clean_latex_math(cleaned)
    
    # 1. Strip Disclaimers
    for pat in DISCLAIMER_PATTERNS:
        matches = re.findall(pat, cleaned)
        if matches:
            stripped_disclaimers.extend(matches)
            cleaned = re.sub(pat, '', cleaned)
            
    # 2. Strip Conversational Fillers
    for pat in FILLER_PATTERNS:
        matches = re.findall(pat, cleaned)
        if matches:
            stripped_fillers.extend(matches)
            cleaned = re.sub(pat, '', cleaned)
            
    # 3. Strip Raw Rule Identifier Codes (e.g. {R_ROB2_...} or [R_ROB2_...])
    cleaned = re.sub(r'\s*\{R_[A-Z0-9_]+\}', '', cleaned)
    cleaned = re.sub(r'\s*\[R_[A-Z0-9_]+\]', '', cleaned)

    # 4. Normalize any model variations like "Paragraph" / "Paragraphs" / "paragraph" -> "Para" inside bracket citations
    cleaned = re.sub(r'(\[[^\]]*?\b)Paragraphs?\b', r'\1Para', cleaned, flags=re.IGNORECASE)

    # 5. Expand combined multi-paragraph citations: [Methods, Para 1, 13] -> [Methods, Para 1] [Methods, Para 13]
    def expand_combined_paras(match):
        sec = match.group(1).strip()
        nums = [n.strip() for n in match.group(2).split(',') if n.strip()]
        return " ".join(f"[{sec}, Para {n}]" for n in nums)
    cleaned = re.sub(r'\[([A-Za-z\s&]+?),\s*Para\s+(\d+(?:\s*,\s*\d+)+)\]', expand_combined_paras, cleaned, flags=re.IGNORECASE)

    # Clean up empty lines created by removals
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    
    # 3. Coordinate Anchor Audit
    # Match coordinate blocks, supporting compound and multi-paragraph citations
    bracket_pattern = r'\[([^\]]*?\b(?:Doc_Header|Para|Table|Fig)\b[^\]]*?)\]'
    extracted_blocks = re.findall(bracket_pattern, cleaned, re.IGNORECASE)
    
    extracted_anchors: List[str] = []
    for block in extracted_blocks:
        trimmed = block.strip()
        if trimmed.lower() == 'doc_header':
            extracted_anchors.append('[Doc_Header]')
            continue
        if ';' in trimmed:
            parts = [p.strip() for p in trimmed.split(';') if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r',\s*(?=[A-Za-z\s]+,\s*(?:Para|Table|Fig))', trimmed) if p.strip()]
        for p in parts:
            extracted_anchors.append(f"[{p}]")
    
    verified: List[str] = []
    invalid: List[str] = []
    
    for anc in extracted_anchors:
        if anc in valid_anchor_set:
            if anc not in verified:
                verified.append(anc)
            continue
            
        # Fallback for multi-para or ranges: [Section, Para X, Y] -> test [Section, Para X]
        m = re.match(r'\[\s*([A-Za-z\s&]+?)\s*,\s*Para\s+(\d+)', anc, re.IGNORECASE)
        if m:
            fallback = f"[{m.group(1).strip()}, Para {m.group(2)}]"
            if fallback in valid_anchor_set:
                if anc not in verified:
                    verified.append(anc)
                continue
                
        # Table or Fig fallback
        tf = re.match(r'\[\s*([A-Za-z\s&]+?)\s*,\s*(Table|Fig)\s*(\d+)', anc, re.IGNORECASE)
        if tf:
            item_type = tf.group(2).capitalize()
            fallback = f"[{tf.group(1).strip()}, {item_type} {tf.group(3)}]"
            if fallback in valid_anchor_set:
                if anc not in verified:
                    verified.append(anc)
                continue

        if anc not in invalid:
            invalid.append(anc)
                
    return SanitizationResult(
        cleaned_markdown=cleaned,
        stripped_disclaimers=stripped_disclaimers,
        stripped_fillers=stripped_fillers,
        verified_anchors=verified,
        invalid_anchors=invalid,
        is_valid=(len(invalid) == 0)
    )

if __name__ == "__main__":
    test_md = """# Clinical Trial Appraisal
## Executive Appraisal & Baseline Rigor
The trial randomized 500 patients [Doc_Header] and baseline characteristics were balanced [Methods, Para 2].
Non-inferiority was achieved [Results, Table 1].
An unreferenced claim was made [Nonexistent, Para 99].

Disclaimer: This synthesis is for informational purposes only and does not constitute medical advice.
I hope this helps! Let me know if you need any other analysis."""

    valid_anchors = {
        "[Doc_Header]": "Header info",
        "[Methods, Para 2]": "Methods paragraph 2",
        "[Results, Table 1]": "Table 1 data"
    }

    res = sanitize_and_verify_appraisal(test_md, valid_anchors)
    print("Cleaned text:\n", res.cleaned_markdown)
    print("\nStripped disclaimers:", res.stripped_disclaimers)
    print("Stripped fillers:", res.stripped_fillers)
    print("Verified anchors:", res.verified_anchors)
    print("Invalid anchors:", res.invalid_anchors)

