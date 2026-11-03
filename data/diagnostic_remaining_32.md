# Remaining 32 Failed Papers: Heuristic Multi-Dimensional Diagnostic

**Total Failed Papers Analyzed**: 32
**Total Critical Violations Extracted**: 65

## Executive Dimensional Breakdown

| Heuristic Dimension | Anomaly Count | Percentage | Key Signal Thresholds |
|---|---|---|---|
| **Dim 1: Web / Margin Timestamp & Running Artifact** | 5 | 7.7% | `y0 <= 0.045H` or `y1 >= 0.96H`, `font <= 8.0pt` |
| **Dim 2: Dense Statistical Matrix / Tabular Grid** | 4 | 6.2% | `density >= 0.16` or (`density >= 0.10` and `vgap <= 10pt`) |
| **Dim 3: Dense Abbreviation Key / Table Footnote** | 3 | 4.6% | `[A-Z]{2,}:` Abbr keys, `EC: Clinical stage; ER: ...` |
| **Dim 4: Trapped Section / Alternative Hierarchy** | 2 | 3.1% | Unnumbered Comment / Letter / Trapped Discussion |
| **Dim 5: Outlier Typography / Heading / Micro-Note** | 2 | 3.1% | `|font_diff| >= 1.5pt` (Distinct header / note font) |
| **Dim 6: Broad Multi-Column Span / Callout Flow** | 42 | 64.6% | `w_ratio >= 0.65` across center gutter |
| **Unclassified** | 7 | 10.8% | `w_ratio >= 0.65` across center gutter |

---

## Dim 1: Web / Margin Timestamp & Running Artifact (5 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **Breast Cancer Screening Strate...**<br>`[Methods, Para 5]` | P7 | `[118,15,587,24]` | 1.7% | 8.0pt (13.3pt) | 8.93pt | 'Breast Cancer Screening Strategies for Women With ATM, ' |
| **Nut, corn and popcorn consumpt...**<br>`[Results, Para 16]` | P7 | `[55,45,546,95]` | 0.0% | 7.0pt (7.0pt) | 7.98pt | 'NUTS, CORN, AND POPCORN AND DIVERTICULAR DISEASE pothes' |
| **Impact of thyroid hormone repl...**<br>`N/A` | P1 | `[0,0,0,0]` | 0.0% | 8.0pt (9.0pt) | 9.53pt | 'parse_and_index_pdf crashed: cannot access local variab' |
| **mortstatsh_1900-1904 mortality...**<br>`N/A` | P1 | `[0,0,0,0]` | 0.0% | 8.6pt (19.4pt) | 11.87pt | 'parse_and_index_pdf crashed: cannot access local variab' |
| **Estimated Lifetimes Gained fro...**<br>`[Introduction, Para 7]` | P5 | `[24,16,547,24]` | 9.7% | 10.0pt (10.0pt) | 0.0pt | '2/20/26, 3:10 PM Estimated Lifetime Gained With Cancer ' |


## Dim 2: Dense Statistical Matrix / Tabular Grid (4 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **Real-world impact of postmaste...**<br>`[Discussion, Para 11]` | P5 | `[45,414,448,465]` | 70.0% | 8.5pt (9.5pt) | 10.75pt | '2004 2005 2006 2007 2008 2009 2010 2011 2012 69.4% 71.2' |
| **Nut, corn and popcorn consumpt...**<br>`[Results, Para 26]` | P7 | `[55,234,465,245]` | 15.2% | 7.0pt (7.0pt) | 7.98pt | 'of the authors and do not necessarily represent the med' |
| **IACR Red Meat and Processed Me...**<br>`[Results, Para 794]` | P234 | `[83,196,481,517]` | 19.3% | 10.0pt (10.0pt) | 0.0pt | 'i iH Sa eae Bia i f Zea aE i a H i a a ess zo sSoe 34 r' |
| **Physical Health Decline after ...**<br>`[Results, Para 7]` | P4 | `[77,697,547,715]` | 20.0% | 10.0pt (10.0pt) | 0.0pt | 'without cancer were matched to breast cancer 1.7 (0.9-2' |


