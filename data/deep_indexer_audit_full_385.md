# WonkProject Corpus Deep Indexer Invariant Audit Report

**Execution Timestamp**: 2026-11-02 14:08:32
**Total Papers Audited**: 385
**Total Audit Runtime**: 8207.4s (Average: 21.32s/paper)

## Executive Health Summary

| Metric | Count | Percentage | Status |
|---|---|---|---|
| **Fully Compliant Papers** | 34 / 385 | 8.8% | ⚠️ ANOMALIES FOUND |
| **Critical Failures** (Column Bleeds / Trapped Sections) | 66 / 385 | 17.1% | ❌ REQUIRES FIX |
| **Cross-Column Bounding Box Bleeds** | 56 | 14.5% | ❌ HIGH PRIORITY |
| **Missing Discussion Section Voids** | 33 | 8.6% | ❌ HIGH PRIORITY |
| **Abstract Page 2+ Leakage** | 161 | 41.8% | ⚠️ MEDIUM |
| **Mega-Paragraphs (Swallowed Subsections)** | 160 | 41.6% | ⚠️ MEDIUM |
| **Table Footnote / Glossary Pollution** | 5 | 1.3% | ℹ️ LOW |

## Publisher Vulnerability Breakdown

| Publisher Family | Total Papers | Papers with Invariant Failures | Failure Rate |
|---|---|---|---|
| **Unknown** | 280 | 254 | 90.7% |
| **MDPI** | 48 | 44 | 91.7% |
| **Springer/Nature/BMC** | 13 | 13 | 100.0% |
| **Elsevier** | 8 | 8 | 100.0% |
| **JAMA** | 8 | 7 | 87.5% |
| **BMJ** | 6 | 5 | 83.3% |
| **The Lancet** | 5 | 3 | 60.0% |
| **Wiley** | 5 | 5 | 100.0% |
| **NEJM** | 5 | 5 | 100.0% |
| **PLOS** | 3 | 3 | 100.0% |
| **JCEM / Oxford** | 3 | 3 | 100.0% |
| **Cell Press** | 1 | 1 | 100.0% |


## Critical Anomaly Highlights

The following papers exhibited structural column bleeds or missing section transitions:

### 📄 `Associations of Plasma Homocysteine Reflecting Vitamin B12 and Folate Status with Fatigue-Related Outcomes in Healthy Adults.pdf`
- **Publisher**: MDPI | **Pages**: 17 | **Total Anchors**: 131
  - ❌ **Cross-Column Bleed**: `[Results, Para 36]` on Page 10 stretches from $x_0=166.4$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "3.4. Pairwise Contrasts Based on Estimated Marginal Means To clarify the relationships among Hcy tertiles for Chalder Physical Fatigue and V"

### 📄 `Association between Dietary Indices and Dietary Patterns and Mortality and Cancer Recurrence among Cancer Survivors An Updated Systematic Review and Meta-Analysis of Cohort Studies.pdf`
- **Publisher**: MDPI | **Pages**: 19 | **Total Anchors**: 162
  - ❌ **Cross-Column Bleed**: `[Methods, Para 15]` on Page 3 stretches from $x_0=166.1$ to $x_1=560.9$ (Width: 595.3).
    > *Excerpt*: "An adjusted version of the Cochrane Risk of Bias in Nonrandomized Studies of Interventions (ROBINS-I) tool was used to evaluate the risk of "
  - ❌ **Cross-Column Bleed**: `[Results, Para 6]` on Page 6 stretches from $x_0=187.7$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "Overall mortality was reported in 36 studies. Two studies [ 27 , 28 ] did not report this"
  - ❌ **Cross-Column Bleed**: `[Results, Para 8]` on Page 6 stretches from $x_0=166.4$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "Twenty-six of the included studies were conducted in the United States. Seven studies Portugal, and one from the Netherlands. One cohort stu"
  - ❌ **Cross-Column Bleed**: `[Results, Para 9]` on Page 6 stretches from $x_0=166.4$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "Supplementary Material Tables S6–S8 summarize the included studies with respect to diet-quality indices and/or dietary patterns investigated"
  - ❌ **Cross-Column Bleed**: `[Results, Para 10]` on Page 6 stretches from $x_0=166.4$ to $x_1=561.0$ (Width: 595.3).
    > *Excerpt*: "The potential risk of bias was assessed using an adjusted version of the ROBINS-I tool. Supplementary Material Table S9 provides comprehensi"
  - ❌ **Cross-Column Bleed**: `[Results, Para 21]` on Page 6 stretches from $x_0=166.0$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "high risk only in one domain (bias due to confounding). Another 18 studies were assessed with moderate potential risk of bias. Three studies"
  - ❌ **Cross-Column Bleed**: `[Results, Para 39]` on Page 9 stretches from $x_0=166.1$ to $x_1=560.9$ (Width: 595.3).
    > *Excerpt*: "3.4. Subgroup Analyses–Cancer Types sociated with overall mortality (RR, 0.83; 95% CI, 0.77–0.91), which was still the case following post-d"

