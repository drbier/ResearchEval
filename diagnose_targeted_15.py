"""
diagnose_targeted_15.py — Targeted Diagnostic for Hybrid Page 1 & Cross-Column Bleeds
Evaluates the 15 previously failed papers against the updated indexer and deep audit invariants.
"""

import os
import sys
import json
import time
from typing import List, Dict, Any

from audit_indexer_deep import audit_single_document
from src.ingestion.indexer import parse_and_index_pdf, IndexedDocument

BASELINE_REPORT_PATH = "data/deep_audit_patched_digital.json"

def get_target_papers() -> List[Dict[str, Any]]:
    with open(BASELINE_REPORT_PATH, "r", encoding="utf-8") as f:
        d = json.load(f)

    # 1. All 8 papers with Page 1 cross-column bleeds
    p1_papers = []
    for p in d["results"]:
        p1 = [v for v in p.get("violations", []) if v["type"] == "CROSS_COLUMN_BBOX_BLEED" and v.get("page") == 1]
        if p1:
            p1_papers.append(p)

    # 2. Additional failed papers with cross-column bleeds
    other_bleed_papers = [
        p for p in d["results"] 
        if p not in p1_papers and p.get("anomaly_counts", {}).get("cross_column_bleeds", 0) > 0
    ]

    selected = p1_papers + other_bleed_papers[:(15 - len(p1_papers))]
    return selected

def run_targeted_diagnostic():
    targets = get_target_papers()
    print("=" * 110)
    print(f"TARGETED DIAGNOSTIC: 15 PREVIOUSLY FAILED PAPERS (Hybrid Page 1 & Cross-Column Bleed Verification)")
    print("=" * 110)

    summary_rows = []
    total_old_p1 = 0
    total_new_p1 = 0
    total_old_bleeds = 0
    total_new_bleeds = 0

    for idx, prev in enumerate(targets):
        pdf_path = prev["path"]
        fname = prev["filename"]
        safe_fname = fname.encode("ascii", errors="replace").decode("ascii")

        old_p1_bleeds = len([v for v in prev.get("violations", []) if v["type"] == "CROSS_COLUMN_BBOX_BLEED" and v.get("page") == 1])
        old_total_bleeds = prev.get("anomaly_counts", {}).get("cross_column_bleeds", 0)
        old_crit = prev.get("has_critical_failure", False)

        total_old_p1 += old_p1_bleeds
        total_old_bleeds += old_total_bleeds

        t0 = time.time()
        audit_res = audit_single_document(pdf_path)
        elapsed = time.time() - t0

        new_p1_bleeds = len([v for v in audit_res.get("violations", []) if v["type"] == "CROSS_COLUMN_BBOX_BLEED" and v.get("page") == 1])
        new_total_bleeds = audit_res.get("anomaly_counts", {}).get("cross_column_bleeds", 0)
        new_crit = audit_res.get("has_critical_failure", False)

        total_new_p1 += new_p1_bleeds
        total_new_bleeds += new_total_bleeds

        # Check Page 1 anchor distribution directly
        p1_anchors = []
        try:
            indexed = parse_and_index_pdf(pdf_path)
            p1_anchors = [a for a in indexed.anchor_metadata.values() if a.page_number == 1 and a.anchor_id != "[Doc_Header]"]
        except Exception:
            pass

        p1_top_full = [a for a in p1_anchors if a.bbox[1] <= 450 and (a.bbox[2] - a.bbox[0]) > (a.page_width * 0.55)]
        p1_cols = [a for a in p1_anchors if (a.bbox[2] - a.bbox[0]) <= (a.page_width * 0.55)]

        row = {
            "idx": idx + 1,
            "filename": safe_fname[:50],
            "pages": audit_res.get("page_count", 0),
            "anchors": audit_res.get("total_anchors", 0),
            "old_p1": old_p1_bleeds,
            "new_p1": new_p1_bleeds,
            "old_bleeds": old_total_bleeds,
            "new_bleeds": new_total_bleeds,
            "old_crit": "FAIL" if old_crit else "PASS",
            "new_crit": "FAIL" if new_crit else "PASS",
            "p1_top_count": len(p1_top_full),
            "p1_col_count": len(p1_cols),
            "violations": audit_res.get("violations", [])
        }
        summary_rows.append(row)

        p1_status = f"{old_p1_bleeds} -> {new_p1_bleeds}"
        tot_status = f"{old_total_bleeds} -> {new_total_bleeds}"
        crit_status = f"{row['old_crit']} -> {row['new_crit']}"

        print(f"[{idx+1:2d}/15] {safe_fname[:55]:<55} | P1: {p1_status:<7} | Bleeds: {tot_status:<7} | Crit: {crit_status:<11} ({elapsed:.1f}s)")

    print("\n" + "=" * 110)
    print("DETAILED RESULTS TABLE")
    print("=" * 110)
    header = f"{'#':<3} | {'Paper Title':<45} | {'P1 Bleed':<10} | {'Tot Bleed':<10} | {'P1 Top/Col':<10} | {'Status':<10}"
    print(header)
    print("-" * 110)
    for r in summary_rows:
        p1_str = f"{r['old_p1']} -> {r['new_p1']}"
        tot_str = f"{r['old_bleeds']} -> {r['new_bleeds']}"
        tc_str = f"{r['p1_top_count']} / {r['p1_col_count']}"
        st_str = f"{r['old_crit']}->{r['new_crit']}"
        print(f"{r['idx']:<3} | {r['filename']:<45} | {p1_str:<10} | {tot_str:<10} | {tc_str:<10} | {st_str:<10}")
    print("-" * 110)
    print(f"TOTALS: Page 1 Bleeds: {total_old_p1} -> {total_new_p1} (Reduction: {total_old_p1 - total_new_p1}) | Total Bleeds: {total_old_bleeds} -> {total_new_bleeds}")
    print("=" * 110)

    # Detailed drill-down for any remaining violations
    remaining_with_violations = [r for r in summary_rows if r["violations"]]
    if remaining_with_violations:
        print("\nDRILL-DOWN: REMAINING VIOLATIONS IN TARGETED PAPERS:")
        for r in remaining_with_violations:
            print(f"\n* Paper #{r['idx']}: {r['filename']}")
            for v in r["violations"]:
                v_type = v.get("type")
                sev = v.get("severity")
                pg = v.get("page", "-")
                det = v.get("details", v.get("text_excerpt", ""))
                safe_det = det.encode("ascii", errors="replace").decode("ascii")[:100]
                print(f"    - [{sev}] {v_type} (p.{pg}): {safe_det}")

if __name__ == "__main__":
    run_targeted_diagnostic()