## Dim 3: Dense Abbreviation Key / Table Footnote (3 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **Metronomic Chemotherapy in Tri...**<br>`[Results, Para 17]` | P4 | `[50,225,407,257]` | 8.6% | 8.0pt (10.0pt) | 7.97pt | 'CTX 50 mg/day + Veliparib 60 mg once daily throughout a' |
| **Metronomic chemotherapy for no...**<br>`[Introduction, Para 28]` | P4 | `[56,568,540,587]` | 2.1% | 7.0pt (7.0pt) | 10.0pt | 'EC: Clinical stage; ER: Estrogen receptor; DX: Doxorubi' |
| **Metronomic chemotherapy for no...**<br>`[Methods, Para 33]` | P7 | `[56,394,540,403]` | 2.1% | 7.0pt (9.0pt) | 10.0pt | '5FU: 5-Fluoracil; E: Epirubicin, Ca: Carboplatin; T: Do' |


## Dim 4: Trapped Section / Alternative Hierarchy (2 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **Association of eating duration...**<br>`N/A` | P1 | `[0,0,0,0]` | 3.9% | 10.0pt (10.0pt) | 0.0pt | 'Paper has 8 pages and 58 Results anchors, but Discussio' |
| **Effects of blood pressure and ...**<br>`N/A` | P1 | `[0,0,0,0]` | 4.8% | 10.0pt (10.0pt) | 0.0pt | 'Paper has 12 pages and 65 Results anchors, but Discussi' |


## Dim 5: Outlier Typography / Heading / Micro-Note (2 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **ayers-et-al-2023-effectiveness...**<br>`[Introduction, Para 20]` | P5 | `[45,241,446,267]` | 3.6% | 7.5pt (9.5pt) | 9.01pt | '* Shaded rows are harm outcomes. Details of the ﬁ nding' |
| **What are the optimal mind-body...**<br>`[Methods, Para 7]` | P3 | `[51,494,527,514]` | 5.0% | 8.0pt (9.5pt) | 10.94pt | 'evidence-based complementary therapy for clinical adopt' |


