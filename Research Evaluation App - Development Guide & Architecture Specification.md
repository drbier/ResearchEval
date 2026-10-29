# **Research Evaluation App: Architecture Specification & Developer Guide**

# **1\. System Overview & Core Objectives**

## **Persona and Purpose**

The Research Evaluation App acts as an **Expert Clinical Research Appraiser**, serving as an objective, highly specialized peer to busy medical clinicians. The system ingests primary medical literature, clinical trial protocols, systematic reviews, and real-world evidence (RWE) studies, processing them into structured, high-density analytical summaries tailored for rapid, evidence-based decision-making.

## **Core Directive**

The system executes a deterministic analysis pipeline to transform complex medical documents into a standardized top-down analysis starting with the article title, incorporating inline source coordinate links, delivering assertive appraisal, and terminating with Bibliographic Data.

Each evaluation must rigorously incorporate inline source coordinate links (e.g., `[Doc_Header]`, `[Methods, Para 3]`, `[Results, Table 2]`) to map every claim directly to its exact source coordinate anchor.

## **Strict Negative Constraints**

To maintain executive tone and regulatory clarity, the generation pipeline must strictly enforce three core operational boundaries:

* **NO Medical Disclaimers:** Do not generate general liability disclaimers, medical warnings, or contextual disclaimers under any circumstances (e.g., "This synthesis is for informational purposes only..."). Disclaimers are managed exclusively by the client-side UI presentation layer.  
* **NO Conversational Fillers:** Do not produce follow-up questions, closing pleasantries, polite intros, or chat-oriented transitional dialogue (e.g., "I hope this analysis helps," "Let me know if you need...").  
* **NO Unsupported Clinical Practice Recommendations:** The system provides methodological appraisal, risk-of-bias evaluation, and statistical context. It must never issue direct therapeutic mandates or unsupported practice recommendations that extend beyond the data reported in the parsed manuscript.

---

# **2\. Multi-Stage Deterministic Pipeline Architecture**

To guarantee zero hallucination, eliminate context drift, and ensure reproducible outputs, the application executes via a three-stage deterministic architecture.+-----------------------------------------------------------------------------------+

\| STAGE 1: INGESTION & COORDINATE INDEXING                                          \|

\|---\|

\+-----------------------------------------------------------------------------------+

                                          \|

                                          v

\+-----------------------------------------------------------------------------------+

\| STAGE 2: CLASSIFICATION, TRIAGE & RULE SELECTION                                  \|

\| Block Parsing \-\> Triage Matrix Evaluation \-\> FW\_A..FW\_H \+ Sub-Feature Tags        \|

\+-----------------------------------------------------------------------------------+

                                          \|

                                          v

\+-----------------------------------------------------------------------------------+

\| STAGE 3: SCOPED DETERMINISTIC SYNTHESIS & GENERATION                             \|

\| Dynamic Prompt Construction (Indexed Text \+ Matched Rules \+ Framework Schema)     \|

\+-----------------------------------------------------------------------------------+

## **Stage 1: Ingestion & Coordinate Indexing**

1. **Parsing:** The ingestion engine parses incoming PDF, HTML, or raw text files into discrete structural and semantic blocks: Title/Header, Abstract, Introduction, Methods, Results, Discussion, Tables, and Figures.  
2. **Anchor Assignment:** Each parsed block is assigned a immutable coordinate anchor using standard syntax:  
   * `[Doc_Header]` for document-level bibliographic metadata.  
   * `[Section, Para X]` for textual paragraphs within specific sections (e.g., `[Methods, Para 4]`).  
   * `[Section, Table Y]` or `[Section, Fig Z]` for structured display items (e.g., `[Results, Table 2]`).  
3. **Coordinate Map:** The output of Stage 1 is an indexed JSON payload (`indexed_doc.json`) holding the raw text bound to explicit coordinate anchors.

## **Stage 2: Classification, Triage & Rule Selection**

