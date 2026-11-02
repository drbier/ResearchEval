# WonkProject Corpus Deep Indexer Invariant Audit Report

**Execution Timestamp**: 2026-11-01 19:29:16
**Total Papers Audited**: 235
**Total Audit Runtime**: 492.3s (Average: 2.09s/paper)

## Executive Health Summary

| Metric | Count | Percentage | Status |
|---|---|---|---|
| **Fully Compliant Papers** | 10 / 235 | 4.3% | ⚠️ ANOMALIES FOUND |
| **Critical Failures** (Column Bleeds / Trapped Sections) | 81 / 235 | 34.5% | ❌ REQUIRES FIX |
| **Cross-Column Bounding Box Bleeds** | 79 | 33.6% | ❌ HIGH PRIORITY |
| **Missing Discussion Section Voids** | 17 | 7.2% | ❌ HIGH PRIORITY |
| **Abstract Page 2+ Leakage** | 95 | 40.4% | ⚠️ MEDIUM |
| **Mega-Paragraphs (Swallowed Subsections)** | 153 | 65.1% | ⚠️ MEDIUM |
| **Table Footnote / Glossary Pollution** | 1 | 0.4% | ℹ️ LOW |

## Publisher Vulnerability Breakdown

| Publisher Family | Total Papers | Papers with Invariant Failures | Failure Rate |
|---|---|---|---|
| **Unknown** | 130 | 123 | 94.6% |
| **MDPI** | 48 | 46 | 95.8% |
| **Springer/Nature/BMC** | 13 | 13 | 100.0% |
| **Elsevier** | 8 | 8 | 100.0% |
| **JAMA** | 8 | 8 | 100.0% |
| **BMJ** | 6 | 6 | 100.0% |
| **The Lancet** | 5 | 4 | 80.0% |
| **Wiley** | 5 | 5 | 100.0% |
| **NEJM** | 5 | 5 | 100.0% |
| **PLOS** | 3 | 3 | 100.0% |
| **JCEM / Oxford** | 3 | 3 | 100.0% |
| **Cell Press** | 1 | 1 | 100.0% |


## Critical Anomaly Highlights

The following papers exhibited structural column bleeds or missing section transitions:

### 📄 `Attenuation of malignant phenotype of glioblastoma following a short course of the pro-oxidant combination of Resveratrol and Copper.pdf`
- **Publisher**: Unknown | **Pages**: 7 | **Total Anchors**: 105
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 5]` on Page 1 stretches from $x_0=47.8$ to $x_1=538.0$ (Width: 595.3).
    > *Excerpt*: "CONCLUSIONS: These results suggest that a simple, non-toxic and inexpensive combination of the commonly used nutraceuticals Resveratrol and "
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 1]` on Page 1 stretches from $x_0=35.9$ to $x_1=550.0$ (Width: 595.3).
    > *Excerpt*: "tion can be abrogated by concurrent treatment with a combinaGlioblastoma (GBM) is a highly aggressive tumour with poor tion of the nutraceut"
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 2]` on Page 1 stretches from $x_0=35.9$ to $x_1=549.9$ (Width: 595.3).
    > *Excerpt*: "Given that the concurrent induction of DNA damage and in ﬂ ammation is a the stomach, which are readily absorbed and have systemic effects i"
  - ❌ **Cross-Column Bleed**: `[Results, Para 11]` on Page 3 stretches from $x_0=60.8$ to $x_1=549.9$ (Width: 595.3).
    > *Excerpt*: "Representative confocal microscopy images of tumour sections to detect cfChPs in TME, and Immuno ﬂ uorescence results of Ki-67,"
  - ❌ **Cross-Column Bleed**: `[Results, Para 12]` on Page 3 stretches from $x_0=35.9$ to $x_1=550.0$ (Width: 595.3).
    > *Excerpt*: "Graphical representation of MFI of extra-nuclear cfChPs (right hand image). The nuclei were gated and MFI of yellow ﬂ uorescent signals in ﬁ"
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 4]` on Page 5 stretches from $x_0=35.9$ to $x_1=549.9$ (Width: 595.3).
    > *Excerpt*: "respectively in R-Cu treated samples. For each gene set, Normalised Enrichment Score (NES), nominal p -value, and False Discovery Rate (FDR)"