### 📄 `Benefits-and-harms-of-breast-cancer-mammography-screening-for-women-at-average-risk-of-breast_optimize.pdf`
- **Publisher**: Unknown | **Pages**: 16 | **Total Anchors**: 179
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 9]` on Page 10 stretches from $x_0=131.0$ to $x_1=488.4$ (Width: 595.3).
    > *Excerpt*: "⨁⨁  b,c,d ⨁⨁  b,j ⨁⨁  b,j ⨁⨁  c,i evidence LOW LOW LOW LOW Downgraded due to indirectness Downgraded due to indirectness Downgraded "
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 20]` on Page 12 stretches from $x_0=103.1$ to $x_1=501.6$ (Width: 595.3).
    > *Excerpt*: "Certainty of evidence ⨁⨁  h LOW f Chemotherapy protocols and indications have significantly changed (e.g. node status was not determined i"

### 📄 `Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants_ A Comparative Modeling Analysis - PMC.pdf`
- **Publisher**: JAMA | **Pages**: 34 | **Total Anchors**: 166
  - ❌ **Cross-Column Bleed**: `[Methods, Para 5]` on Page 7 stretches from $x_0=118.9$ to $x_1=587.6$ (Width: 612.0).
    > *Excerpt*: "Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants: A Comparative Modeling Ana…"

### 📄 `Cancer Medicine - 2025 - Modi - Associations of Commonly Used Concomitant Medications With Survival and Adverse Event.pdf`
- **Publisher**: Unknown | **Pages**: 10 | **Total Anchors**: 48
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 3]` on Page 2 stretches from $x_0=53.6$ to $x_1=543.8$ (Width: 595.3).
    > *Excerpt*: "Conclusion: These findings emphasise the need for careful management of concomitant medications in breast cancer care and support ongoing re"

### 📄 `Electroacupuncture frequency for chemotherapy-induced neuropathy in breast cancer a randomized controlled trial .pdf`
- **Publisher**: Unknown | **Pages**: 11 | **Total Anchors**: 101
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 11]` on Page 9 stretches from $x_0=48.2$ to $x_1=550.2$ (Width: 595.3).
    > *Excerpt*: "• In the 2 Hz EA group, 13 patients experienced one adverse event, 4 patients experienced two adverse events, and 1 patient experienced four"

### 📄 `Efficacy and safety of metronomic chemotherapy in maintenance therapy for metastatic colorectal cancer A systematic review of randomized controlled trials.pdf`
- **Publisher**: Unknown | **Pages**: 7 | **Total Anchors**: 74
  - ❌ **Cross-Column Bleed**: `[Results, Para 3]` on Page 3 stretches from $x_0=51.0$ to $x_1=560.5$ (Width: 594.0).
    > *Excerpt*: "3.4. The effectiveness of MC in mCRC MT All 4 selected studies included RCTs and had reported on the mPFS and mOS of the participants. Geng "