## Dim 6: Broad Multi-Column Span / Callout Flow (42 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **Cancer Medicine - 2025 - Modi ...**<br>`[Abstract, Para 3]` | P2 | `[53,40,543,66]` | 0.0% | 9.0pt (9.0pt) | 12.45pt | 'Conclusion: These findings emphasise the need for caref' |
| **Respiratory viral infections a...**<br>`[Methods, Para 89]` | P47 | `[25,567,556,654]` | 3.6% | 8.0pt (9.0pt) | 9.6pt | 'Data analysis Data Processing for single cell RNA-seq a' |
| **No impact of fish oil suppleme...**<br>`[Results, Para 33]` | P7 | `[42,723,465,740]` | 0.0% | 7.0pt (7.0pt) | 9.0pt | '↑) Statistically significant increase in the fish oil g' |
| **The benefits and risks of meno...**<br>`[Abstract, Para 2]` | P2 | `[63,93,518,156]` | 0.7% | 10.0pt (9.8pt) | 12.0pt | 'Early acceptance of MHT not only reduces the risk of al' |
| **Hypercalcemia, hypercalciuria,...**<br>`[Discussion, Para 11]` | P9 | `[40,517,545,537]` | 2.1% | 8.0pt (8.0pt) | 9.98pt | '4 For studies with 4 arms, we combined 2 arms into appr' |
| **Cardiac Troponins and Cardiova...**<br>`[Introduction, Para 15]` | P51 | `[139,153,693,185]` | 0.7% | 8.0pt (8.0pt) | 9.18pt | 'Explain the medical context (including whether diagnost' |
| **Cardiac Troponins and Cardiova...**<br>`[Methods, Para 14]` | P51 | `[139,210,704,242]` | 1.4% | 8.0pt (8.0pt) | 6.9pt | 'Methods, paragraph 1; Describe the study design or sour' |
| **Cardiac Troponins and Cardiova...**<br>`[Methods, Para 15]` | P51 | `[147,238,701,265]` | 2.9% | 8.0pt (8.0pt) | 6.87pt | '1-4 Source of data Specify the key study dates, includi' |
| **Cardiac Troponins and Cardiova...**<br>`[Discussion, Para 17]` | P52 | `[146,375,703,397]` | 1.4% | 8.0pt (8.0pt) | 4.62pt | 'paragraphs Discussion, paragraph Implications 20 D;V Di' |
| **Menopausal hormone therapy and...**<br>`[Introduction, Para 3]` | P1 | `[45,531,559,610]` | 0.7% | 9.0pt (9.0pt) | 9.98pt | 'When reaching menopause, most women experience menoIn t' |
| **Alzheimer s   Dementia - 2025 ...**<br>`[Results, Para 12]` | P6 | `[92,48,528,100]` | 4.3% | 8.0pt (8.0pt) | 5.48pt | 'Associations between cumulative average three-component' |
| **Brain Abnormalities in Childre...**<br>`[Results, Para 7]` | P4 | `[72,347,533,382]` | 2.1% | 7.0pt (8.0pt) | 8.98pt | 'Participants with exposure The transformed variables we' |
| **Nut, corn and popcorn consumpt...**<br>`[Results, Para 18]` | P7 | `[55,90,545,107]` | 1.4% | 7.0pt (7.0pt) | 7.98pt | '15. Floch MH, Bina I. The natural history of divercompl' |
| **Nut, corn and popcorn consumpt...**<br>`[Results, Para 19]` | P7 | `[55,98,546,118]` | 3.0% | 7.0pt (7.0pt) | 7.98pt | 'ticulitis: fact and theory. J Clin Gastroenterol . 2004' |
| **Nut, corn and popcorn consumpt...**<br>`[Results, Para 23]` | P7 | `[55,122,545,141]` | 5.0% | 7.0pt (7.0pt) | 7.98pt | 'ology and fiber. J Clin Gastroenterol . 2006;40 noted e' |
| **Nut, corn and popcorn consumpt...**<br>`[Results, Para 25]` | P7 | `[55,139,546,176]` | 2.1% | 7.0pt (7.0pt) | 8.08pt | '17. Laine L, Connors LG, Reicin A, et al. Serious lower' |
| **Safe, mild ultraviolet‐B expos...**<br>`[Abstract, Para 20]` | P2 | `[46,712,551,733]` | 3.6% | 8.0pt (8.0pt) | 10.93pt | 'FIG URE 1 Ultraviolet radiation conversion of 7-dehydro' |
| **Soy Combined.pdf**<br>`[Abstract, Para 62]` | P169 | `[58,433,554,559]` | 1.4% | 9.0pt (9.0pt) | 10.66pt | '2.2 Association of soy isoflavone intake and breast can' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 21]` | P15 | `[166,734,560,769]` | 2.9% | 9.9pt (9.0pt) | 12.57pt | 'The hallmark case report of Hercbergs and Leith in 1993' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 29]` | P17 | `[52,384,529,431]` | 2.9% | 9.0pt (9.0pt) | 6.75pt | 'Results Case report of a 69-years-old male patient with' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 34]` | P17 | `[48,547,548,613]` | 2.9% | 9.0pt (9.0pt) | 8.43pt | 'Circadian rhythm synchronized to the 24 h environmental' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 44]` | P18 | `[48,393,545,424]` | 7.4% | 9.0pt (9.0pt) | 10.96pt | 'Prospective cohort study of a community-dwelling popula' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 45]` | P18 | `[48,415,553,495]` | 2.9% | 8.9pt (9.0pt) | 10.96pt | 'participants aged 25–84 years in Western Australia to a' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 47]` | P18 | `[50,517,518,552]` | 5.0% | 9.0pt (9.0pt) | 9.69pt | 'TR β 1 methylation detected in 47% of NSCLC surgical Re' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 49]` | P18 | `[166,639,561,687]` | 0.7% | 10.0pt (9.0pt) | 12.55pt | 'In the era of precision oncology, a novel aspect of the' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 67]` | P20 | `[48,212,440,260]` | 3.6% | 9.0pt (9.0pt) | 8.43pt | 'All patients were asymptomatic. Prospective observation' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 70]` | P20 | `[48,333,528,375]` | 5.0% | 9.0pt (9.0pt) | 8.43pt | 'Incidence of TKI-induced hypothyroidism: 26%. Retrospec' |
| **The Intriguing Thyroid Hormone...**<br>`[Results, Para 72]` | P20 | `[48,409,554,444]` | 5.0% | 9.0pt (9.0pt) | 9.69pt | 'Incidence of hypothyroidism related to TKI targeting VE' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 27]` | P36 | `[166,734,560,769]` | 2.9% | 9.9pt (9.0pt) | 12.57pt | 'The hallmark case report of Hercbergs and Leith in 1993' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 35]` | P38 | `[52,384,529,431]` | 2.9% | 9.0pt (9.0pt) | 6.75pt | 'Results Case report of a 69-years-old male patient with' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 40]` | P38 | `[48,547,548,613]` | 2.9% | 9.0pt (9.0pt) | 8.43pt | 'Circadian rhythm synchronized to the 24 h environmental' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 50]` | P39 | `[48,393,545,424]` | 7.4% | 9.0pt (9.0pt) | 10.96pt | 'Prospective cohort study of a community-dwelling popula' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 51]` | P39 | `[48,415,553,495]` | 2.9% | 8.9pt (9.0pt) | 10.96pt | 'participants aged 25–84 years in Western Australia to a' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 53]` | P39 | `[50,517,518,552]` | 5.0% | 9.0pt (9.0pt) | 9.69pt | 'TR β 1 methylation detected in 47% of NSCLC surgical Re' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 55]` | P39 | `[166,639,561,687]` | 0.7% | 10.0pt (9.0pt) | 12.55pt | 'In the era of precision oncology, a novel aspect of the' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 73]` | P41 | `[48,212,440,260]` | 3.6% | 9.0pt (9.0pt) | 8.43pt | 'All patients were asymptomatic. Prospective observation' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 76]` | P41 | `[48,333,528,375]` | 5.0% | 9.0pt (9.0pt) | 8.43pt | 'Incidence of TKI-induced hypothyroidism: 26%. Retrospec' |
| **Thyroid & Cancer - All 2025-12...**<br>`[Results, Para 78]` | P41 | `[48,409,554,444]` | 5.0% | 9.0pt (9.0pt) | 9.69pt | 'Incidence of hypothyroidism related to TKI targeting VE' |
| **Association of statins use and...**<br>`[Introduction, Para 33]` | P3 | `[37,508,559,654]` | 1.4% | 10.0pt (10.0pt) | 0.0pt | '2.6. Covariates additive and multiplicative interaction' |
| **Tamoxifen for the prevention.pdf**<br>`[Results, Para 8]` | P3 | `[42,506,569,518]` | 4.3% | 10.0pt (10.0pt) | 0.0pt | 'the number of person-years in the tamoxifen group (PY,q' |
| **Differential impact of PPI on ...**<br>`[Abstract, Para 6]` | P1 | `[37,626,558,679]` | 0.0% | 10.0pt (10.0pt) | 0.0pt | 'Interpretation Baseline exposure to proton pump inhibit' |
| **Low-Dose Lithium for Mild Cogn...**<br>`[Abstract, Para 10]` | P1 | `[84,564,536,608]` | 0.0% | 10.0pt (10.0pt) | 0.0pt | 'CONCLUSIONS AND RELEVANCE This pilot randomized clinica' |