### 📄 `Report of the Conference on Low Blood Cholesterol Mortality Associations.pdf`
- **Publisher**: MDPI | **Pages**: 15 | **Total Anchors**: 142
  - ❌ **Cross-Column Bleed**: `[Results, Para 10]` on Page 5 stretches from $x_0=53.5$ to $x_1=530.2$ (Width: 579.8).
    > *Excerpt*: "did not have enough observations at the total cholesterol level to make a proportional hazards estimate. t is the number of standard"

### 📄 `Total Cholesterol and Cancer Risk in a Large Prospective Study in Korea.pdf`
- **Publisher**: Unknown | **Pages**: 7 | **Total Anchors**: 74
  - ❌ **Cross-Column Bleed**: `[Results, Para 12]` on Page 3 stretches from $x_0=129.5$ to $x_1=508.2$ (Width: 585.0).
    > *Excerpt*: "180-199 mg/dL HR† HR† 95% CI HR† 95% CI HR† 95% CI HR† 95% CI"

### 📄 `A meta-analysis of cardiovascular events in intermittent androgen-deprivation therapy versus continuous androgen-deprivation.pdf`
- **Publisher**: Unknown | **Pages**: 8 | **Total Anchors**: 87
  - ❌ **Cross-Column Bleed**: `[Results, Para 13]` on Page 5 stretches from $x_0=52.3$ to $x_1=552.5$ (Width: 595.3).
    > *Excerpt*: "Treatment regimens in the included studies Intermittent: induction only (8 mo): LHRHa injections plus a non-steroidal anti-androgen, with Cr"
  - ❌ **Cross-Column Bleed**: `[Results, Para 14]` on Page 5 stretches from $x_0=52.3$ to $x_1=539.0$ (Width: 595.3).
    > *Excerpt*: "Intermittent: induction only (3 mo): CPA 200 mg for 2 weeks followed by monthly depot Calais da Silva 2009 (SEUG 9401 Trial) 13 injections o"
  - ❌ **Cross-Column Bleed**: `[Results, Para 16]` on Page 5 stretches from $x_0=52.3$ to $x_1=552.5$ (Width: 595.3).
    > *Excerpt*: "Intermittent: induction only (6 mo): goserelin acetate (3.6 mg) SC every 28 days. The CPA was Salonen 2012/2013 (FinnProstate Study VII) 14 "
  - ❌ **Section Void**: Paper has 8 pages and 37 Results anchors, but Discussion has 0 anchors (Discussion trapped in Results).

### 📄 `Intermittent androgen-deprivation therapy in prostate cancer a critical review focused on phase 3 trials.pdf`
- **Publisher**: Elsevier | **Pages**: 9 | **Total Anchors**: 117
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 2]` on Page 1 stretches from $x_0=51.9$ to $x_1=548.0$ (Width: 595.3).
    > *Excerpt*: "Context: Intermittent androgen deprivation (IAD) in prostate cancer (PCa) patients has Accepted April 10, 2013 been proposed to delay develo"
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 3]` on Page 1 stretches from $x_0=51.9$ to $x_1=548.1$ (Width: 595.3).
    > *Excerpt*: "Objective: This review analyzes (1) the oncologic and quality of life (QoL) results from print on April 19, 2013 randomized phase 3 trials c"
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 63]` on Page 7 stretches from $x_0=57.8$ to $x_1=424.1$ (Width: 595.3).
    > *Excerpt*: "E U R O P E A N U R O L O G Y X X X ( 2 0 1 3 ) X X X – X X X Table 5 – Comparison of international guidelines on indications for intermitte"

### 📄 `Intermittent vs Continuous Androgen Deprivation Therapy for Prostate Cancer A Systematic Review and Meta-analysis.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 136
  - ❌ **Cross-Column Bleed**: `[References, Para 23]` on Page 8 stretches from $x_0=67.4$ to $x_1=534.6$ (Width: 612.0).
    > *Excerpt*: "ing pooled analyses. In addition, the high risk of bias and the systematic method of evaluation of adverse effects in the inlow methodologic"
  - ❌ **Cross-Column Bleed**: `[Conclusions, Para 1]` on Page 8 stretches from $x_0=67.4$ to $x_1=534.4$ (Width: 612.0).
    > *Excerpt*: "sive literature search using multiple databases, including both In our systematic review, we observed that intermittent anscientific and gra"
  - ❌ **Cross-Column Bleed**: `[Conclusions, Para 2]` on Page 8 stretches from $x_0=67.4$ to $x_1=534.4$ (Width: 612.0).
    > *Excerpt*: "vival. No major difference in quality of life was observed beWe also examined the effect of the intervention on several tween groups, althou"
  - ❌ **Cross-Column Bleed**: `[Conclusions, Para 3]` on Page 8 stretches from $x_0=67.4$ to $x_1=534.5$ (Width: 612.0).
    > *Excerpt*: "ered as an alternative therapeutic option in patients with prosOur systematic review was limited by the available data, tate cancer. However"

