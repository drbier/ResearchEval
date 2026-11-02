# WonkProject Corpus Deep Indexer Invariant Audit Report

**Execution Timestamp**: 2026-11-01 18:19:25
**Total Papers Audited**: 385
**Total Audit Runtime**: 7034.1s (Average: 18.27s/paper)

## Executive Health Summary

| Metric | Count | Percentage | Status |
|---|---|---|---|
| **Fully Compliant Papers** | 13 / 385 | 3.4% | ⚠️ ANOMALIES FOUND |
| **Critical Failures** (Column Bleeds / Trapped Sections) | 175 / 385 | 45.5% | ❌ REQUIRES FIX |
| **Cross-Column Bounding Box Bleeds** | 162 | 42.1% | ❌ HIGH PRIORITY |
| **Missing Discussion Section Voids** | 46 | 11.9% | ❌ HIGH PRIORITY |
| **Abstract Page 2+ Leakage** | 167 | 43.4% | ⚠️ MEDIUM |
| **Mega-Paragraphs (Swallowed Subsections)** | 279 | 72.5% | ⚠️ MEDIUM |
| **Table Footnote / Glossary Pollution** | 83 | 21.6% | ℹ️ LOW |

## Publisher Vulnerability Breakdown

| Publisher Family | Total Papers | Papers with Invariant Failures | Failure Rate |
|---|---|---|---|
| **Unknown** | 280 | 269 | 96.1% |
| **MDPI** | 48 | 46 | 95.8% |
| **Springer/Nature/BMC** | 13 | 13 | 100.0% |
| **Elsevier** | 8 | 8 | 100.0% |
| **JAMA** | 8 | 8 | 100.0% |
| **BMJ** | 6 | 6 | 100.0% |
| **The Lancet** | 5 | 5 | 100.0% |
| **Wiley** | 5 | 5 | 100.0% |
| **NEJM** | 5 | 5 | 100.0% |
| **PLOS** | 3 | 3 | 100.0% |
| **JCEM / Oxford** | 3 | 3 | 100.0% |
| **Cell Press** | 1 | 1 | 100.0% |


## Critical Anomaly Highlights

The following papers exhibited structural column bleeds or missing section transitions:

### 📄 `Attenuation of malignant phenotype of glioblastoma following a short course of the pro-oxidant combination of Resveratrol and Copper.pdf`
- **Publisher**: Unknown | **Pages**: 7 | **Total Anchors**: 87
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 5]` on Page 1 stretches from $x_0=47.8$ to $x_1=538.0$ (Width: 595.3).
    > *Excerpt*: "CONCLUSIONS: These results suggest that a simple, non-toxic and inexpensive combination of the commonly used nutraceuticals Resveratrol and "
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 1]` on Page 1 stretches from $x_0=35.9$ to $x_1=550.0$ (Width: 595.3).
    > *Excerpt*: "tion can be abrogated by concurrent treatment with a combinaGlioblastoma (GBM) is a highly aggressive tumour with poor tion of the nutraceut"
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 2]` on Page 1 stretches from $x_0=35.9$ to $x_1=549.9$ (Width: 595.3).
    > *Excerpt*: "Given that the concurrent induction of DNA damage and in ﬂ ammation is a the stomach, which are readily absorbed and have systemic effects i"

### 📄 `Cholesterol and all-cause mortality in elderly people from the Honolulu Heart Program a cohort study.pdf`
- **Publisher**: The Lancet | **Pages**: 5 | **Total Anchors**: 54
  - ❌ **Cross-Column Bleed**: `[Results, Para 6]` on Page 4 stretches from $x_0=45.8$ to $x_1=516.3$ (Width: 595.0).
    > *Excerpt*: "Intermediate (4·51–5·25 mmol/L) 1·39 (0·91–2·12) 1·33 (0·87–2·03) The nine groups were based on tertiles of cholesterol at examinations thre"

### 📄 `Evaluating the Association Between Low-Density Lipoprotein Cholesterol Reduction and Relative and Absolute Effects of Statin Treatment.pdf`
- **Publisher**: Unknown | **Pages**: 8 | **Total Anchors**: 99
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 4]` on Page 4 stretches from $x_0=72.3$ to $x_1=510.3$ (Width: 612.0).
    > *Excerpt*: "evidence of heterogeneity; MI, myocardial infarction; RRR, relative risk reduction; 1° prevention, primary prevention; 2° prevention, second"