1. **Matrix Evaluation:** The classification module evaluates the parsed `Doc_Header`, `Abstract`, and `Methods` sections against the **Master Triage Matrix**.  
2. **Framework ID Resolution:** Assigns exactly one primary Framework ID (`FW_A` through `FW_H`) based on study design triggers and explicit exclusion rules.  
3. **Sub-Feature Tagging:** Scans for concurrent analytical requirements (e.g., non-inferiority margins, ctDNA correlatives, PRO endpoints, safety signals) and appends multi-label sub-feature tags (e.g., `+TAG_NON_INFERIORITY`, `+TAG_BIOMARKER_PROGNOSTIC`, `+TAG_CONSORT_PRO`).

## **Stage 3: Scoped Deterministic Synthesis & Generation**

1. **Prompt Assembly:** Constructs a minimal, scoped context window containing:  
   * The indexed text payload from Stage 1\.  
   * The matched Framework Output Schema (`schemadb.json`).  
   * Only those specific methodological rules triggered in Stage 2 (`rulesdb.json`).  
   * Target plain-language statistical definitions (`lexicondb.json`).  
2. **Synthesis Engine:** Generates the structured evaluation using the target schema.  
3. **Post-Processing Sanitization:** Runs a regular expression and string validation filter over the generated response to strip any accidental disclaimers or conversational phrasing before returning the payload to the UI layer.

---

# **3\. Data Tables & Rule Bases for Implementation**

## **Table 1: Master Triage & Study Classification Matrix**

| Framework ID | Primary Study Classification | Key Diagnostic Triggers (Include) | Explicit Exclusion Criteria | Core Methodological Guidelines |
| :---- | :---- | :---- | :---- | :---- |
| **FW\_A** | Superiority Randomized Controlled Trial (RCT) | Prospected trial, parallel assignment, randomization explicitly described, primary endpoint testing superiority. | Cluster RCTs with economic endpoints as primary; non-inferiority designs. | CONSORT 2010, RoB 2, CONSORT Harms 2022\. |
| **FW\_B** | Systematic Review & Meta-Analysis | PRISMA flow diagram, pooled effect sizes (Forest plot), Cochrane risk of bias aggregate, search strategy across PubMed/Embase. | Single narrative review without pooled quantitative synthesis; scoping reviews without quality appraisal. | PRISMA 2020, AMSTAR 2, GRADE. |
| **FW\_C** | Observational / Real-World Evidence (RWE) | Cohort studies, case-control studies, cross-sectional design, prospective/retrospective registry analysis, propensity-score matching. | Interventional randomized allocation; single case reports. | STROBE, RECORD (for health data), ROBINS-I. |
| **FW\_D** | Biomarker & Diagnostic Accuracy Study | Assessment of predictive/prognostic biomarkers, assay performance (ROC/AUC, sensitivity, specificity, PPV/NPV), ctDNA liquid biopsy validation. | Pre-clinical in vitro assays without human patient clinical outcome correlation. | REMARK (prognostic), STARD 2015 (diagnostic accuracy). |
| **FW\_E** | Clinical Trial Protocol | Methodological outline of uncompleted trial, phase I-III prospective protocol publication, statistical analysis plan (SAP) standalone. | Completed trials with published results; letters to the editor. | SPIRIT 2013, SPIRIT-PRO. |
| **FW\_F** | Non-Inferiority / Equivalence RCT | Explicit non-inferiority margin (\$\\Delta\$), pre-specified non-inferiority hypothesis, dual Intent-to-Treat (ITT) and Per-Protocol (PP) evaluation requirement. | Superiority-only trials; phase I dose-finding without non-inferiority margins. | Extended CONSORT for Non-Inferiority Trials. |
| **FW\_G** | Health Economics & Outcomes Research | Cost-effectiveness analysis (CEA), cost-utility analysis (CUA), Incremental Cost-Effectiveness Ratio (ICER), Quality-Adjusted Life Years (QALY). | Clinical efficacy outcomes without explicit economic or utility modeling. | CHEERS 2022\. |
| **FW\_H** | Narrative Review & Expert Opinion | Literature overviews lacking systematic search syntax, narrative summaries, state-of-the-art clinical updates, commentary articles. | Quantitative systematic reviews with meta-analytic pooling. | SANRA (Scale for Assessment of Narrative Review Articles). |

## **Table 2: Critical Appraisal & Methodological Rules Engine**

