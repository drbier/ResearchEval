# WonkProject Corpus Deep Indexer Invariant Audit Report

**Execution Timestamp**: 2026-11-02 07:19:14
**Total Papers Audited**: 235
**Total Audit Runtime**: 499.6s (Average: 2.13s/paper)

## Executive Health Summary

| Metric | Count | Percentage | Status |
|---|---|---|---|
| **Fully Compliant Papers** | 12 / 235 | 5.1% | ⚠️ ANOMALIES FOUND |
| **Critical Failures** (Column Bleeds / Trapped Sections) | 64 / 235 | 27.2% | ❌ REQUIRES FIX |
| **Cross-Column Bounding Box Bleeds** | 60 | 25.5% | ❌ HIGH PRIORITY |
| **Missing Discussion Section Voids** | 16 | 6.8% | ❌ HIGH PRIORITY |
| **Abstract Page 2+ Leakage** | 96 | 40.9% | ⚠️ MEDIUM |
| **Mega-Paragraphs (Swallowed Subsections)** | 143 | 60.9% | ⚠️ MEDIUM |
| **Table Footnote / Glossary Pollution** | 2 | 0.9% | ℹ️ LOW |

## Publisher Vulnerability Breakdown

| Publisher Family | Total Papers | Papers with Invariant Failures | Failure Rate |
|---|---|---|---|
| **Unknown** | 130 | 122 | 93.8% |
| **MDPI** | 48 | 46 | 95.8% |
| **Springer/Nature/BMC** | 13 | 13 | 100.0% |
| **Elsevier** | 8 | 8 | 100.0% |
| **JAMA** | 8 | 8 | 100.0% |
| **BMJ** | 6 | 6 | 100.0% |
| **The Lancet** | 5 | 3 | 60.0% |
| **Wiley** | 5 | 5 | 100.0% |
| **NEJM** | 5 | 5 | 100.0% |
| **PLOS** | 3 | 3 | 100.0% |
| **JCEM / Oxford** | 3 | 3 | 100.0% |
| **Cell Press** | 1 | 1 | 100.0% |


## Critical Anomaly Highlights

The following papers exhibited structural column bleeds or missing section transitions:

### 📄 `Total cholesterol and all-cause mortality by sex and age a prospective cohort study among 12.8 million adults.pdf`
- **Publisher**: Springer/Nature/BMC | **Pages**: 10 | **Total Anchors**: 47
  - ❌ **Cross-Column Bleed**: `[References, Para 4]` on Page 8 stretches from $x_0=155.6$ to $x_1=556.7$ (Width: 595.3).
    > *Excerpt*: "In conclusion, U-curve relationships between TC and mortality were found, regardless of sex and age. TC ranges associated with the lowest mo"
  - ❌ **Cross-Column Bleed**: `[References, Para 5]` on Page 8 stretches from $x_0=155.6$ to $x_1=554.6$ (Width: 595.3).
    > *Excerpt*: "2. US Department of Health and Human Services. Healthy People 2020. 2020 Topics & Objective: Heart Disease and Stroke. https:// www.healthyp"

### 📄 `Association between Dietary Indices and Dietary Patterns and Mortality and Cancer Recurrence among Cancer Survivors An Updated Systematic Review and Meta-Analysis of Cohort Studies.pdf`
- **Publisher**: MDPI | **Pages**: 19 | **Total Anchors**: 232
  - ❌ **Cross-Column Bleed**: `[Methods, Para 3]` on Page 3 stretches from $x_0=166.4$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "and (6) study population restricted to adults only ( ≥ 18 years). PICOS criteria for eligible"
  - ❌ **Cross-Column Bleed**: `[Methods, Para 14]` on Page 3 stretches from $x_0=166.1$ to $x_1=560.9$ (Width: 595.3).
    > *Excerpt*: "Data extraction from the included studies was carried out as follows: (1) name of the ﬁrst author and year of publication; (2) country; (3) "
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

### 📄 `Benefits-and-harms-of-breast-cancer-mammography-screening-for-women-at-average-risk-of-breast_optimize.pdf`
- **Publisher**: Unknown | **Pages**: 16 | **Total Anchors**: 179
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 17]` on Page 10 stretches from $x_0=131.0$ to $x_1=488.4$ (Width: 595.3).
    > *Excerpt*: "⨁⨁  b,c,d ⨁⨁  b,j ⨁⨁  b,j ⨁⨁  c,i evidence LOW LOW LOW LOW Downgraded due to indirectness Downgraded due to indirectness Downgraded "
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 28]` on Page 12 stretches from $x_0=103.1$ to $x_1=501.6$ (Width: 595.3).
    > *Excerpt*: "Certainty of evidence ⨁⨁  h LOW f Chemotherapy protocols and indications have significantly changed (e.g. node status was not determined i"

