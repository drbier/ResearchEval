"""
expand_pmc_benchmark.py - Curate an expanded, balanced 16-paper PMC benchmark cohort across major publishers and study designs.
"""

import os
import sys
import json
import time
import requests
import xml.etree.ElementTree as ET

# Define balanced matrix: (Publisher/Journal, Design, Search Query)
BENCHMARK_TARGETS = [
    # 1. BMJ Publishing Group (BMJ Open, Gut, Thorax)
    {
        "slot": "BMJ_01_RCT",
        "publisher": "BMJ Publishing Group",
        "journal": "BMJ Open",
        "design": "Randomized Controlled Trial",
        "query": '"BMJ Open"[Journal] AND ("randomized controlled trial"[Publication Type] OR "clinical trial"[Publication Type]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "BMJ_02_Review",
        "publisher": "BMJ Publishing Group",
        "journal": "BMJ Open",
        "design": "Systematic Review / Protocol",
        "query": '"BMJ Open"[Journal] AND ("systematic review"[Publication Type] OR "protocol"[Title]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 2. Public Library of Science (PLOS ONE, PLOS Medicine)
    {
        "slot": "PLOS_01_Cohort",
        "publisher": "PLOS",
        "journal": "PLOS ONE",
        "design": "Observational / Cohort Study",
        "query": '"PLoS One"[Journal] AND ("cohort studies"[MeSH Terms] OR "cohort"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "PLOS_02_RCT",
        "publisher": "PLOS",
        "journal": "PLOS ONE",
        "design": "Randomized Controlled Trial",
        "query": '"PLoS One"[Journal] AND "randomized controlled trial"[Publication Type] AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 3. BioMed Central / Springer Nature (BMC Medicine, Breast Cancer Res)
    {
        "slot": "BMC_01_MetaAnalysis",
        "publisher": "BioMed Central / Springer",
        "journal": "BMC Medicine",
        "design": "Meta-Analysis",
        "query": '"BMC Med"[Journal] AND ("meta-analysis"[Publication Type] OR "systematic review"[Publication Type]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "BMC_02_Trial",
        "publisher": "BioMed Central / Springer",
        "journal": "BMC Cancer / Medicine",
        "design": "Clinical Trial",
        "query": '("BMC Med"[Journal] OR "BMC Cancer"[Journal]) AND ("clinical trial"[Publication Type] OR "randomized controlled trial"[Publication Type]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 4. Nature Publishing Group (Nature Communications, Scientific Reports)
    {
        "slot": "NPG_01_DeepBiomarker",
        "publisher": "Nature Publishing Group",
        "journal": "Nature Communications",
        "design": "Molecular / Biomarker Cohort",
        "query": '"Nat Commun"[Journal] AND ("cancer"[Title/Abstract] OR "clinical"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "NPG_02_ClinicalStudy",
        "publisher": "Nature Publishing Group",
        "journal": "Scientific Reports",
        "design": "Clinical Observational Study",
        "query": '"Sci Rep"[Journal] AND ("clinical"[Title] OR "trial"[Title]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 5. Frontiers Media (Frontiers in Oncology, Frontiers in Medicine)
    {
        "slot": "FRONTIERS_01_Oncology",
        "publisher": "Frontiers",
        "journal": "Frontiers in Oncology",
        "design": "Translational / Clinical Cohort",
        "query": '"Front Oncol"[Journal] AND ("survival"[Title/Abstract] OR "cohort"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "FRONTIERS_02_Meta",
        "publisher": "Frontiers",
        "journal": "Frontiers in Medicine / Endocrinology",
        "design": "Systematic Review / Meta-Analysis",
        "query": '("Front Med (Lausanne)"[Journal] OR "Front Endocrinol (Lausanne)"[Journal]) AND "meta-analysis"[Title] AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 6. Elsevier Open Access / The Lancet OA (eBioMedicine, Lancet Regional Health)
    {
        "slot": "ELSEVIER_01_LancetReg",
        "publisher": "Elsevier / Lancet",
        "journal": "Lancet Regional Health",
        "design": "Observational / Public Health",
        "query": '"Lancet Reg Health"[Journal] AND ("cohort"[Title/Abstract] OR "outcomes"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "ELSEVIER_02_eBioMed",
        "publisher": "Elsevier / Lancet",
        "journal": "eBioMedicine",
        "design": "Translational Clinical Study",
        "query": '"EBioMedicine"[Journal] AND ("clinical"[Title/Abstract] OR "patients"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 7. MDPI Open Access (Nutrients, Cancers)
    {
        "slot": "MDPI_01_Nutrients",
        "publisher": "MDPI",
        "journal": "Nutrients",
        "design": "Dietary / Metabolic RCT or Cohort",
        "query": '"Nutrients"[Journal] AND ("randomized"[Title/Abstract] OR "trial"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "MDPI_02_Cancers",
        "publisher": "MDPI",
        "journal": "Cancers",
        "design": "Oncology Retrospective Analysis",
        "query": '"Cancers (Basel)"[Journal] AND ("retrospective"[Title/Abstract] OR "prognostic"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },

    # 8. Brief Reports & Communications (Compact / 2-4 Pages)
    {
        "slot": "BRIEF_01_AutismDev",
        "publisher": "Springer",
        "journal": "J Autism Dev Disord",
        "design": "Brief Report",
        "query": '"brief report"[Title] AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    },
    {
        "slot": "BRIEF_02_PalliatMed",
        "publisher": "Mary Ann Liebert",
        "journal": "J Palliat Med",
        "design": "Short Communication / Brief",
        "query": '"short communication"[Title] OR "brief report"[Title] AND ("palliative"[Title/Abstract] OR "hospice"[Title/Abstract]) AND ("2023"[Date - Publication] : "2025"[Date - Publication]) AND "open access"[Filter]'
    }
]

def curate_expanded_benchmark():
    cohort = []
    seen_pmcids = set()

    print(f"Searching NCBI PubMed Central across {len(BENCHMARK_TARGETS)} target slots...")

    for target in BENCHMARK_TARGETS:
        slot = target["slot"]
        query = target["query"]
        esearch_url = (
            f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pmc&term={requests.utils.quote(query)}&retmax=5&sort=pub_date&retmode=json"
        )
        try:
            r = requests.get(esearch_url, timeout=12)
            if r.status_code != 200:
                print(f"  [!] Failed query for {slot}: HTTP {r.status_code}")
                continue

            id_list = r.json().get("esearchresult", {}).get("idlist", [])
            # filter unseen
            id_list = [i for i in id_list if f"PMC{i}" not in seen_pmcids]
            if not id_list:
                print(f"  [!] No unseen candidates for {slot}")
                continue

            chosen_id = id_list[0]
            pmcid = f"PMC{chosen_id}"
            seen_pmcids.add(pmcid)

            # Esummary to get clean metadata
            time.sleep(0.34)
            esum_url = (
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                f"?db=pmc&id={chosen_id}&retmode=json"
            )
            r_sum = requests.get(esum_url, timeout=12)
            title = pmcid
            source = target["journal"]
            pubdate = ""
            doi = ""

            if r_sum.status_code == 200:
                info = r_sum.json().get("result", {}).get(chosen_id, {})
                raw_title = info.get("title", pmcid)
                if "<" in raw_title:
                    try:
                        raw_title = "".join(ET.fromstring(f"<root>{raw_title}</root>").itertext())
                    except Exception:
                        pass
                title = raw_title.strip()
                source = info.get("source", target["journal"]).strip()
                pubdate = info.get("pubdate", "")
                doi = info.get("doi", "")

            item = {
                "slot": slot,
                "pmcid": pmcid,
                "title": title,
                "publisher": target["publisher"],
                "journal": source,
                "design": target["design"],
                "pubdate": pubdate,
                "doi": doi
            }
            cohort.append(item)
            clean_t = title.encode('ascii', 'backslashreplace').decode('ascii')
            if len(clean_t) > 55:
                clean_t = clean_t[:52] + "..."
            print(f"  [+] {slot:<22} -> {pmcid:<12} | {source:<18} | {clean_t}")

        except Exception as e:
            print(f"  [!] Error processing slot {slot}: {e}")

    return cohort

if __name__ == "__main__":
    cohort = curate_expanded_benchmark()
    print("\n" + "=" * 90)
    print(f"EXPANDED PMC BENCHMARK CURATED: {len(cohort)} MANUSCRIPTS")
    print("=" * 90)

    out_file = os.path.join("data", "pmc_expanded_16_benchmark.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cohort, f, indent=2)
    print(f"Cohort saved to: {out_file}")