| Rule ID | Target Domain / Standard | Operational Trigger Criteria | Directional Biases Evaluated | Mandatory Appraisal Action in Engine |
| :---- | :---- | :---- | :---- | :---- |
| **R\_CONSORT\_01** | Allocation Confounding | RCT lacking explicit detail on sequence generation or allocation concealment. | Selection Bias (overestimates treatment effect size by \~15-30%). | Flag baseline balance tables; explicitly demand details on concealment mechanism; cite `[Methods, Para X]`. |
| **R\_CONSORT\_HARMS** | Safety Reporting | Any trial reporting grade 3-5 adverse events or treatment discontinuation. | Selective Reporting Bias (underreporting subtle or long-term toxicities). | Extract absolute event rates; contrast drug-related vs total toxicities; check for pooled safety groupings that hide severe single-organ toxicities. |
| **R\_CONSORT\_PRO** | Patient-Reported Outcomes | Study secondary/primary endpoints including HRQoL, PROMs, or pain scales. | Attrition Bias / Missing Not at Random (MNAR) due to progressive disease. | Inspect completion rates over time; verify if instrument is validated in the target indication; verify handling of missing data. |
| **R\_ROB2\_01** | Risk of Bias 2 (Crossover/Missing) | Missing outcome data \> 10% without robust imputation (e.g., last observation carried forward used). | Attrition Bias (artificially inflates responders if dropouts are disease-related). | Downgrade study quality score; check for sensitivity analysis under Missing Not at Random assumptions. |
| **R\_FDA\_OS\_01** | FDA Guidance on Survival | Overall Survival (OS) evaluated in presence of post-progression crossover (\>20%). | Dilution Bias (masks true OS benefit of primary therapy due to effective sequence therapy). | Assess if crossover was pre-planned; demand censored or rank-preserving structural failure time (RPSFT) adjusted analyses. |
| **R\_IRECIST\_01** | Immunotherapy Outcomes | Immunotherapy trial reporting atypical response patterns or progression. | Pseudo-progression Bias (premature discontinuation of active agent). | Distinguish unconfirmed progressive disease (iUPD) vs confirmed progressive disease (iCPD); audit imaging schedules. |
| **R\_SUBGROUP\_01** | Subgroup Analysis | Multi-group post-hoc analysis or claims of efficacy in small sub-cohorts. | Type I Error Inflation (False Positive finding through multiple testing). | Enforce test for interaction (p-interaction); downgrade post-hoc claims unless pre-specified and stratified. |
| **R\_GRADE\_01** | Certainty of Evidence | Systematic reviews evaluating quality across pooled studies. | Imprecision, Inconsistency, Indirectness, Publication Bias. | Assign certainty rating (High, Moderate, Low, Very Low) per endpoint; justify downgrades with quantitative metrics. |
| **R\_STROBE\_01** | Confounding in RWE | Observational study comparing non-randomized treatment cohorts. | Selection Bias & Immortal Time Bias; Information Bias. | Verify propensity score adjustments or multivariable models; check for immortal time windows in exposure definitions. |
| **R\_REMARK\_01** | Prognostic Biomarkers | Claims of prognostic/predictive biomarker utility in tissue/fluid. | Overfitting / Optimism Bias; Assay Variability Bias. | Check for independent validation cohort (internal cross-validation is insufficient); audit cut-point selection (pre-fixed vs optimal cutpoint searching). |
| **R\_NI\_MARGIN\_01** | Non-Inferiority Design | Non-inferiority claim based solely on Intent-To-Treat (ITT) analysis. | Bias Toward Equivalence (ITT dilutes differences, artificially supporting non-inferiority). | Mandatory dual analysis evaluation: demand BOTH Per-Protocol (PP) and ITT. If PP fails or is omitted, reject non-inferiority claim. |
| **R\_CHEERS\_01** | Economic Evaluation | Cost-effectiveness modeling based on trial primary endpoints. | Time Horizon Bias; Unrealistic Discounting / Parameter Uncertainty. | Check if time horizon matches disease lifecycle; audit source of utility weights (EuroQol EQ-5D vs direct estimate); check sensitivity analyses. |