### 📄 `Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants_ A Comparative Modeling Analysis - PMC.pdf`
- **Publisher**: JAMA | **Pages**: 34 | **Total Anchors**: 165
  - ❌ **Cross-Column Bleed**: `[Methods, Para 5]` on Page 7 stretches from $x_0=118.9$ to $x_1=587.6$ (Width: 612.0).
    > *Excerpt*: "Breast Cancer Screening Strategies for Women With ATM, CHEK2, and PALB2 Pathogenic Variants: A Comparative Modeling Ana…"

### 📄 `Breast cancer patients enrolled in the Swiss mammography screening program “donna” demonstrate prolonged survival.pdf`
- **Publisher**: Unknown | **Pages**: 13 | **Total Anchors**: 101
  - ❌ **Cross-Column Bleed**: `[Results, Para 6]` on Page 5 stretches from $x_0=56.7$ to $x_1=411.6$ (Width: 595.3).
    > *Excerpt*: "Wilcoxon–Mann Whitney rank sum tests or student’s t-tests, as appropriate, were used to test for significance in differences is also true fo"

### 📄 `Cancer Medicine - 2025 - Modi - Associations of Commonly Used Concomitant Medications With Survival and Adverse Event.pdf`
- **Publisher**: Unknown | **Pages**: 10 | **Total Anchors**: 42
  - ❌ **Cross-Column Bleed**: `[Abstract, Para 4]` on Page 2 stretches from $x_0=53.6$ to $x_1=543.8$ (Width: 595.3).
    > *Excerpt*: "Conclusion: These findings emphasise the need for careful management of concomitant medications in breast cancer care and support ongoing re"

