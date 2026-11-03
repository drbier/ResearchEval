"""
verify_remaining_32.py - Targeted verification on the 32 remaining failed manuscripts.
"""

import os
import sys
import json
import time
from audit_indexer_deep import audit_single_document

def safe_str(s, length=42):
    s = s.encode('ascii', 'backslashreplace').decode('ascii')
    if len(s) > length:
        return s[:length-3] + "..."
    return s

def run_targeted_verification():
    cohort_results_path = os.path.join("data", "diagnostic_cohort_66_results.json")
    if not os.path.exists(cohort_results_path):
        print(f"Error: {cohort_results_path} not found.")
        return

    with open(cohort_results_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Filter to the 32 papers that were still failing in diagnostic_cohort_66_results
    failing_32 = [r for r in data["results"] if r.get("new_crit", False)]
    print(f"Loaded {len(failing_32)} papers that were failing in previous round.")
    print("=" * 88)
    print(f"{'Paper Name':<42} | {'Prev Bleed':<10} | {'New Bleed':<10} | {'Prev Voids':<10} | {'New Voids':<10} | {'Status'}")
    print("-" * 88)

    start_time = time.time()
    resolved_count = 0
    still_failing = 0
    total_prev_bleeds = 0
    total_new_bleeds = 0
    total_prev_voids = 0
    total_new_voids = 0
    results = []

    for item in failing_32:
        fname = item["filename"]
        path = item["path"]
        short_name = safe_str(fname, 42)
        prev_bleeds = item.get("new_bleeds", 0)
        prev_voids = item.get("new_voids", 0)
        total_prev_bleeds += prev_bleeds
        total_prev_voids += prev_voids

        try:
            audit = audit_single_document(path)
            new_crit = audit.get("has_critical_failure", False)
            new_bleeds = audit.get("anomaly_counts", {}).get("cross_column_bleeds", 0)
            new_voids = audit.get("anomaly_counts", {}).get("section_voids", 0)
            total_new_bleeds += new_bleeds
            total_new_voids += new_voids

            if not new_crit:
                resolved_count += 1
                status = "[RESOLVED]"
            else:
                still_failing += 1
                status = "[FAIL]"

            print(f"{short_name:<42} | {prev_bleeds:<10} | {new_bleeds:<10} | {prev_voids:<10} | {new_voids:<10} | {status}")
            sys.stdout.flush()

            results.append({
                "filename": fname,
                "path": path,
                "prev_bleeds": prev_bleeds,
                "new_bleeds": new_bleeds,
                "prev_voids": prev_voids,
                "new_voids": new_voids,
                "new_crit": new_crit,
                "status": status,
                "violations": audit.get("violations", [])
            })
        except Exception as e:
            print(f"{short_name:<42} | ERROR: {e}")
            still_failing += 1

    total_elap = time.time() - start_time
    print("=" * 88)
    print("TARGETED VERIFICATION SUMMARY (32 PAPERS)")
    print(f"Total Evaluated:                {len(failing_32)}")
    print(f"Newly Resolved Papers:          {resolved_count} / {len(failing_32)} ({resolved_count/len(failing_32)*100:.1f}%)")
    print(f"Remaining Failing Papers:       {still_failing} / {len(failing_32)} ({still_failing/len(failing_32)*100:.1f}%)")
    print(f"Total Bleeds:                   {total_prev_bleeds} -> {total_new_bleeds} (Dropped by {total_prev_bleeds - total_new_bleeds})")
    print(f"Total Section Voids:            {total_prev_voids} -> {total_new_voids}")
    print(f"Runtime:                        {total_elap:.1f}s ({total_elap/max(1, len(failing_32)):.2f}s/paper)")
    print("=" * 88)

    # Save to json
    out_path = os.path.join("data", "verify_remaining_32_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_evaluated": len(failing_32),
            "newly_resolved": resolved_count,
            "still_failing": still_failing,
            "total_prev_bleeds": total_prev_bleeds,
            "total_new_bleeds": total_new_bleeds,
            "total_prev_voids": total_prev_voids,
            "total_new_voids": total_new_voids,
            "results": results
        }, f, indent=2)

if __name__ == "__main__":
    run_targeted_verification()