### 📄 `Lack of an association or an inverse association between low-density-lipoprotein cholesterol and mortality in the elderly a systematic review.pdf`
- **Publisher**: BMJ | **Pages**: 8 | **Total Anchors**: 91
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 4]` on Page 1 stretches from $x_0=41.8$ to $x_1=547.3$ (Width: 595.3).
    > *Excerpt*: "Results: We identified 19 cohort studies including 30 in the title or in the abstract. cohorts with a total of 68 094 elderly people, where "
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 7]` on Page 1 stretches from $x_0=146.8$ to $x_1=553.3$ (Width: 595.3).
    > *Excerpt*: "▪ We may have overlooked a small number of relemortality in most people over 60 years. This finding is vant studies because we only searched"
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 8]` on Page 1 stretches from $x_0=41.8$ to $x_1=553.3$ (Width: 595.3).
    > *Excerpt*: "erosclerosis. 1 Moreover, in most of the Japanese epidemiological studies, high TC is For numbered affiliations see end of article. not a ri"

### 📄 `Report of the Conference on Low Blood Cholesterol Mortality Associations.pdf`
- **Publisher**: MDPI | **Pages**: 15 | **Total Anchors**: 108
  - ❌ **Cross-Column Bleed**: `[Results, Para 22]` on Page 8 stretches from $x_0=55.3$ to $x_1=527.0$ (Width: 579.8).
    > *Excerpt*: "Adjusted proportional hazards model hazard rate ratios. Adjusted for age, diastolic blood pressure, cigarette smoking, and body mass ItI.1.6"
  - ❌ **Cross-Column Bleed**: `[Results, Para 36]` on Page 11 stretches from $x_0=89.3$ to $x_1=496.6$ (Width: 579.8).
    > *Excerpt*: "Ecological Correlations Between Fatty Acids in the Diet in 1979-81 and Mortality in 1987, Ages 35-74, 31 Countries"
  - ❌ **Section Void**: Paper has 15 pages and 50 Results anchors, but Discussion has 0 anchors (Discussion trapped in Results).

### 📄 `Total Cholesterol and Cancer Risk in a Large Prospective Study in Korea.pdf`
- **Publisher**: Unknown | **Pages**: 7 | **Total Anchors**: 62
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 2]` on Page 4 stretches from $x_0=42.5$ to $x_1=543.7$ (Width: 585.0).
    > *Excerpt*: "†Models used attained age as the underlying time metric and were adjusted for cigarette smoking, alcohol drinking, body mass index, fasting "

### 📄 `A meta-analysis of cardiovascular events in intermittent androgen-deprivation therapy versus continuous androgen-deprivation.pdf`
- **Publisher**: Unknown | **Pages**: 8 | **Total Anchors**: 82
  - ❌ **Cross-Column Bleed**: `[Results, Para 13]` on Page 5 stretches from $x_0=45.4$ to $x_1=559.4$ (Width: 595.3).
    > *Excerpt*: "IADT. Similar results were also reported by Botrel et al. 21 (speci ﬁ c They found that in terms of overall survival, the hazard risks (HRs)"
  - ❌ **Cross-Column Bleed**: `[Results, Para 15]` on Page 5 stretches from $x_0=52.3$ to $x_1=552.5$ (Width: 595.3).
    > *Excerpt*: "Treatment regimens in the included studies Intermittent: induction only (8 mo): LHRHa injections plus a non-steroidal anti-androgen, with Cr"
  - ❌ **Cross-Column Bleed**: `[Results, Para 16]` on Page 5 stretches from $x_0=52.3$ to $x_1=539.0$ (Width: 595.3).
    > *Excerpt*: "Intermittent: induction only (3 mo): CPA 200 mg for 2 weeks followed by monthly depot Calais da Silva 2009 (SEUG 9401 Trial) 13 injections o"
  - ❌ **Cross-Column Bleed**: `[Results, Para 18]` on Page 5 stretches from $x_0=52.3$ to $x_1=552.5$ (Width: 595.3).
    > *Excerpt*: "Intermittent: induction only (6 mo): goserelin acetate (3.6 mg) SC every 28 days. The CPA was Salonen 2012/2013 (FinnProstate Study VII) 14 "
  - ❌ **Section Void**: Paper has 8 pages and 34 Results anchors, but Discussion has 0 anchors (Discussion trapped in Results).