### 📄 `Dietary Supplement Use During Chemotherapy and Survival Outcomes of Patients With Breast Cancer Enrolled in a Cooperative Group Clinical Trial (SWOG S0221).pdf`
- **Publisher**: Unknown | **Pages**: 17 | **Total Anchors**: 158
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 17]` on Page 8 stretches from $x_0=37.0$ to $x_1=548.1$ (Width: 585.0).
    > *Excerpt*: "† Strati ﬁ ed on treatment assignment and adjusted for age, tumor characteristics (estrogen receptor, progesterone receptor, human epidermal"
  - ❌ **Cross-Column Bleed**: `[References, Para 9]` on Page 10 stretches from $x_0=93.5$ to $x_1=548.0$ (Width: 585.0).
    > *Excerpt*: "Cassileth BR, Vickers AJ: High prevalence of complementary and alternative medicine use among cancer patients: Implications for research and"
  - ❌ **Cross-Column Bleed**: `[Appendix, Para 3]` on Page 14 stretches from $x_0=77.8$ to $x_1=548.0$ (Width: 585.0).
    > *Excerpt*: "TABLE A2. Prevalence of Use of Dietary Supplements Before and During Chemotherapy for High-Risk Breast Cancer in S0221: DELCaP Study Partici"
  - ❌ **Cross-Column Bleed**: `[Appendix, Para 7]` on Page 15 stretches from $x_0=77.8$ to $x_1=548.0$ (Width: 585.0).
    > *Excerpt*: "Ambrosone et al TABLE A2. Prevalence of Use of Dietary Supplements Before and During Chemotherapy for High-Risk Breast Cancer in S0221: DELC"

### 📄 `Dietary flaxseed alters tumor biological markers in postmenopausal breast cancer.pdf`
- **Publisher**: Unknown | **Pages**: 8 | **Total Anchors**: 126
  - ❌ **Cross-Column Bleed**: `[References, Para 37]` on Page 7 stretches from $x_0=46.2$ to $x_1=549.3$ (Width: 585.0).
    > *Excerpt*: "seed enhances the inhibitory effect of tamoxifen on Anderson E. Effect of tamoxifen on Ki67 labeling 90^100."
  - ❌ **Cross-Column Bleed**: `[References, Para 38]` on Page 7 stretches from $x_0=41.2$ to $x_1=549.3$ (Width: 585.0).
    > *Excerpt*: "the growth of estrogen-dependent human breast index in human breast tumors and its relationship to 16. Adlercreutz H, MousaviY, ClarkJ, et a"
  - ❌ **Cross-Column Bleed**: `[References, Para 40]` on Page 7 stretches from $x_0=41.2$ to $x_1=549.4$ (Width: 585.0).
    > *Excerpt*: "34. Chen J, Stavro M,Thompson LU. Dietary flaxseed 51. Robertson JF, Nicholson RI, Bundred NJ, et al. 17. Saarinen NM,Warri A, Makela SI, et"
  - ❌ **Cross-Column Bleed**: `[References, Para 41]` on Page 7 stretches from $x_0=213.6$ to $x_1=549.3$ (Width: 585.0).
    > *Excerpt*: "tamoxifen in postmenopausal women with primary 35. Dabrosin C, Chen J, Wang L, Thompson LU."
  - ❌ **Cross-Column Bleed**: `[References, Para 43]` on Page 7 stretches from $x_0=46.2$ to $x_1=549.4$ (Width: 585.0).
    > *Excerpt*: "Flaxseed inhibits metastasis and decreases extracelluAntioxidant activity of the flaxseed lignan secoisolari52. Harper-Wynne CL, Sacks NP, S"
  - ❌ **Cross-Column Bleed**: `[References, Para 44]` on Page 7 stretches from $x_0=46.2$ to $x_1=549.4$ (Width: 585.0).
    > *Excerpt*: "lar vascular endothelial growth factor in human breast ciresinol diglycoside and its mammalian lignan Comparison of the systemic and intratu"
  - ❌ **Cross-Column Bleed**: `[References, Para 46]` on Page 7 stretches from $x_0=41.2$ to $x_1=549.4$ (Width: 585.0).
    > *Excerpt*: "36. Thompson LU, Seidl M, Rickard S, Orchson LJ, JClin Oncol 2002;20:1026^35. 19. Prasad K. Hydroxyl radical- scavenging property of Fong HH"
  - ❌ **Cross-Column Bleed**: `[References, Para 48]` on Page 7 stretches from $x_0=41.2$ to $x_1=549.4$ (Width: 585.0).
    > *Excerpt*: "Pilot study of dietary fat restriction and flaxseed sup37. Miller WR, Dixon JM, Macfarlane L, Cameron D, plementation in men with prostate c"

### 📄 `Electroacupuncture frequency for chemotherapy-induced neuropathy in breast cancer a randomized controlled trial .pdf`
- **Publisher**: Unknown | **Pages**: 11 | **Total Anchors**: 109
  - ❌ **Cross-Column Bleed**: `[Discussion, Para 3]` on Page 9 stretches from $x_0=48.2$ to $x_1=550.2$ (Width: 595.3).
    > *Excerpt*: "• In the 2 Hz EA group, 13 patients experienced one adverse event, 4 patients experienced two adverse events, and 1 patient experienced four"

### 📄 `Impact of Ipsilateral Blood Draws, Injections, Blood Pressure Measurements, and Air Travel on the Risk of Lymphedema for Patients Treated for Breast Cancer.pdf`
- **Publisher**: Unknown | **Pages**: 9 | **Total Anchors**: 89
  - ❌ **Cross-Column Bleed**: `[References, Para 5]` on Page 7 stretches from $x_0=34.9$ to $x_1=424.5$ (Width: 585.0).
    > *Excerpt*: "strategies for investigation and treatment: A review. Delayed breast cellulitis: An evolving complication of Plast Surg Nurs 32:173-177, 201"
  - ❌ **Cross-Column Bleed**: `[References, Para 6]` on Page 7 stretches from $x_0=34.9$ to $x_1=547.9$ (Width: 585.0).
    > *Excerpt*: "19. Hayes SB, Freedman GM, Li T, et al: Does 37. Smith J: The practice of venepuncture in 1339-1346, 2006 axillary boost increase lymphedema"
  - ❌ **Cross-Column Bleed**: `[References, Para 8]` on Page 7 stretches from $x_0=34.9$ to $x_1=547.9$ (Width: 585.0).
    > *Excerpt*: "Breast Cancer Res Treat 142:59-67, 2013 40. Brennan MJ, Weitz J: Lymphedema 30 years org/pdfDocs/PP_Lymphedema_BC_Supplement.pdf 21. Ahmed R"
  - ❌ **Cross-Column Bleed**: `[References, Para 9]` on Page 7 stretches from $x_0=34.9$ to $x_1=434.1$ (Width: 585.0).
    > *Excerpt*: "Position AR: Risk factors for lymphedema in breast cancer 71:12-14, 1992 statement of the National Lymphedema Network:"
  - ❌ **Cross-Column Bleed**: `[References, Para 10]` on Page 7 stretches from $x_0=34.9$ to $x_1=547.9$ (Width: 585.0).
    > *Excerpt*: "survivors, the Iowa Women ’ s Health Study. Breast 41. Clark B, Sitzia J, Harlow W: Incidence and risk Lymphedema risk reduction practices. "
  - ❌ **Cross-Column Bleed**: `[References, Para 11]` on Page 7 stretches from $x_0=34.9$ to $x_1=547.9$ (Width: 585.0).
    > *Excerpt*: "Cancer Res Treat 130:981-991, 2011 of arm oedema following treatment for breast cancer: lymphnet.org/pdfDocs/nlnriskreduction.pdf A three-ye"
  - ❌ **Cross-Column Bleed**: `[References, Para 13]` on Page 7 stretches from $x_0=34.9$ to $x_1=547.9$ (Width: 585.0).
    > *Excerpt*: "42. Cemal Y, Pusic A, Mehrara BJ: Preventative Prevalence of lymphedema in women with breast Trends in risk reduction practices for the prev"

### 📄 `Improved survival in patients with end-stage cancer treated with coenzyme Q(10) and other antioxidants a pilot study.pdf`
- **Publisher**: MDPI | **Pages**: 11 | **Total Anchors**: 95
  - ❌ **Cross-Column Bleed**: `[References, Para 9]` on Page 9 stretches from $x_0=70.1$ to $x_1=406.2$ (Width: 476.2).
    > *Excerpt*: "• Received for publication 1 June 2009 • Accepted subject to revision 4 June 2009 • Revised accepted 13 October 2009 Copyright © 2009 Field "

### 📄 `Intl Journal of Cancer - 2024 - Chan - Post‐diagnosis dietary factors  supplement use and colorectal cancer prognosis  A.pdf`
- **Publisher**: Unknown | **Pages**: 26 | **Total Anchors**: 271
  - ❌ **Cross-Column Bleed**: `[Results, Para 48]` on Page 9 stretches from $x_0=98.8$ to $x_1=540.7$ (Width: 595.3).
    > *Excerpt*: "An overview of summary relative risks from linear dose – response meta-analyses of observational studies and the corresponding associations,"

### 📄 `Efficacy and safety of metronomic chemotherapy in maintenance therapy for metastatic colorectal cancer A systematic review of randomized controlled trials.pdf`
- **Publisher**: Unknown | **Pages**: 7 | **Total Anchors**: 68
  - ❌ **Cross-Column Bleed**: `[Results, Para 3]` on Page 3 stretches from $x_0=51.0$ to $x_1=560.5$ (Width: 594.0).
    > *Excerpt*: "3.4. The effectiveness of MC in mCRC MT All 4 selected studies included RCTs and had reported on the mPFS and mOS of the participants. Geng "

### 📄 `Metronomic Capecitabine Plus Aromatase Inhibitor as Initial Therapy in Patients With Hormone Receptor-Positive, Human Epidermal Growth Factor Receptor 2-Negative Metastatic Breast Cancer.pdf`
- **Publisher**: Unknown | **Pages**: 13 | **Total Anchors**: 125
  - ❌ **Cross-Column Bleed**: `[Introduction, Para 1]` on Page 2 stretches from $x_0=51.9$ to $x_1=536.0$ (Width: 585.0).
    > *Excerpt*: "citabine plus an aromatase inhibitor (AI) signi ﬁ cantly prolonged median progression-free survival to 20.9 months compared with 11.9 months"

### 📄 `Metronomic Chemotherapy for Metastatic Breast Cancer Treatment Clinical and Preclinical Data between Lights and Shadows.pdf`
- **Publisher**: MDPI | **Pages**: 18 | **Total Anchors**: 218
  - ❌ **Cross-Column Bleed**: `[Results, Para 65]` on Page 12 stretches from $x_0=166.1$ to $x_1=559.3$ (Width: 595.3).
    > *Excerpt*: "proﬁle is associated with well-documented clinical activity in various types of cancer and In a recently published systematic literature ana"
  - ❌ **Cross-Column Bleed**: `[Results, Para 66]` on Page 12 stretches from $x_0=166.0$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "event reporting were noted. Most of the studies used the NCI-CTCAE (any version) criteria, while seven used the WHO criteria. The authors em"
  - ❌ **Cross-Column Bleed**: `[Results, Para 67]` on Page 12 stretches from $x_0=166.4$ to $x_1=560.5$ (Width: 595.3).
    > *Excerpt*: "different regimens and schedules applied, even when the same drugs are used, the small number of patients enrolled in the different trials, "