## Unclassified (7 anomalies)

| Paper / Anchor | Pg | BBox [x0,y0,x1,y1] | Num Density | Font (Body) | VGap | Excerpt |
|---|---|---|---|---|---|---|
| **Simple sugar intake and cancer...**<br>`[Abstract, Para 4]` | P2 | `[202,111,557,138]` | 0.0% | 7.3pt (8.1pt) | 9.58pt | 'Conclusions: Simple sugar intake in drinks and fruit ju' |
| **Simple sugar intake and cancer...**<br>`[Abstract, Para 5]` | P2 | `[207,140,557,157]` | 6.4% | 7.3pt (8.1pt) | 7.25pt | '© 2021 The Authors. Published by Elsevier Ltd. This is ' |
| **No impact of fish oil suppleme...**<br>`[Results, Para 8]` | P4 | `[34,116,370,124]` | 1.6% | 7.0pt (7.0pt) | 8.02pt | 'Summary of studies investigating the haemostatic effect' |
| **No impact of fish oil suppleme...**<br>`[Methods, Para 32]` | P7 | `[42,115,385,123]` | 0.0% | 7.0pt (7.0pt) | 8.02pt | 'Summary of studies investigating clinical bleeding and ' |
| **Cardiac Troponins and Cardiova...**<br>`[Introduction, Para 16]` | P51 | `[147,177,686,208]` | 0.7% | 8.0pt (8.0pt) | 9.45pt | 'Background and existing models. objectives Specify the ' |
| **Cardiac Troponins and Cardiova...**<br>`[Discussion, Para 16]` | P52 | `[146,361,689,383]` | 1.4% | 8.0pt (8.0pt) | 6.93pt | 'Interpretation Give an overall interpretation of the re' |
| **Cardiac Troponins and Cardiova...**<br>`[Discussion, Para 18]` | P52 | `[139,394,670,431]` | 3.6% | 8.0pt (8.0pt) | 9.65pt | '3, 4 Other information Supplementary Provide informatio' |