### 📄 `Intermittent androgen-deprivation therapy in prostate cancer a critical review focused on phase 3 trials.pdf`
- **Publisher**: Elsevier | **Pages**: 9 | **Total Anchors**: 125
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 2]` on Page 1 stretches from $x_0=51.9$ to $x_1=548.0$ (Width: 595.3).
    > *Excerpt*: "Context: Intermittent androgen deprivation (IAD) in prostate cancer (PCa) patients has Accepted April 10, 2013 been proposed to delay develo"
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 3]` on Page 1 stretches from $x_0=51.9$ to $x_1=548.1$ (Width: 595.3).
    > *Excerpt*: "Objective: This review analyzes (1) the oncologic and quality of life (QoL) results from print on April 19, 2013 randomized phase 3 trials c"
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 52]` on Page 5 stretches from $x_0=57.8$ to $x_1=542.0$ (Width: 595.3).
    > *Excerpt*: "Please cite this article in press as: Sciarra A, et al. Intermittent Androgen-deprivation Therapy in Prostate Cancer: A Critical Review Focu"
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 71]` on Page 7 stretches from $x_0=57.8$ to $x_1=424.1$ (Width: 595.3).
    > *Excerpt*: "E U R O P E A N U R O L O G Y X X X ( 2 0 1 3 ) X X X – X X X Table 5 – Comparison of international guidelines on indications for intermitte"

### 📄 `Intermittent versus continuous androgen deprivation for locally advanced, recurrent or metastatic prostate cancer- a systema.pdf`
- **Publisher**: Unknown | **Pages**: 14 | **Total Anchors**: 168
  - ❌ **Cross-Column Bleed**: `[Results, Para 8]` on Page 5 stretches from $x_0=56.7$ to $x_1=538.7$ (Width: 595.3).
    > *Excerpt*: "ever, when the random-effects model analysis was performed, no significant difference was detected (ranFour studies [8,48-50,54,55] included"
  - ❌ **Cross-Column Bleed**: `[Results, Para 9]` on Page 5 stretches from $x_0=56.7$ to $x_1=538.5$ (Width: 595.3).
    > *Excerpt*: "It was not possible to perform a meta-analysis for OS group of patients, only 1 study [50] reported TTP data and CSS, since only Crook et al"
  - ❌ **Cross-Column Bleed**: `[Results, Para 10]` on Page 5 stretches from $x_0=56.7$ to $x_1=538.6$ (Width: 595.3).
    > *Excerpt*: "Two studies One study [58], on re-introduction of treatment in [8,50,55] reported OS data, which permitted metaIAD group, used a hormone the"

### 📄 `Intermittent vs Continuous Androgen Deprivation Therapy for Prostate Cancer A Systematic Review and Meta-analysis.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 123
  - ❌ **Cross-Column Bleed**: `[References, Para 8]` on Page 4 stretches from $x_0=67.4$ to $x_1=518.8$ (Width: 612.0).
    > *Excerpt*: "Abbreviations: AA, antiandrogen; CAD, continuous androgen deprivation; CPA, cyproterone acetate; IAD, intermittent androgen deprivation; LHR"
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 14]` on Page 5 stretches from $x_0=76.4$ to $x_1=534.1$ (Width: 612.0).
    > *Excerpt*: "Abbreviations: NA, not available (ie, the outcome was not evaluated in the study); PSA, prostate-specific antigen. a The risk of bias was as"

### 📄 `Treatment of prostate cancer with intermittent versus continuous androgen deprivation- a systematic review of randomized tri.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 89
  - ❌ **Cross-Column Bleed**: `[Results, Para 8]` on Page 3 stretches from $x_0=56.5$ to $x_1=381.5$ (Width: 585.0).
    > *Excerpt*: "PSA above an acceptable level or Note: acceptable level of PSA needed to stop or start ADT depends on physicians’/patients’ preference"
  - ❌ **Cross-Column Bleed**: `[Results, Para 34]` on Page 6 stretches from $x_0=41.5$ to $x_1=446.4$ (Width: 585.0).
    > *Excerpt*: "NOTE. Comparability of groups, deﬁnition of intervention, and measurements used in the groups were satisfactory in all studies."

