"""
diagnose_remaining_32.py - Comprehensive Multi-Dimensional Diagnostic on the Remaining 32 Failed Manuscripts.

Evaluates:
1. Numeric/Symbol Density Ratio: (count of digits + math operators) / total characters.
2. Font Size Profile: Dominant font size, font family, and differential against page median body font.
3. Vertical Gap (vgap): Median distance between line baselines within the block.
4. Categorizes failures into distinct heuristic dimensions without overfitting.
"""

import os
import sys
import json
import statistics
import pymupdf
import re

MATH_OPERATORS = set("+-*/=<>≤≥±%~^≠≈#&|°")

def compute_numeric_symbol_density(text: str) -> float:
    if not text:
        return 0.0
    count = sum(1 for c in text if c.isdigit() or c in MATH_OPERATORS)
    return count / max(1, len(text))

def analyze_page_fonts(page) -> float:
    """Determine the dominant median body font size of the page."""
    d = page.get_text("dict")
    font_char_counts = {}
    for b in d.get("blocks", []):
        if "lines" not in b:
            continue
        for l in b["lines"]:
            for s in l.get("spans", []):
                sz = round(float(s.get("size", 10.0)), 1)
                t_len = len(s.get("text", "").strip())
                if t_len > 0:
                    font_char_counts[sz] = font_char_counts.get(sz, 0) + t_len
    if not font_char_counts:
        return 10.0
    return max(font_char_counts.items(), key=lambda item: item[1])[0]

def analyze_block_spans(page, target_bbox, excerpt_start: str = ""):
    """Find matching block in page dict and compute font profile and vgap."""
    d = page.get_text("dict")
    best_block = None
    best_overlap = -1.0
    
    tx0, ty0, tx1, ty1 = target_bbox
    
    for b in d.get("blocks", []):
        if "lines" not in b:
            continue
        bx0, by0, bx1, by1 = b["bbox"]
        # Compute intersection over union or vertical overlap
        y_overlap = max(0.0, min(ty1, by1) - max(ty0, by0))
        x_overlap = max(0.0, min(tx1, bx1) - max(tx0, bx0))
        overlap = x_overlap * y_overlap
        if overlap > best_overlap:
            best_overlap = overlap
            best_block = b

    if not best_block:
        # Fallback to closest center
        min_dist = 999999.0
        for b in d.get("blocks", []):
            if "lines" not in b:
                continue
            cy = (b["bbox"][1] + b["bbox"][3]) / 2.0
            t_cy = (ty0 + ty1) / 2.0
            dist = abs(cy - t_cy)
            if dist < min_dist:
                min_dist = dist
                best_block = b

    if not best_block or "lines" not in best_block:
        return {
            "dominant_font_size": 10.0,
            "font_names": ["Unknown"],
            "vgap_median": 0.0,
            "line_count": 1
        }

    # Font analysis
    span_fonts = {}
    font_names = set()
    for l in best_block["lines"]:
        for s in l.get("spans", []):
            sz = round(float(s.get("size", 10.0)), 1)
            fn = s.get("font", "Unknown")
            font_names.add(fn)
            t_len = len(s.get("text", "").strip())
            span_fonts[sz] = span_fonts.get(sz, 0) + t_len

    dominant_font = max(span_fonts.items(), key=lambda item: item[1])[0] if span_fonts else 10.0

    # Vgap analysis (distance between consecutive line baselines)
    lines = best_block["lines"]
    vgaps = []
    if len(lines) > 1:
        for i in range(len(lines) - 1):
            y_curr = lines[i]["bbox"][3]
            y_next = lines[i+1]["bbox"][3]
            diff = abs(y_next - y_curr)
            if diff > 0.5:
                vgaps.append(diff)
    
    vgap_med = round(statistics.median(vgaps), 2) if vgaps else round(best_block["bbox"][3] - best_block["bbox"][1], 2)

    return {
        "dominant_font_size": dominant_font,
        "font_names": list(font_names)[:3],
        "vgap_median": vgap_med,
        "line_count": len(lines)
    }