### 📄 `Metronomic Chemotherapy for Metastatic Breast Cancer Treatment Clinical and Preclinical Data between Lights and Shadows.pdf`
- **Publisher**: MDPI | **Pages**: 18 | **Total Anchors**: 151
  - ❌ **Cross-Column Bleed**: `[Results, Para 68]` on Page 12 stretches from $x_0=166.1$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "proﬁle is associated with well-documented clinical activity in various types of cancer and In a recently published systematic literature ana"
  - ❌ **Cross-Column Bleed**: `[Results, Para 69]` on Page 12 stretches from $x_0=166.0$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "event reporting were noted. Most of the studies used the NCI-CTCAE (any version) criteria, while seven used the WHO criteria. The authors em"
  - ❌ **Cross-Column Bleed**: `[Results, Para 70]` on Page 12 stretches from $x_0=166.4$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "different regimens and schedules applied, even when the same drugs are used, the small number of patients enrolled in the different trials, "

### 📄 `Metronomic Chemotherapy in Triple-Negative Metastatic Breast Cancer The Future Is Now.pdf`
- **Publisher**: Unknown | **Pages**: 6 | **Total Anchors**: 86
  - ❌ **Cross-Column Bleed**: `[Results, Para 17]` on Page 4 stretches from $x_0=50.6$ to $x_1=407.5$ (Width: 600.0).
    > *Excerpt*: "CTX 50 mg/day + Veliparib 60 mg once daily throughout a 21-day cycle ORR = overall response rate; CBR = clinical benefit rate; PFS = progres"
  - ❌ **Section Void**: Paper has 6 pages and 52 Results anchors, but Discussion has 0 anchors (Discussion trapped in Results).

### 📄 `Metronomic chemotherapy for non-metastatic triple negative breast cancer Selection is the key.pdf`
- **Publisher**: Unknown | **Pages**: 11 | **Total Anchors**: 135
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 28]` on Page 4 stretches from $x_0=56.7$ to $x_1=540.3$ (Width: 595.3).
    > *Excerpt*: "EC: Clinical stage; ER: Estrogen receptor; DX: Doxorubicin; CTX: Cyclophosphamide; PTX: Paclitaxel; C: Carboplatin; X: Capecitabine; 5-FU: 5"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 33]` on Page 7 stretches from $x_0=56.7$ to $x_1=540.3$ (Width: 595.3).
    > *Excerpt*: "5FU: 5-Fluoracil; E: Epirubicin, Ca: Carboplatin; T: Docetaxel; CTX: Cyclophosphamide; MTX: Methotrexate; X: Capecitabine; AT: Anthracycline"

### 📄 `Overall Survival with Palbociclib and Fulvestrant in Advanced Breast Cancer..pdf`
- **Publisher**: NEJM | **Pages**: 11 | **Total Anchors**: 121
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 18]` on Page 11 stretches from $x_0=100.0$ to $x_1=507.3$ (Width: 567.0).
    > *Excerpt*: "The authors’ full names and academic degrees are as follows: Nicholas C. Turner, M.D., Dennis J. Slamon, M.D., Jungsil Ro, M.D., Igor Bondar"

### 📄 `Postmastectomy Radiation Therapy An ASTRO-ASCO-SSO Clinical Practice Guideline.pdf`
- **Publisher**: Unknown | **Pages**: 23 | **Total Anchors**: 208
  - ❌ **Section Void**: Paper has 23 pages and 100 Results anchors, but Discussion has 0 anchors (Discussion trapped in Results).

### 📄 `Proton Pump Inhibitor Use and Survival in Patients with newly dx glioblastoma.pdf`
- **Publisher**: JAMA | **Pages**: 13 | **Total Anchors**: 103
  - ❌ **Cross-Column Bleed**: `[Results, Para 3]` on Page 5 stretches from $x_0=47.9$ to $x_1=395.2$ (Width: 612.0).
    > *Excerpt*: "JAMA Network Open | Oncology both subgroups, the association with PPI use remained detrimental compared with no drug. To confirm that the ex"
  - ❌ **Cross-Column Bleed**: `[Results, Para 11]` on Page 6 stretches from $x_0=47.9$ to $x_1=395.3$ (Width: 612.0).
    > *Excerpt*: "Patients who were treated with steroids were more likely to be prescribed PPI or other antacid drugs of steroid intake with the outcomes ass"
  - ❌ **Cross-Column Bleed**: `[Results, Para 12]` on Page 6 stretches from $x_0=47.9$ to $x_1=395.3$ (Width: 612.0).
    > *Excerpt*: "The findings of this meta-analysis suggest that any outcomes associated with PA-PPI in patients with newly diagnosed glioblastoma are detrim"
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 8]` on Page 6 stretches from $x_0=47.9$ to $x_1=392.9$ (Width: 612.0).
    > *Excerpt*: "The precise mechanisms how PA-PPIs may affect outcomes, beyond a pure association, remain to be further studied. Blood-brain barrier permeab"