## **Table 3: Clinician Plain-Language Statistical & Methodological Lexicon**

\+--------------------------------------------------------------------------------------------------------------------------------------------------------+

\| CONCEPT                     \| PLAIN-LANGUAGE CLINICAL DEFINITION               \| CRITICAL CAVEAT / CLINICAL WARNING         \| STANDARD FORMULA          \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Hazard Ratio (HR)           \| Relative rate of an event occurring in treatment \| HR assumes constant proportional hazard    \| HR \= (Hazard Exp) /       \|

\|                             \| vs control arm at any given point in time.       \| over time. Non-proportional hazards invalidate\|    (Hazard Control)       \|

\|                             \| HR \< 1.0 indicates risk reduction in treatment.  \| standard log-rank test interpretations.    \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Relative Risk (RR) vs       \| RR is the ratio of absolute risk in exposed vs   \| OR overestimates relative risk when the   \| RR \= \[a/(a+b)\] / \[c/(c+d)\]\|

\| Odds Ratio (OR)             \| unexposed. OR is the odds of event in exposed vs \| baseline outcome occurrence is common      \| OR \= (a\*d) / (b\*c)        \|

\|                             \| unexposed.                                       \| (\> 10%).                                   \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Heterogeneity (I²)          \| Percentage of variation across studies in meta-  \| I² between 50-90% represents substantial    \| I² \= \[(Q \- df) / Q\] \* 100 \|

\|                             \| analysis due to true study heterogeneity rather  \| heterogeneity; pooling data via fixed-effects \|                         \|

\|                             \| than chance alone.                               \| models under high I² is invalid.           \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Minimal Important           \| Smallest change in an outcome score that         \| Statistical significance (p \< 0.05) does   \| Context dependent         \|

\| Difference (MID)            \| patients perceive as beneficial or harmful.      \| NOT equal clinical relevance if point      \| (Anchor or Distribution)  \|

\|                             \|                                                  \| estimate fails to meet MID threshold.      \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| iRECIST: iUPD vs iCPD       \| Specialized immune response criteria. Unconfirmed\| Tumor flare or pseudo-progression can     \| iCPD requires confirmation\|

\|                             \| Progression (iUPD) requires repeated scan to    \| mimic progression; discontinuing therapy at\| 4-8 weeks post iUPD with  \|

\|                             \| confirm True Progression (iCPD).                 \| iUPD may cause premature trial dropouts.   \| target lesion growth.     \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Prognostic vs Predictive    \| Prognostic: indicates patient outcome regardless \| Confounding marker type leads to inappropriate\| Prognostic \= Main Effect  \|

\| Biomarker                   \| of treatment. Predictive: predicts likelihood of  \| targeted therapy selection in unselected   \| Predictive \= Interaction   \|

\|                             \| response to a specific therapy.                  \| populations.                               \| Term                      \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| ctDNA / Liquid Biopsy       \| Circulating tumor DNA shed into plasma used to    \| High risk of false negatives (low DNA shed);\| Variant Allele Fraction   \|

\|                             \| detect minimal residual disease (MRD) or somatic \| CHIP (Clonal Hematopoiesis of Indeterminate \| (VAF) % calculation       \|

\|                             \| alterations.                                     \| Potential) creates false positive mutations\|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Master Protocols            \| Overarching protocol umbrella evaluating         \| Sharing control arms across sub-protocols   \| Multi-arm multi-stage     \|

\| (Basket/Umbrella/Platform)  \| multiple therapies or diseases (e.g., Basket,    \| requires strict temporal matching to prevent\| adaptive design           \|

\|                             \| Umbrella, Platform trials).                      \| historical control bias.                   \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| Non-Inferiority Margin (Δ)  \| Maximum acceptable threshold by which novel      \| Margin must be pre-specified based on      \| Null Hypothesis:          \|

\|                             \| intervention can be worse than standard control  \| historical control data; setting margin    \| Control \- Test \>= Δ       \|

\|                             \| while maintaining clinical utility.              \| too wide guarantees false non-inferiority. \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

\| ICER / QALY                 \| Incremental Cost-Effectiveness Ratio calculates  \| QALYs may fail to capture subtle qualitative\| ICER \= (Cost A \- Cost B) /\|