def run_diagnostic():
    input_path = os.path.join("data", "diagnostic_cohort_66_results.json")
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found.")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    failed_papers = [r for r in data["results"] if r.get("new_crit")]
    print(f"Loaded {len(failed_papers)} remaining failing papers for deep multi-dimensional analysis.\n")

    detailed_anomalies = []

    for p_idx, paper in enumerate(failed_papers, 1):
        path = paper["path"]
        fname = paper["filename"]
        violations = [v for v in paper.get("violations", []) if v.get("severity") == "CRITICAL"]

        if not os.path.exists(path):
            print(f"[{p_idx}/32] File not found: {fname}")
            continue

        try:
            doc = pymupdf.open(path)
        except Exception as e:
            print(f"[{p_idx}/32] Open error: {fname} -> {e}")
            continue

        for v in violations:
            v_type = v.get("type")
            page_no = v.get("page", 1)
            bbox = v.get("bbox", [0.0, 0.0, 0.0, 0.0])
            anchor_id = v.get("anchor_id", "N/A")
            excerpt = v.get("text_excerpt") or v.get("details") or ""

            if page_no > len(doc) or page_no < 1:
                page_no = 1
            page = doc[page_no - 1]
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)

            page_body_font = analyze_page_fonts(page)
            block_metrics = analyze_block_spans(page, bbox, excerpt_start=excerpt[:30])

            density = compute_numeric_symbol_density(excerpt)
            font_size = block_metrics["dominant_font_size"]
            font_diff = round(font_size - page_body_font, 2)
            vgap = block_metrics["vgap_median"]

            # Geometric ratios
            y0 = bbox[1]
            y1 = bbox[3]
            w_box = bbox[2] - bbox[0]
            y0_ratio = round(y0 / max(1.0, page_h), 3)
            y1_ratio = round(y1 / max(1.0, page_h), 3)
            w_ratio = round(w_box / max(1.0, page_w), 3)

            # Heuristic Categorization Dimension
            dimension = "Unclassified"
            if v_type == "MISSING_DISCUSSION_SECTION":
                dimension = "Dim 4: Trapped Section / Alternative Hierarchy"
            elif y0_ratio <= 0.045 or y1_ratio >= 0.96 or (font_size <= 8.0 and (y0_ratio <= 0.06 or y1_ratio >= 0.94)):
                dimension = "Dim 1: Web / Margin Timestamp & Running Artifact"
            elif density >= 0.16 or (density >= 0.10 and block_metrics["line_count"] >= 3 and vgap <= 10.0):
                dimension = "Dim 2: Dense Statistical Matrix / Tabular Grid"
            elif re.search(r'\b[A-Z0-9]{2,}\s*:\s*[A-Z0-9]', excerpt) or re.search(r'\b(?:EC|ER|PR|HER2|DFS|OS|PFS|CI|HR|OR|RR|AUC|ROC)\s*[:=]', excerpt):
                dimension = "Dim 3: Dense Abbreviation Key / Table Footnote"
            elif font_size >= page_body_font + 1.5 or font_size <= page_body_font - 1.5:
                dimension = "Dim 5: Outlier Typography / Heading / Micro-Note"
            elif w_ratio >= 0.65:
                dimension = "Dim 6: Broad Multi-Column Span / Callout Flow"

            detailed_anomalies.append({
                "paper": fname,
                "path": path,
                "violation_type": v_type,
                "anchor_id": anchor_id,
                "page": page_no,
                "bbox": bbox,
                "y0_ratio": y0_ratio,
                "y1_ratio": y1_ratio,
                "w_ratio": w_ratio,
                "excerpt": excerpt[:140],
                "numeric_symbol_density": round(density, 3),
                "dominant_font_size": font_size,
                "page_body_font": page_body_font,
                "font_diff": font_diff,
                "font_names": block_metrics["font_names"],
                "vgap": vgap,
                "line_count": block_metrics["line_count"],
                "dimension": dimension
            })

        doc.close()

    # Generate Markdown Report
    md = []
    md.append("# Remaining 32 Failed Papers: Heuristic Multi-Dimensional Diagnostic\n")
    md.append(f"**Total Failed Papers Analyzed**: {len(failed_papers)}")
    md.append(f"**Total Critical Violations Extracted**: {len(detailed_anomalies)}\n")

    # Group by Dimension
    dimensions = {}
    for a in detailed_anomalies:
        d = a["dimension"]
        if d not in dimensions:
            dimensions[d] = []
        dimensions[d].append(a)

    md.append("## Executive Dimensional Breakdown\n")
    md.append("| Heuristic Dimension | Anomaly Count | Percentage | Key Signal Thresholds |")
    md.append("|---|---|---|---|")
    total_anoms = max(1, len(detailed_anomalies))
    for dim_name in sorted(dimensions.keys()):
        c = len(dimensions[dim_name])
        pct = c / total_anoms * 100
        if "Dim 1" in dim_name:
            signals = "`y0 <= 0.045H` or `y1 >= 0.96H`, `font <= 8.0pt`"
        elif "Dim 2" in dim_name:
            signals = "`density >= 0.16` or (`density >= 0.10` and `vgap <= 10pt`)"
        elif "Dim 3" in dim_name:
            signals = "`[A-Z]{2,}:` Abbr keys, `EC: Clinical stage; ER: ...`"
        elif "Dim 4" in dim_name:
            signals = "Unnumbered Comment / Letter / Trapped Discussion"
        elif "Dim 5" in dim_name:
            signals = "`|font_diff| >= 1.5pt` (Distinct header / note font)"
        else:
            signals = "`w_ratio >= 0.65` across center gutter"
        md.append(f"| **{dim_name}** | {c} | {pct:.1f}% | {signals} |")

    md.append("\n---\n")

    for dim_name in sorted(dimensions.keys()):
        anoms = dimensions[dim_name]
        md.append(f"## {dim_name} ({len(anoms)} anomalies)\n")
        md.append("| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |")
        md.append("|---|---|---|---|---|---|---|")
        for a in anoms:
            p_short = a["paper"][:30] + "..." if len(a["paper"]) > 32 else a["paper"]
            aid = a["anchor_id"]
            pg = a["page"]
            bb = f"[{int(a['bbox'][0])},{int(a['bbox'][1])},{int(a['bbox'][2])},{int(a['bbox'][3])}]"
            dens = f"{a['numeric_symbol_density']*100:.1f}%"
            f_str = f"{a['dominant_font_size']}pt ({a['page_body_font']}pt)"
            vg = f"{a['vgap']}pt"
            exc = repr(a["excerpt"][:55]).replace("|", "/")
            md.append(f"| **{p_short}**<br>`{aid}` | P{pg} | `{bb}` | {dens} | {f_str} | {vg} | {exc} |")
        md.append("\n")

    # Save Markdown and JSON
    md_content = "\n".join(md)
    out_md = os.path.join("data", "diagnostic_remaining_32.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md_content)

    out_json = os.path.join("data", "diagnostic_remaining_32.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(detailed_anomalies, f, indent=2)

    print(f"Diagnostic completed successfully.")
    print(f"Markdown report written to: {out_md}")
    print(f"JSON data written to: {out_json}")

if __name__ == "__main__":
    run_diagnostic()