### 📄 `Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes.pdf`
- **Publisher**: Wiley | **Pages**: 38 | **Total Anchors**: 533
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 41]` on Page 6 stretches from $x_0=96.4$ to $x_1=739.9$ (Width: 841.9).
    > *Excerpt*: "Summary of findings 1. Summary of findings table - Postmastectomy radiotherapy (PMRT) compared to no PMRT in women with breast cancer and Po"
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 18]` on Page 8 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 31]` on Page 9 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 38]` on Page 10 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 60]` on Page 12 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 72]` on Page 13 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 81]` on Page 14 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 87]` on Page 15 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 102]` on Page 16 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 10]` on Page 17 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 62]` on Page 18 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 71]` on Page 19 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."
  - ❌ **Cross-Column Bleed**: `[Methods, Para 14]` on Page 24 stretches from $x_0=160.4$ to $x_1=533.5$ (Width: 595.3).
    > *Excerpt*: "The South Sweden Breast Cancer Group (SSBCG II:1) randomly assigned postmenopausal women to postmastectomy radiotherapy (PMRT) or no radioth"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 15]` on Page 24 stretches from $x_0=160.4$ to $x_1=546.7$ (Width: 595.3).
    > *Excerpt*: "The randomisation was stratified on the department, tumour size and the number of positive axillary Postmenopausal women (defined as at leas"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 16]` on Page 24 stretches from $x_0=171.8$ to $x_1=522.4$ (Width: 595.3).
    > *Excerpt*: "Other malignant diseases except for squamous cell cancer of the skin or cervical cancer in situ"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 18]` on Page 24 stretches from $x_0=160.4$ to $x_1=546.8$ (Width: 595.3).
    > *Excerpt*: "The radiotherapy was administered using a ventral photon beam with the maximum targeted skin dose of 45 Gy administered in 20 fractions over"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 19]` on Page 24 stretches from $x_0=160.4$ to $x_1=528.4$ (Width: 595.3).
    > *Excerpt*: "The number of women with 1 to 3 positive lymph nodes that were randomised and included in this"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 20]` on Page 24 stretches from $x_0=42.5$ to $x_1=498.7$ (Width: 595.3).
    > *Excerpt*: "Post-mastectomy radiotherapy for women with early breast cancer and one to three positive lymph nodes (Review) Copyright © 2023 The Authors."

### 📄 `Real-world impact of postmastectomy radiotherapy in T1–2 breast cancer with one to three positive lymph nodes.pdf`
- **Publisher**: Unknown | **Pages**: 10 | **Total Anchors**: 84
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 16]` on Page 5 stretches from $x_0=45.0$ to $x_1=448.9$ (Width: 595.3).
    > *Excerpt*: "2004 2005 2006 2007 2008 2009 2010 2011 2012 69.4% 71.2% 70.1% 67.3% 63.2% 64 .9% 60.9% 54.4% 52.9% 30.6% 28.8% 29.9% 32.7% 36.8% 35.1 % 39."