\|                             \| economic cost per Quality-Adjusted Life Year     \| disease burdens or rare toxicities.        \| (QALY A \- QALY B)         \|

\|                             \| gained by new intervention.                      \|                                            \|                           \|

\+-----------------------------+--------------------------------------------------+--------------------------------------------+---------------------------+

## **Table 4: Adaptive Framework Output Schema**

\+---------------------------------------------------------------------------------------------------------------------------------------------------------+

\| FRAMEWORK ID \| SCHEMA STRUCTURE (EXACT HEADING SEQUENCE)          \| REQUIRED ELEMENTS                               \| NEGATIVE CONSTRAINTS      \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_A         \| \# \[Article Title\]                                  \| \- Primary/Secondary Endpoints with CIs & HRs    \| NO missing coordinate     \|

\| (Superiority \| \#\# Executive Appraisal & Baseline Rigor            \| \- Methodological Risk of Bias (RoB 2\)           \|   anchors on key data.    \|

\|  RCT)        \| \#\# Primary Efficacy & Safety Evaluation            \| \- Absolute Risk Reduction & NNT                 \| NO unreferenced baseline  \|

\|              \| \#\# Methodological Flaws & Risk of Bias             \| \- Absolute Safety Event Rates                   \|   imbalances.             \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \| NO casual language.       \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_B         \| \# \[Article Title\]                                  \| \- Literature Search Strategy & Criteria         \| NO narrative pooling      \|

\| (Meta-       \| \#\# Meta-Analysis Quality & Heterogeneity           \| \- Forest Plot Summary & Heterogeneity (I²)      \|   without checking        \|

\|  Analysis)   \| \#\# Pooled Efficacy & Safety Outcomes               \| \- Publication Bias Evaluation (Funnel/Egger)    \|   heterogeneity scores.   \|

\|              \| \#\# GRADE Evidence Certainty Analysis               \| \- GRADE Ratings per Outcome Table               \| NO implicit assumptions.  \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_C         \| \# \[Article Title\]                                  \| \- Study Cohort & Confounding Adjustment         \| NO causal claims in       \|

\| (Observational\| \#\# Observational Cohort & Confounding Analysis     \| \- Propensity Matching / Multivariable Models    \|   purely observational    \|

\| / RWE)       \| \#\# Key Real-World Findings & Associations          \| \- Assessment of Unmeasured Confounders          \|   data without caveats.   \|

\|              \| \#\# Methodological Limitations & Bias Evaluation   \| \- Residual Bias Identification                  \| NO omitted match stats.   \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_D         \| \# \[Article Title\]                                  \| \- Biomarker Type (Prognostic vs Predictive)     \| NO clinical utility claims\|

\| (Biomarker / \| \#\# Biomarker Utility & Assay Technical Validation  \| \- Diagnostic Accuracy (Sens, Spec, AUC, PPV)    \|   lacking independent     \|

\|  Diagnostic) \| \#\# Clinical Outcome Association & Correlatives     \| \- Cut-point Selection Criteria & Optimization   \|   cohort validation.      \|

\|              \| \#\# Technical Limits & Methodological Assessment    \| \- Analytical Sensitivity & Limit of Detection   \| NO vague assay metrics.   \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_E         \| \# \[Article Title\]                                  \| \- Trial Rationale & Proposed Methodology        \| NO extraction of non-     \|

\| (Trial       \| \#\# Protocol Design & Endpoint Architecture         \| \- Sample Size Power Calculation                 \|   existent clinical trial \|

\|  Protocol)   \| \#\# Statistical Power & Planned Analysis            \| \- Planned interim analyses & Stopping Rules     \|   efficacy results.       \|

\|              \| \#\# Potential Methodological Pitfalls               \| \- Feasibility & Ethical Constraints             \| NO speculative data.      \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_F         \| \# \[Article Title\]                                  \| \- Pre-specified Margin (Δ) & Rationale          \| NO acceptance of NI claim \|