### 📄 `Antioxidant supplementation and breast cancer prognosis in postmenopausal women undergoing chemotherapy and radiation therapy.pdf`
- **Publisher**: Unknown | **Pages**: 10 | **Total Anchors**: 106
  - ❌ **Cross-Column Bleed**: `[Methods, Para 16]` on Page 3 stretches from $x_0=41.7$ to $x_1=543.8$ (Width: 585.0).
    > *Excerpt*: "Flow diagram of exclusion and inclusion criteria for participants of the Mamma Carcinoma Risk Factor Investigation study for analyses relati"
  - ❌ **Cross-Column Bleed**: `[Results, Para 8]` on Page 5 stretches from $x_0=80.9$ to $x_1=428.3$ (Width: 585.0).
    > *Excerpt*: "Antioxidants, chemo/radiotherapy in breast cancer Characteristics of 2223 breast cancer patients overall and according to postdiagnosis diet"

### 📄 `Association Between Precautionary Behaviors and Breast Cancer-Related Lymphedema in Patients Undergoing Bilateral Surgery.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 86
  - ❌ **Cross-Column Bleed**: `[Results, Para 8]` on Page 3 stretches from $x_0=43.0$ to $x_1=547.1$ (Width: 585.0).
    > *Excerpt*: "Abbreviations: ALND, axillary lymph node dissection; BMI, body mass index; DCIS, ductal carcinoma in situ; RLNR, regional lymph node radiati"
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 10]` on Page 5 stretches from $x_0=43.0$ to $x_1=547.1$ (Width: 585.0).
    > *Excerpt*: "Abbreviations: ALND, axillary lymph node dissection; BMI, body mass index; RLNR, regional lymph node radiation; SLNB, sentinel lymph node bi"
  - ❌ **Cross-Column Bleed**: `[Results, Para 25]` on Page 9 stretches from $x_0=37.1$ to $x_1=550.1$ (Width: 585.0).
    > *Excerpt*: "Association Between Precautionary Behaviors and Breast Cancer – Related Lymphedema in Patients Undergoing Bilateral Surgery The following re"

### 📄 `Benefits-and-harms-of-breast-cancer-mammography-screening-for-women-at-average-risk-of-breast_optimize.pdf`
- **Publisher**: Unknown | **Pages**: 16 | **Total Anchors**: 166
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 23]` on Page 10 stretches from $x_0=131.0$ to $x_1=488.4$ (Width: 595.3).
    > *Excerpt*: "⨁⨁  b,c,d ⨁⨁  b,j ⨁⨁  b,j ⨁⨁  c,i evidence LOW LOW LOW LOW Downgraded due to indirectness Downgraded due to indirectness Downgraded "
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 50]` on Page 12 stretches from $x_0=103.1$ to $x_1=501.6$ (Width: 595.3).
    > *Excerpt*: "Certainty of evidence ⨁⨁  h LOW f Chemotherapy protocols and indications have significantly changed (e.g. node status was not determined i"

### 📄 `Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants_ A Comparative Modeling Analysis - PMC.pdf`
- **Publisher**: JAMA | **Pages**: 34 | **Total Anchors**: 144
  - ❌ **Cross-Column Bleed**: `[Methods, Para 6]` on Page 7 stretches from $x_0=118.9$ to $x_1=587.6$ (Width: 612.0).
    > *Excerpt*: "Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants: A Comparative Modeling Ana…"