### 📄 `Treatment of prostate cancer with intermittent versus continuous androgen deprivation- a systematic review of randomized tri.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 117
  - ❌ **Cross-Column Bleed**: `[Results, Para 8]` on Page 3 stretches from $x_0=56.5$ to $x_1=381.5$ (Width: 585.0).
    > *Excerpt*: "PSA above an acceptable level or Note: acceptable level of PSA needed to stop or start ADT depends on physicians’/patients’ preference"

### 📄 `Antioxidant supplementation and breast cancer prognosis in postmenopausal women undergoing chemotherapy and radiation therapy.pdf`
- **Publisher**: Unknown | **Pages**: 10 | **Total Anchors**: 112
  - ❌ **Cross-Column Bleed**: `[Methods, Para 15]` on Page 3 stretches from $x_0=41.7$ to $x_1=543.8$ (Width: 585.0).
    > *Excerpt*: "Flow diagram of exclusion and inclusion criteria for participants of the Mamma Carcinoma Risk Factor Investigation study for analyses relati"
  - ❌ **Cross-Column Bleed**: `[Results, Para 9]` on Page 5 stretches from $x_0=80.9$ to $x_1=428.3$ (Width: 585.0).
    > *Excerpt*: "Antioxidants, chemo/radiotherapy in breast cancer Characteristics of 2223 breast cancer patients overall and according to postdiagnosis diet"

### 📄 `Association Between Precautionary Behaviors and Breast Cancer-Related Lymphedema in Patients Undergoing Bilateral Surgery.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 97
  - ❌ **Cross-Column Bleed**: `[Results, Para 21]` on Page 9 stretches from $x_0=37.1$ to $x_1=550.1$ (Width: 585.0).
    > *Excerpt*: "The following represents disclosure information provided by authors of this manuscript. All relationships are considered compensated. Relati"

### 📄 `Association between Dietary Indices and Dietary Patterns and Mortality and Cancer Recurrence among Cancer Survivors An Updated Systematic Review and Meta-Analysis of Cohort Studies.pdf`
- **Publisher**: MDPI | **Pages**: 19 | **Total Anchors**: 215
  - ❌ **Cross-Column Bleed**: `[Results, Para 7]` on Page 6 stretches from $x_0=187.7$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "Overall mortality was reported in 36 studies. Two studies [ 27 , 28 ] did not report this"
  - ❌ **Cross-Column Bleed**: `[Results, Para 9]` on Page 6 stretches from $x_0=166.4$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "Twenty-six of the included studies were conducted in the United States. Seven studies Portugal, and one from the Netherlands. One cohort stu"
  - ❌ **Cross-Column Bleed**: `[Results, Para 10]` on Page 6 stretches from $x_0=166.4$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "Supplementary Material Tables S6–S8 summarize the included studies with respect to diet-quality indices and/or dietary patterns investigated"
  - ❌ **Cross-Column Bleed**: `[Results, Para 11]` on Page 6 stretches from $x_0=166.4$ to $x_1=561.0$ (Width: 595.3).
    > *Excerpt*: "The potential risk of bias was assessed using an adjusted version of the ROBINS-I tool. Supplementary Material Table S9 provides comprehensi"
  - ❌ **Cross-Column Bleed**: `[Results, Para 22]` on Page 6 stretches from $x_0=166.0$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "high risk only in one domain (bias due to confounding). Another 18 studies were assessed with moderate potential risk of bias. Three studies"