\| (Non-        \| \#\# Non-Inferiority Design & Margin Rigor           \| \- Per-Protocol (PP) vs ITT Analysis Divergence  \|   based on ITT alone.     \|

\|  Inferiority)\| \#\# Efficacy Bounds & Margin Testing                \| \- Upper Bound 95% CI vs Margin Comparison       \| NO omitted margin values. \|

\|              \| \#\# Protocol Adherence & Methodological Critique    \| \- Conclusion on Efficacy / Superiority Switch   \|                           \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_G         \| \# \[Article Title\]                                  \| \- Model Structure & Time Horizon                \| NO health economic claims \|

\| (Health      \| \#\# Economic Model Architecture & Assumptions       \| \- ICER per QALY / DALY Gained                   \|   without explicit        \|

\|  Economics)  \| \#\# Cost-Effectiveness & Utility Estimates          \| \- Sensitivity Analyses (Deterministic/Prob)     \|   discounting rate state. \|

\|              \| \#\# Model Vulnerabilities & Sensitivity Critique    \| \- Thresholds for Willingness-To-Pay (WTP)       \| NO unreferenced costs.    \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

\| FW\_H         \| \# \[Article Title\]                                  \| \- Scope & Literature Coverage Breadth           \| NO treatment efficacy     \|

\| (Narrative   \| \#\# Narrative Synthesis & Critical Overview         \| \- Unsystematic Search Vulnerability             \|   claims presented as     \|

\|  Review)     \| \#\# Quality of Literature & Expert Consensus        \| \- Critical Gaps & Unsupported Claims            \|   level 1 evidence.       \|

\|              \| \#\# Expert Opinion Critique                         \| \- Conflict of Interest / Expert Bias Assessment \| NO missing COI check.     \|

\|              \| \#\# Bibliographic Data                              \| \- Full Citation with PubMed ID / DOI            \|                           \|

\+--------------+----------------------------------------------------+-------------------------------------------------+---------------------------+

## **Table 5: Ingestion Chunking & Provenance Coordinate Anchor Schema**

\+-----------------------------------------------------------------------------------------------------------------------------------------------+

\| SOURCE DOMAIN          \| INGESTION CHUNKING RULE                             \| PROVENANCE COORDINATE ANCHOR FORMAT                            \|

\+------------------------+-----------------------------------------------------+----------------------------------------------------------------+

\| Document Header        \| First 500 tokens of file; includes title, authors,   \| \[Doc\_Header\]                                                   \|

\|                        \| journal, year, DOI, affiliation.                    \|                                                                \|

\+------------------------+-----------------------------------------------------+----------------------------------------------------------------+

\| Body Text Paragraphs   \| Split by structural section tag; bounded by single  \| \[{Section\_Name}, Para {X}\]                                     \|

\|                        \| paragraph breaks (\\n\\n).                            \| Example: \[Methods, Para 3\], \[Discussion, Para 12\]              \|

\+------------------------+-----------------------------------------------------+----------------------------------------------------------------+

\| Data Tables            \| Converted to markdown table format or key-value     \| \[{Section\_Name}, Table {Y}\]                                    \|

\|                        \| keyframe; preserved in-line with original index.    \| Example: \[Results, Table 2\]                                    \|

\+------------------------+-----------------------------------------------------+----------------------------------------------------------------+

\| Figure Captions        \| Processed as discrete text block; paired with image \| \[{Section\_Name}, Fig {Z}\]                                      \|

\|                        \| metadata if present.                                \| Example: \[Results, Fig 1\]                                      \|

\+------------------------+-----------------------------------------------------+----------------------------------------------------------------+

\| Supplementary Files    \| External appendiceal text; indexed under distinct   \| \[Supp\_{File\_ID}, Para {X}\]                                     \|

\|                        \| supplementary tag.                                  \| Example: \[Supp\_Appendix1, Para 4\]                              \|

\+------------------------+-----------------------------------------------------+----------------------------------------------------------------+

---

# **4\. Implementation Guidelines & Edge-Case Safeguards**

## **Multi-Label & Hybrid Design Handling**

When processing complex hybrid study designs, Antigravity must execute multi-label tag association during Stage 2:

