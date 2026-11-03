"""
diagnose_failed_cohort_66.py - Targeted Diagnostic on the 66 Failed Papers Cohort.

Validates the impact of:
1. Stateful table continuation tracking across page boundaries.
2. Recurring Wiley/Cochrane full-width running headers and copyright footers routing to Meta.
3. Refined Invariant 2A exempting non-standard document typologies.
4. Wide-straddle guard preventing false 2-column detection on single-column pages with tables.
"""

import os
import sys
import json
import time
from audit_indexer_deep import audit_single_document

def run_diagnostic():
    audit_json_path = os.path.join("data", "deep_indexer_audit_full_385.json")
    if not os.path.exists(audit_json_path):
        print(f"Error: {audit_json_path} not found.")
        return

    with open(audit_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    baseline_crit = [r for r in data["results"] if r.get("has_critical_failure")]
    print(f"Loaded {len(baseline_crit)} baseline critical failure manuscripts from {audit_json_path}.")
    print("=" * 80)
    print(f"{'Paper Name':<45} | {'Old Crit':<8} | {'New Crit':<8} | {'Old Bleed':<9} | {'New Bleed':<9} | {'Status'}")
    print("-" * 80)

    start_time = time.time()
    results = []
    resolved_count = 0
    still_failing = 0
    total_old_bleeds = 0
    total_new_bleeds = 0
    total_old_voids = 0
    total_new_voids = 0

    for idx, base in enumerate(baseline_crit, 1):
        path = base["path"]
        fname = base["filename"]
        short_name = (fname[:42] + "...") if len(fname) > 45 else fname
        old_crit = base.get("has_critical_failure", True)
        old_bleeds = base.get("anomaly_counts", {}).get("cross_column_bleeds", 0)
        old_voids = base.get("anomaly_counts", {}).get("section_voids", 0)
        total_old_bleeds += old_bleeds
        total_old_voids += old_voids

        try:
            t0 = time.time()
            new_audit = audit_single_document(path)
            elap = time.time() - t0
            new_crit = new_audit.get("has_critical_failure", False)
            new_bleeds = new_audit.get("anomaly_counts", {}).get("cross_column_bleeds", 0)
            new_voids = new_audit.get("anomaly_counts", {}).get("section_voids", 0)
            total_new_bleeds += new_bleeds
            total_new_voids += new_voids

            if not new_crit:
                resolved_count += 1
                status = "[RESOLVED]"
            else:
                still_failing += 1
                status = "[FAIL]"

            print(f"{short_name:<45} | {str(old_crit):<8} | {str(new_crit):<8} | {old_bleeds:<9} | {new_bleeds:<9} | {status}")
            sys.stdout.flush()

            results.append({
                "filename": fname,
                "path": path,
                "old_crit": old_crit,
                "new_crit": new_crit,
                "old_bleeds": old_bleeds,
                "new_bleeds": new_bleeds,
                "old_voids": old_voids,
                "new_voids": new_voids,
                "status": status,
                "violations": new_audit.get("violations", [])
            })
        except Exception as e:
            print(f"{short_name:<45} | ERROR: {e}")
            still_failing += 1

    total_elap = time.time() - start_time
    print("=" * 80)
    print("TARGETED DIAGNOSTIC SUMMARY")
    print(f"Total Papers in Cohort:         {len(baseline_crit)}")
    print(f"Successfully Resolved Papers:   {resolved_count} ({resolved_count/len(baseline_crit)*100:.1f}%)")
    print(f"Remaining Failing Papers:       {still_failing} ({still_failing/len(baseline_crit)*100:.1f}%)")
    print(f"Total Bleeds:                   {total_old_bleeds} -> {total_new_bleeds} (Dropped by {total_old_bleeds - total_new_bleeds})")
    print(f"Total Section Voids:            {total_old_voids} -> {total_new_voids} (Dropped by {total_old_voids - total_new_voids})")
    print(f"Total Diagnostic Runtime:       {total_elap:.1f}s (Average: {total_elap/max(1, len(baseline_crit)):.2f}s/paper)")
    print("=" * 80)

    # Save results
    out_path = os.path.join("data", "diagnostic_cohort_66_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_cohort": len(baseline_crit),
            "resolved_count": resolved_count,
            "still_failing": still_failing,
            "total_old_bleeds": total_old_bleeds,
            "total_new_bleeds": total_new_bleeds,
            "total_old_voids": total_old_voids,
            "total_new_voids": total_new_voids,
            "results": results
        }, f, indent=2)
    print(f"Detailed diagnostic results saved to: {out_path}")

if __name__ == "__main__":
    run_diagnostic()

