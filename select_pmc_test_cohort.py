"""
select_pmc_test_cohort.py - Discover and select a balanced cohort of PMC articles for highlight verification.
"""

import os
import sys
import json
import time
import requests
import xml.etree.ElementTree as ET

def search_pmc_categories():
    categories = {
        "Randomized Controlled Trial (Medium / Standard IMRaD)": (
            '("randomized controlled trial"[Publication Type] OR "clinical trial"[Publication Type]) '
            'AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
        ),
        "Systematic Review / Meta-Analysis (Long / Multi-Section)": (
            '("systematic review"[Publication Type] OR "meta-analysis"[Publication Type]) '
            'AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
        ),
        "Observational / Cohort Study (Statistical / High Table Density)": (
            '("cohort studies"[MeSH Terms] OR "observational study"[Publication Type]) '
            'AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
        ),
        "Brief Report / Short Communication (Compact / Fast Scroll)": (
            '("brief report"[Title/Abstract] OR "short communication"[Title/Abstract]) '
            'AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
        )
    }

    selected = []

    print("Querying NCBI PubMed Central for candidate test articles...\n")

    for cat_name, query in categories.items():
        esearch_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pmc&term={requests.utils.quote(query)}&retmax=6&sort=pub_date&retmode=json"
        )
        try:
            r = requests.get(esearch_url, timeout=12)
            if r.status_code != 200:
                continue
            id_list = r.json().get("esearchresult", {}).get("idlist", [])
            if not id_list:
                continue

            # Fetch metadata via esummary
            esum_url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                f"?db=pmc&id={','.join(id_list)}&retmode=json"
            )
            time.sleep(0.35)
            r_sum = requests.get(esum_url, timeout=12)
            if r_sum.status_code != 200:
                continue

            result_dict = r_sum.json().get("result", {})
            cat_candidates = []
            for pmc_id in id_list:
                info = result_dict.get(pmc_id, {})
                title = info.get("title", f"PMC{pmc_id}")
                # strip html tags if any
                title = "".join(ET.fromstring(f"<root>{title}</root>").itertext()) if "<" in title else title
                source = info.get("source", "PMC Indexed Journal")
                pubdate = info.get("pubdate", "")
                cat_candidates.append({
                    "pmcid": f"PMC{pmc_id}",
                    "title": title.strip(),
                    "journal": source.strip(),
                    "pubdate": pubdate,
                    "category": cat_name
                })

            # Pick the top 2 from each category
            for item in cat_candidates[:2]:
                selected.append(item)

        except Exception as e:
            print(f"Error querying {cat_name}: {e}")

    return selected

if __name__ == "__main__":
    cohort = search_pmc_categories()
    print("=" * 90)
    print(f"FOUND {len(cohort)} CANDIDATE PMC TEST ARTICLES")
    print("=" * 90)
    for idx, c in enumerate(cohort, 1):
        clean_title = c['title'].encode('ascii', 'backslashreplace').decode('ascii')
        if len(clean_title) > 65:
            clean_title = clean_title[:62] + "..."
        print(f"[{idx:02d}] {c['pmcid']:<12} | {c['journal']:<22} | {clean_title}")
        print(f"     Category: {c['category']}")
        print("-" * 90)

    out_file = os.path.join("data", "pmc_suggested_test_cohort.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cohort, f, indent=2)
    print(f"\nCohort saved to: {out_file}")