### 📄 `Benefits-and-harms-of-breast-cancer-mammography-screening-for-women-at-average-risk-of-breast_optimize.pdf`
- **Publisher**: Unknown | **Pages**: 16 | **Total Anchors**: 180
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 18]` on Page 10 stretches from $x_0=131.0$ to $x_1=488.4$ (Width: 595.3).
    > *Excerpt*: "⨁⨁  b,c,d ⨁⨁  b,j ⨁⨁  b,j ⨁⨁  c,i evidence LOW LOW LOW LOW Downgraded due to indirectness Downgraded due to indirectness Downgraded "
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 29]` on Page 12 stretches from $x_0=103.1$ to $x_1=501.6$ (Width: 595.3).
    > *Excerpt*: "Certainty of evidence ⨁⨁  h LOW f Chemotherapy protocols and indications have significantly changed (e.g. node status was not determined i"

### 📄 `Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants_ A Comparative Modeling Analysis - PMC.pdf`
- **Publisher**: JAMA | **Pages**: 34 | **Total Anchors**: 165
  - ❌ **Cross-Column Bleed**: `[Methods, Para 5]` on Page 7 stretches from $x_0=118.9$ to $x_1=587.6$ (Width: 612.0).
    > *Excerpt*: "Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants: A Comparative Modeling Ana…"
  - ❌ **Cross-Column Bleed**: `[Results, Para 17]` on Page 13 stretches from $x_0=41.2$ to $x_1=567.2$ (Width: 612.0).
    > *Excerpt*: "Abbreviation: MRI, magnetic resonance imaging. a Results are shown as mean values of cumulative lifetime outcomes per 1000 women screened ac"
  - ❌ **Cross-Column Bleed**: `[Results, Para 39]` on Page 20 stretches from $x_0=41.2$ to $x_1=571.2$ (Width: 612.0).
    > *Excerpt*: "Abbreviation: MRI, magnetic resonance imaging. a Results are shown as model mean values of cumulative lifetime outcomes per 1000 women scree"

### 📄 `Breast cancer patients enrolled in the Swiss mammography screening program “donna” demonstrate prolonged survival.pdf`
- **Publisher**: Unknown | **Pages**: 13 | **Total Anchors**: 100
  - ❌ **Cross-Column Bleed**: `[Results, Para 6]` on Page 5 stretches from $x_0=56.7$ to $x_1=411.6$ (Width: 595.3).
    > *Excerpt*: "Wilcoxon–Mann Whitney rank sum tests or student’s t-tests, as appropriate, were used to test for significance in differences is also true fo"

### 📄 `Cancer Medicine - 2025 - Modi - Associations of Commonly Used Concomitant Medications With Survival and Adverse Event.pdf`
- **Publisher**: Unknown | **Pages**: 10 | **Total Anchors**: 42
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 5]` on Page 2 stretches from $x_0=53.6$ to $x_1=543.8$ (Width: 595.3).
    > *Excerpt*: "Conclusion: These findings emphasise the need for careful management of concomitant medications in breast cancer care and support ongoing re"

### 📄 `Dietary Supplement Use During Chemotherapy and Survival Outcomes of Patients With Breast Cancer Enrolled in a Cooperative Group Clinical Trial (SWOG S0221).pdf`
- **Publisher**: Unknown | **Pages**: 17 | **Total Anchors**: 143
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 17]` on Page 8 stretches from $x_0=37.0$ to $x_1=548.1$ (Width: 585.0).
    > *Excerpt*: "† Strati ﬁ ed on treatment assignment and adjusted for age, tumor characteristics (estrogen receptor, progesterone receptor, human epidermal"
  - ❌ **Cross-Column Bleed**: `[References, Para 9]` on Page 10 stretches from $x_0=93.5$ to $x_1=548.0$ (Width: 585.0).
    > *Excerpt*: "Cassileth BR, Vickers AJ: High prevalence of complementary and alternative medicine use among cancer patients: Implications for research and"
  - ❌ **Cross-Column Bleed**: `[Appendix, Para 3]` on Page 14 stretches from $x_0=77.8$ to $x_1=548.0$ (Width: 585.0).
    > *Excerpt*: "TABLE A2. Prevalence of Use of Dietary Supplements Before and During Chemotherapy for High-Risk Breast Cancer in S0221: DELCaP Study Partici"
  - ❌ **Cross-Column Bleed**: `[Appendix, Para 7]` on Page 15 stretches from $x_0=77.8$ to $x_1=548.0$ (Width: 585.0).
    > *Excerpt*: "Ambrosone et al TABLE A2. Prevalence of Use of Dietary Supplements Before and During Chemotherapy for High-Risk Breast Cancer in S0221: DELC"
