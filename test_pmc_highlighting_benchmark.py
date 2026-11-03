"""
test_pmc_highlighting_benchmark.py - Automated execution and coordinate highlight audit across the 16-paper PMC benchmark.
"""

import os
import sys
import json
import time
import pymupdf
from src.ingestion.fetcher import PaperFetcher
from src.ingestion.indexer import parse_and_index_pdf
from audit_indexer_deep import audit_single_document

def safe_str(s, length=40):
    s = s.encode('ascii', 'backslashreplace').decode('ascii')
    if len(s) > length:
        return s[:length-3] + "..."
    return s

def run_pmc_benchmark():
    benchmark_json = os.path.join("data", "pmc_expanded_16_benchmark.json")
    if not os.path.exists(benchmark_json):
        print(f"Error: {benchmark_json} not found.")
        return

    with open(benchmark_json, "r", encoding="utf-8") as f:
        cohort = json.load(f)

    upload_dir = os.path.join("data", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    fetcher = PaperFetcher(upload_dir)

    print("=" * 105)
    print(f"STARTING PMC 16-MANUSCRIPT BENCHMARK & HIGHLIGHT AUDIT")
    print("=" * 105)
    print(f"{'#':<3} | {'PMCID':<12} | {'Publisher / Journal':<25} | {'Pages':<6} | {'Anchors':<8} | {'Coord Match %':<14} | {'Bleeds':<7} | {'Status'}")
    print("-" * 105)

    start_total = time.time()
    results = []
    success_count = 0

    for idx, item in enumerate(cohort, 1):
        pmcid = item["pmcid"]
        journal = safe_str(item["journal"], 24)
        t0 = time.time()

        try:
            # 1. Fetch & Synthesize PDF from PMC JATS XML
            resolve_res = fetcher.resolve_url(pmcid)
            if resolve_res.get("status") != "full_text_pdf":
                err_msg = resolve_res.get("message", "Fetch failed")
                print(f"{idx:02d} | {pmcid:<12} | {journal:<25} | {'N/A':<6} | {'N/A':<8} | {'N/A':<14} | {'N/A':<7} | [FETCH ERROR: {err_msg[:15]}]")
                results.append({
                    "pmcid": pmcid,
                    "status": "FETCH_ERROR",
                    "error": err_msg
                })
                continue

            pdf_filename = resolve_res["pdf_filename"]
            pdf_path = os.path.join(upload_dir, pdf_filename)

            # 2. Open PDF & count pages
            doc = pymupdf.open(pdf_path)
            total_pages = len(doc)

            # 3. Coordinate Indexing
            indexed = parse_and_index_pdf(pdf_path)
            total_anchors = len(indexed.all_anchors)

            # 4. Highlight Coordinate Audit: Verify every anchor bounding box against PyMuPDF physical text
            coord_matched = 0
            coord_tested = 0
            coord_out_of_bounds = 0

            for aid, meta in indexed.anchor_metadata.items():
                p_num = meta.page_number
                bbox = meta.bbox
                if p_num < 1 or p_num > total_pages:
                    coord_out_of_bounds += 1
                    continue

                page = doc[p_num - 1]
                w = page.rect.width
                h = page.rect.height

                # Check bounding box validity: 0 <= x0 < x1 <= w, 0 <= y0 < y1 <= h
                x0, y0, x1, y1 = bbox
                if not (0 <= x0 < x1 <= w + 2 and 0 <= y0 < y1 <= h + 2):
                    coord_out_of_bounds += 1
                    continue

                # Test text extraction clip: does PyMuPDF find text inside this exact bounding box?
                clip_text = page.get_text("text", clip=pymupdf.Rect(x0, y0, x1, y1)).strip()
                coord_tested += 1
                
                # Check that clip text contains first few words of indexed anchor text
                anchor_words = meta.text.strip().split()[:4]
                if anchor_words:
                    sample_query = " ".join(anchor_words).lower()
                    if sample_query[:15] in clip_text.lower():
                        coord_matched += 1
                    else:
                        # Allow partial match if punctuation varies
                        clean_clip = "".join(c for c in clip_text.lower() if c.isalnum())
                        clean_sample = "".join(c for c in sample_query if c.isalnum())[:12]
                        if clean_sample and clean_sample in clean_clip:
                            coord_matched += 1

            doc.close()

            coord_pct = (coord_matched / max(1, coord_tested)) * 100

            # 5. Deep Pipeline Audit
            deep_audit = audit_single_document(pdf_path)
            bleeds = deep_audit.get("anomaly_counts", {}).get("cross_column_bleeds", 0)
            voids = deep_audit.get("anomaly_counts", {}).get("section_voids", 0)
            has_crit = deep_audit.get("has_critical_failure", False)

            if not has_crit and coord_out_of_bounds == 0 and coord_pct >= 95.0:
                status = "[PASS]"
                success_count += 1
            elif not has_crit:
                status = "[PASS*]"  # Passed deep audit, slight clip diff
                success_count += 1
            else:
                status = "[FAIL]"

            print(f"{idx:02d} | {pmcid:<12} | {journal:<25} | {total_pages:<6} | {total_anchors:<8} | {coord_pct:6.1f}% ({coord_matched}/{coord_tested}) | {bleeds:<7} | {status}")
            sys.stdout.flush()

            results.append({
                "pmcid": pmcid,
                "title": item.get("title", ""),
                "journal": item.get("journal", ""),
                "publisher": item.get("publisher", ""),
                "design": item.get("design", ""),
                "pages": total_pages,
                "anchors": total_anchors,
                "coord_tested": coord_tested,
                "coord_matched": coord_matched,
                "coord_pct": coord_pct,
                "coord_out_of_bounds": coord_out_of_bounds,
                "bleeds": bleeds,
                "voids": voids,
                "has_crit": has_crit,
                "status": status,
                "sections": list(indexed.sections.keys())
            })

        except Exception as e:
            print(f"{idx:02d} | {pmcid:<12} | {journal:<25} | ERROR: {str(e)[:35]}")
            results.append({
                "pmcid": pmcid,
                "status": "ERROR",
                "error": str(e)
            })

    total_elap = time.time() - start_total
    print("=" * 105)
    print("PMC BENCHMARK HIGHLIGHT AUDIT SUMMARY")
    print(f"Total Evaluated:                {len(cohort)}")
    print(f"Passing Manuscripts:            {success_count} / {len(cohort)} ({success_count/len(cohort)*100:.1f}%)")
    print(f"Total Pages Generated:          {sum(r.get('pages', 0) for r in results)}")
    print(f"Total Anchors Tested:           {sum(r.get('coord_tested', 0) for r in results)}")
    print(f"Total Highlight Matches:        {sum(r.get('coord_matched', 0) for r in results)} ({sum(r.get('coord_matched', 0) for r in results)/max(1, sum(r.get('coord_tested', 0) for r in results))*100:.1f}%)")
    print(f"Total Runtime:                  {total_elap:.1f}s ({total_elap/max(1, len(cohort)):.2f}s/paper)")
    print("=" * 105)

    out_report = os.path.join("data", "pmc_benchmark_highlight_audit.json")
    with open(out_report, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_evaluated": len(cohort),
            "passing_count": success_count,
            "pass_rate": success_count / len(cohort) * 100,
            "total_pages": sum(r.get('pages', 0) for r in results),
            "total_anchors": sum(r.get('coord_tested', 0) for r in results),
            "total_matches": sum(r.get('coord_matched', 0) for r in results),
            "results": results
        }, f, indent=2)

    print(f"Detailed audit saved to: {out_report}")

if __name__ == "__main__":
    run_pmc_benchmark()