1. **Primary Framework Assignment:** The engine assigns a single root framework based on the primary outcome hypothesis. For instance, an RCT evaluating overall survival with a non-inferiority secondary outcome maps to **FW\_F** (Non-Inferiority). An RCT evaluating OS with a concurrent ctDNA exploratory biomarker maps to **FW\_A** (Superiority RCT) with sub-tag `+TAG_BIOMARKER`.  
2. **Rule Injector Mechanics:** Sub-feature tags force the rule engine to dynamically append secondary rule modules into Stage 3 context:  
   * If `+TAG_NON_INFERIORITY` is present: Inject `R_NI_MARGIN_01` into the prompt scope.  
   * If `+TAG_BIOMARKER` is present: Inject `R_REMARK_01` into the prompt scope.  
   * If `+TAG_PRO` is present: Inject `R_CONSORT_PRO` into the prompt scope.

## **Relegation to Supplementary Materials vs True Methodological Omission**

To prevent false-negative quality flags, Antigravity must distinguish between true methodological omissions and information relegated to supplementary files:

1. **Supplementary Verification Query:** Before triggering a high-severity bias flag (e.g., flagging an absent allocation concealment description or missing protocol deviation table), the system checks for index anchors labeled `[Supp_AppendixX, Para Y]`.  
2. **Graded Reporting Syntax:**  
   * If method is present in main manuscript: Cite `[Methods, Para X]`.  
   * If method is located in supplementary material: Cite `[Supp_Appendix 1, Para Y]` and append: `"(Methodology detail relegated to Supplementary Materials)"`.  
   * If method is absent in both main and supplementary text: Trigger the appropriate Risk of Bias Rule (e.g., `R_CONSORT_01`) and state explicitly: `"Methodological detail absent from both primary manuscript and attached supplementary files [Doc_Header]."`

## **Strict Execution Rules for Antigravity**

### **Data Structure Specifications**

The engine must consume four static JSON database files:// triagedb.json

\[

  {

    "framework\_id": "FW\_A",

    "name": "Superiority RCT",

    "triggers": \["randomized", "double-blind", "placebo-controlled", "superiority"\],

    "exclusions": \["non-inferiority", "systematic review", "cost-effectiveness"\],

    "sub\_tags": \["+TAG\_CONSORT\_PRO", "+TAG\_BIOMARKER"\]

  }

\]

// rulesdb.json

\[

  {

    "rule\_id": "R\_NI\_MARGIN\_01",

    "target\_domain": "Non-Inferiority Design",

    "trigger\_condition": "framework\_id \== 'FW\_F' or tags.contains('+TAG\_NON\_INFERIORITY')",

    "appraisal\_action": "Evaluate if both ITT and PP analyses are reported. If PP is missing, report high risk of bias."

  }

\]

// lexicondb.json

\[

  {

    "term": "Hazard Ratio",

    "definition": "Relative rate of an event occurring in treatment vs control arm at any given point in time.",

    "caveat": "HR assumes constant proportional hazard over time."

  }

\]

// schemadb.json

{

  "FW\_A": {

    "headings": \[

      "\# \[Article Title\]",

      "\#\# Executive Appraisal & Baseline Rigor",

      "\#\# Primary Efficacy & Safety Evaluation",

      "\#\# Methodological Flaws & Risk of Bias",

      "\#\# Bibliographic Data"

    \]

  }

}

### **Deterministic Parsing Pipeline Requirements**

1. **Strict Context Injection:** The generation prompt passed to the LLM during Stage 3 must **only** contain the exact schema text, matched rules from `rulesdb.json`, relevant term definitions from `lexicondb.json`, and the indexed source text.  
2. **Coordinate Enforcement:** Every analytical assertion must end with a valid coordinate anchor tag from the source text (e.g., `[Results, Table 1]`).  
3. **Post-Processing Sanitization Regex:** Before delivering the synthesized markdown string to the application UI, execute the following string cleanup operations:  
   * Strip matching disclaimer blocks: `/(?i)(disclaimer|informational purposes only|consult your physician|not intended to provide medical advice).*/g`  
   * Strip conversational conversational fillers: `/(?i)(hope this helps|let me know if|as an ai|here is your analysis).*/g`  
   * Ensure exact match of target framework structural headers specified in `schemadb.json`.

