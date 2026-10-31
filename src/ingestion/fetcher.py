import os
import sys
import re
import io
import urllib.parse
from typing import Dict, Any, Optional, Tuple, List
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pymupdf

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

class PaperFetcher:
    """Intelligent paper fetcher supporting PMC, PubMed, DOI, and journal URLs."""
    
    def __init__(self, upload_dir: str):
        self.upload_dir = upload_dir
        os.makedirs(upload_dir, exist_ok=True)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8"
        }

    def resolve_url(self, raw_input: str) -> Dict[str, Any]:
        """
        Analyze an input URL, DOI, or PubMed ID.
        Returns a dict:
        {
            "status": "full_text_pdf" | "abstract_only" | "error",
            "pdf_filename": str (if full text or generated),
            "is_abstract_only": bool,
            "title": str,
            "abstract_text": str,
            "source_url": str,
            "message": str
        }
        """
        raw_clean = raw_input.strip()
        
        # 1. Check if direct PDF URL
        if raw_clean.lower().endswith(".pdf") or ".pdf?" in raw_clean.lower():
            return self._download_direct_pdf(raw_clean)

        # 2. Check for PubMed Central (PMC) ID or URL
        pmc_match = re.search(r'PMC(\d+)', raw_clean, re.IGNORECASE)
        if pmc_match:
            pmcid = pmc_match.group(1)
            return self._fetch_pmc_fulltext(pmcid, raw_clean)

        # 3. Check for PubMed (PMID) URL or numeric PMID
        pmid_match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', raw_clean, re.IGNORECASE) or (raw_clean.isdigit() and len(raw_clean) in range(6, 10))
        if pmid_match:
            pmid = pmid_match.group(1) if hasattr(pmid_match, 'group') else raw_clean
            return self._fetch_pubmed_id(pmid, raw_clean)

        # 4. Check for DOI
        doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', raw_clean)
        if doi_match:
            doi = doi_match.group(0)
            return self._fetch_via_doi_or_unpaywall(doi, raw_clean)

        # 5. Generic Journal / HTML Webpage
        return self._fetch_generic_webpage(raw_clean)

    def check_url_availability(self, raw_input: str) -> Dict[str, Any]:
        """
        Fast preliminary check to see if free full text is available via PMC/Unpaywall
        or whether only an abstract is available, prior to downloading large files.
        """
        raw_clean = raw_input.strip()
        if not raw_clean:
            return {"status": "error", "message": "Empty URL or identifier."}

        # 1. Direct PDF URL
        if raw_clean.lower().endswith(".pdf") or ".pdf?" in raw_clean.lower():
            return {
                "status": "success",
                "input_type": "pdf_url",
                "full_text_available": True,
                "is_abstract_only": False,
                "source_type": "Direct PDF Link",
                "message": "Direct PDF link detected (full text available)."
            }

        # 2. PubMed Central (PMC) ID or URL
        pmc_match = re.search(r'PMC(\d+)', raw_clean, re.IGNORECASE)
        if pmc_match:
            pmcid = pmc_match.group(1)
            return {
                "status": "success",
                "input_type": "pmc",
                "pmcid": f"PMC{pmcid}",
                "full_text_available": True,
                "is_abstract_only": False,
                "source_type": "PubMed Central (PMC)",
                "message": f"Full text is available on PubMed Central (PMC{pmcid}) via PubMed API."
            }

        # 3. PubMed (PMID) URL or numeric PMID
        pmid_match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', raw_clean, re.IGNORECASE) or (raw_clean.isdigit() and len(raw_clean) in range(6, 10))
        if pmid_match:
            pmid = pmid_match.group(1) if hasattr(pmid_match, 'group') else raw_clean
            return self._check_pubmed_availability(pmid, raw_clean)

        # 4. DOI
        doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', raw_clean)
        if doi_match:
            doi = doi_match.group(0)
            return self._check_doi_availability(doi, raw_clean)

        # 5. Generic Webpage
        return {
            "status": "success",
            "input_type": "webpage",
            "full_text_available": True,
            "is_abstract_only": False,
            "source_type": "Webpage",
            "message": "Journal webpage provided. Web article extractor ready."
        }

    def _check_pubmed_availability(self, pmid: str, source_url: str) -> Dict[str, Any]:
        """Query NCBI elink and esummary to verify PMC full-text linkage."""
        try:
            # 1. Query elink.fcgi for direct PMC linkage
            elink_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id={pmid}&retmode=json"
            r_elink = requests.get(elink_url, timeout=8)
            if r_elink.status_code == 200:
                for ls in r_elink.json().get('linksets', []):
                    for db in ls.get('linksetdbs', []):
                        if db.get('linkname') == 'pubmed_pmc':
                            links = db.get('links', [])
                            if links:
                                pmcid = str(links[0])
                                # Fetch title from esummary
                                title = f"PubMed Article {pmid}"
                                sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
                                r_sum = requests.get(sum_url, timeout=6)
                                if r_sum.status_code == 200:
                                    title = r_sum.json().get('result', {}).get(pmid, {}).get('title', title)
                                return {
                                    "status": "success",
                                    "input_type": "pubmed",
                                    "pmid": pmid,
                                    "pmcid": f"PMC{pmcid}",
                                    "full_text_available": True,
                                    "is_abstract_only": False,
                                    "source_type": "PubMed Central (PMC)",
                                    "title": title,
                                    "message": f"Full text is available on PubMed Central (PMC{pmcid}) via PubMed API."
                                }

            # 2. Query esummary for DOI and Unpaywall check
            sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
            r_sum = requests.get(sum_url, timeout=8)
            title = f"PubMed Article {pmid}"
            doi = None
            if r_sum.status_code == 200:
                p_data = r_sum.json().get('result', {}).get(pmid, {})
                title = p_data.get('title', title)
                for aid in p_data.get('articleids', []):
                    if aid.get('idtype') == 'doi':
                        doi = aid.get('value')
                        break

            if doi:
                doi_check = self._check_doi_availability(doi, source_url)
                if doi_check.get("full_text_available"):
                    doi_check["pmid"] = pmid
                    doi_check["title"] = title
                    return doi_check

            # 3. Paywalled article - retrieve official abstract snippet
            abstract_text = ""
            fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
            r_fetch = requests.get(fetch_url, timeout=8)
            if r_fetch.status_code == 200:
                root = ET.fromstring(r_fetch.content)
                title_el = root.find('.//ArticleTitle')
                if title_el is not None:
                    title = ''.join(title_el.itertext())
                nodes = root.findall('.//AbstractText')
                abstract_text = "\n\n".join([''.join(n.itertext()) for n in nodes])

            return {
                "status": "success",
                "input_type": "pubmed",
                "pmid": pmid,
                "full_text_available": False,
                "is_abstract_only": True,
                "source_type": "PubMed Registry",
                "title": title,
                "abstract_text": abstract_text[:1500] if abstract_text else "No abstract text in registry.",
                "message": f"This study (PMID {pmid}) is paywalled. No free full-text manuscript was located on PubMed Central (Abstract only)."
            }
        except Exception as e:
            return {"status": "error", "message": f"Error querying PubMed API for PMID {pmid}: {str(e)}"}

    def _check_doi_availability(self, doi: str, source_url: str) -> Dict[str, Any]:
        """Check Unpaywall for open-access PDF of DOI."""
        try:
            unp_url = f"https://api.unpaywall.org/v2/{doi}?email=drbiernd@gmail.com"
            r = requests.get(unp_url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", f"DOI: {doi}")
                best_oa = data.get("best_oa_location")
                if best_oa and best_oa.get("url_for_pdf"):
                    return {
                        "status": "success",
                        "input_type": "doi",
                        "full_text_available": True,
                        "is_abstract_only": False,
                        "source_type": "Open Access (Unpaywall)",
                        "doi": doi,
                        "title": title,
                        "message": "Free full-text open access PDF found via Unpaywall."
                    }
        except Exception:
            pass
        return {
            "status": "success",
            "input_type": "doi",
            "full_text_available": False,
            "is_abstract_only": True,
            "source_type": "Journal Paywall",
            "doi": doi,
            "title": f"DOI: {doi}",
            "message": f"No open-access PDF located for DOI {doi} (Paywalled)."
        }

    def _download_direct_pdf(self, pdf_url: str) -> Dict[str, Any]:
        """Download direct PDF link."""
        try:
            r = requests.get(pdf_url, headers=self.headers, timeout=20)
            if r.status_code == 200 and len(r.content) > 5000:
                filename = f"url_paper_{abs(hash(pdf_url)) % 1000000}.pdf"
                path = os.path.join(self.upload_dir, filename)
                with open(path, "wb") as f:
                    f.write(r.content)
                return {
                    "status": "full_text_pdf",
                    "pdf_filename": filename,
                    "is_abstract_only": False,
                    "title": filename,
                    "source_url": pdf_url,
                    "message": "Full-text PDF downloaded successfully."
                }
        except Exception as e:
            pass
        return {"status": "error", "message": f"Could not download PDF from {pdf_url}"}

    def _fetch_pmc_fulltext(self, pmcid_digits: str, source_url: str) -> Dict[str, Any]:
        """Fetch full-text from PubMed Central via official NCBI JATS XML efetch."""
        try:
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid_digits}&retmode=xml"
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and len(r.text) > 1000:
                root = ET.fromstring(r.content)
                
                # Extract title
                title_el = root.find('.//article-title')
                title = ''.join(title_el.itertext()) if title_el is not None else f"PMC{pmcid_digits}"
                
                # Check for full text body
                body = root.find('.//body')
                if body is not None:
                    # Convert structured JATS XML into a clean, searchable PDF
                    filename = f"PMC{pmcid_digits}.pdf"
                    pdf_path = os.path.join(self.upload_dir, filename)
                    self._generate_pdf_from_jats(root, pdf_path, title, default_pmcid=f"PMC{pmcid_digits}")
                    
                    return {
                        "status": "full_text_pdf",
                        "pdf_filename": filename,
                        "is_abstract_only": False,
                        "title": title,
                        "source_url": source_url,
                        "message": f"Full text extracted from PubMed Central (PMC{pmcid_digits})."
                    }
        except Exception as e:
            pass
            
        return {"status": "error", "message": f"Could not retrieve full text for PMC{pmcid_digits}."}

    def _fetch_pubmed_id(self, pmid: str, source_url: str) -> Dict[str, Any]:
        """Fetch paper metadata from PubMed; check if PMC full text is linked, otherwise flag abstract."""
        try:
            # 1. Direct NCBI elink check for PubMed Central full-text linkage
            elink_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi?dbfrom=pubmed&db=pmc&id={pmid}&retmode=json"
            r_elink = requests.get(elink_url, timeout=10)
            if r_elink.status_code == 200:
                for ls in r_elink.json().get('linksets', []):
                    for db in ls.get('linksetdbs', []):
                        if db.get('linkname') == 'pubmed_pmc':
                            links = db.get('links', [])
                            if links:
                                pmc_digits = str(links[0])
                                res = self._fetch_pmc_fulltext(pmc_digits, source_url)
                                if res.get("status") == "full_text_pdf":
                                    res["pmid"] = pmid
                                    res["pmcid"] = f"PMC{pmc_digits}"
                                    res["source_type"] = "PMC"
                                    res["message"] = f"Full text verified on PubMed Central (PMC{pmc_digits}) and retrieved via PubMed/NCBI API."
                                    return res

            # 2. Check esummary for DOI and open-access via Unpaywall
            sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
            r_sum = requests.get(sum_url, timeout=10)
            if r_sum.status_code == 200:
                data = r_sum.json().get('result', {}).get(pmid, {})
                article_ids = data.get('articleids', [])
                for aid in article_ids:
                    if aid.get('idtype') == 'doi':
                        res = self._fetch_via_doi_or_unpaywall(aid['value'], source_url)
                        if res.get("status") == "full_text_pdf":
                            res["pmid"] = pmid
                            return res

            # 3. If no free full-text found, fetch the official abstract via efetch
            fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
            r_fetch = requests.get(fetch_url, timeout=10)
            if r_fetch.status_code == 200:
                root = ET.fromstring(r_fetch.content)
                title_el = root.find('.//ArticleTitle')
                title = ''.join(title_el.itertext()) if title_el is not None else "PubMed Article"
                
                # Extract Authors
                authors = []
                for a in root.findall('.//Author'):
                    last = a.find('LastName')
                    fore = a.find('ForeName')
                    l_txt = last.text.strip() if last is not None and last.text else ''
                    f_txt = fore.text.strip() if fore is not None and fore.text else ''
                    if l_txt or f_txt:
                        authors.append(f"{f_txt} {l_txt}".strip())
                authors_str = ", ".join(authors) if authors else "Not specified"

                # Extract Journal
                j_el = root.find('.//Journal/Title') or root.find('.//Journal/ISOAbbreviation')
                journal = ''.join(j_el.itertext()).strip() if j_el is not None else "Not specified"

                # Extract Year
                year = ""
                y_el = root.find('.//JournalIssue/PubDate/Year') or root.find('.//ArticleDate/Year') or root.find('.//PubDate/Year')
                if y_el is not None and y_el.text:
                    year = y_el.text.strip()
                if not year:
                    year = "Not specified"

                # Extract DOI
                doi = ""
                for aid in root.findall('.//ArticleId'):
                    if aid.get('IdType') == 'doi' and aid.text:
                        doi = aid.text.strip()

                meta_dict = {
                    "authors": authors_str,
                    "journal": journal,
                    "year": year,
                    "doi": doi,
                    "pmid": pmid
                }
                
                abstract_nodes = root.findall('.//AbstractText')
                abstract_parts = []
                for node in abstract_nodes:
                    label = node.get('Label')
                    text = ''.join(node.itertext())
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
                abstract_full = "\n\n".join(abstract_parts)
                
                if abstract_full:
                    # Create an abstract PDF representation
                    filename = f"PubMed_{pmid}_abstract.pdf"
                    pdf_path = os.path.join(self.upload_dir, filename)
                    self._create_abstract_pdf(pdf_path, title, abstract_full, meta_dict)
                    
                    return {
                        "status": "abstract_only",
                        "pdf_filename": filename,
                        "is_abstract_only": True,
                        "title": title,
                        "pmid": pmid,
                        "abstract_text": abstract_full,
                        "source_url": source_url,
                        "message": f"This study (PMID {pmid}) is paywalled. No free full-text was located on PubMed Central (Abstract only)."
                    }
        except Exception as e:
            pass

        return {"status": "error", "message": f"Could not retrieve paper or abstract for PMID {pmid}."}

    def _fetch_via_doi_or_unpaywall(self, doi: str, source_url: str) -> Dict[str, Any]:
        """Query Unpaywall API to resolve open access PDF for DOI."""
        try:
            unpaywall_url = f"https://api.unpaywall.org/v2/{doi}?email=drbiernd@gmail.com"
            r = requests.get(unpaywall_url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                title = data.get("title", f"DOI: {doi}")
                best_oa = data.get("best_oa_location")
                if best_oa and best_oa.get("url_for_pdf"):
                    pdf_link = best_oa["url_for_pdf"]
                    # Try downloading
                    pdf_res = self._download_direct_pdf(pdf_link)
                    if pdf_res.get("status") == "full_text_pdf":
                        pdf_res["title"] = title
                        return pdf_res
        except Exception:
            pass
        return {"status": "error", "message": f"Could not find open access PDF for DOI: {doi}"}

    def _fetch_generic_webpage(self, webpage_url: str) -> Dict[str, Any]:
        """Scrape webpage and detect whether full text or only abstract is present."""
        try:
            r = requests.get(webpage_url, headers=self.headers, timeout=12)
            if r.status_code != 200:
                return {"status": "error", "message": f"Webpage returned status {r.status_code}."}
                
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Check for direct PDF links in meta tags
            meta_pdf = soup.find('meta', {'name': re.compile(r'citation_pdf_url', re.I)})
            if meta_pdf and meta_pdf.get('content'):
                pdf_res = self._download_direct_pdf(meta_pdf['content'])
                if pdf_res.get("status") == "full_text_pdf":
                    return pdf_res

            title = soup.title.string.strip() if soup.title else "Web Article"
            
            # Extract meta tags for bibliographic info
            authors_meta = [m['content'] for m in soup.find_all('meta', {'name': re.compile(r'citation_author', re.I)}) if m.get('content')]
            j_meta = soup.find('meta', {'name': re.compile(r'citation_journal_title', re.I)})
            d_meta = soup.find('meta', {'name': re.compile(r'citation_publication_date|citation_date', re.I)})
            doi_meta = soup.find('meta', {'name': re.compile(r'citation_doi', re.I)})
            
            web_meta = {
                "authors": ", ".join(authors_meta) if authors_meta else "Not specified",
                "journal": j_meta['content'] if j_meta and j_meta.get('content') else "Web Publication",
                "year": d_meta['content'][:4] if d_meta and d_meta.get('content') else "",
                "doi": doi_meta['content'] if doi_meta and doi_meta.get('content') else "",
                "pmid": ""
            }

            # Extract main article or body text
            article_body = soup.find('article') or soup.find('main') or soup.body
            all_text = article_body.get_text(separator="\n\n") if article_body else ""
            words = all_text.split()
            
            # If word count > 1800, likely full text HTML
            if len(words) > 1800:
                filename = f"html_paper_{abs(hash(webpage_url)) % 1000000}.pdf"
                pdf_path = os.path.join(self.upload_dir, filename)
                self._create_text_pdf(pdf_path, title, all_text, web_meta)
                return {
                    "status": "full_text_pdf",
                    "pdf_filename": filename,
                    "is_abstract_only": False,
                    "title": title,
                    "source_url": webpage_url,
                    "message": "Full-text article extracted from webpage."
                }
            else:
                # Likely an abstract page / paywalled manuscript
                filename = f"abstract_{abs(hash(webpage_url)) % 1000000}.pdf"
                pdf_path = os.path.join(self.upload_dir, filename)
                self._create_abstract_pdf(pdf_path, title, all_text[:3000], web_meta)
                return {
                    "status": "abstract_only",
                    "pdf_filename": filename,
                    "is_abstract_only": True,
                    "title": title,
                    "abstract_text": all_text[:2000],
                    "source_url": webpage_url,
                    "message": "This webpage appears to contain an abstract only (full manuscript may be behind a paywall)."
                }
        except Exception as e:
            return {"status": "error", "message": f"Failed to access webpage: {str(e)}"}

    def _generate_pdf_from_jats(self, root: ET.Element, output_path: str, title: str, default_pmcid: str = ""):
        """Construct a clean, coordinate-indexable PDF from PubMed Central JATS XML with full bibliographic header."""
        doc = pymupdf.open()
        
        # 1. Extract Full Bibliographic Metadata from JATS XML
        title_el = root.find('.//article-title')
        if title_el is not None:
            clean_title = ''.join(title_el.itertext()).strip()
            if clean_title:
                title = clean_title

        authors = []
        for contrib in root.findall('.//contrib'):
            if contrib.get('contrib-type') == 'author':
                name_el = contrib.find('name')
                if name_el is not None:
                    sur = name_el.find('surname')
                    giv = name_el.find('given-names')
                    s_txt = sur.text.strip() if sur is not None and sur.text else ''
                    g_txt = giv.text.strip() if giv is not None and giv.text else ''
                    if s_txt or g_txt:
                        authors.append(f"{g_txt} {s_txt}".strip())
        authors_str = ", ".join(authors) if authors else "Not specified"

        j_el = root.find('.//journal-title')
        if j_el is None:
            for jid in root.findall('.//journal-id'):
                if jid.text:
                    j_el = jid
                    break
        journal = ''.join(j_el.itertext()).strip() if j_el is not None else "Not specified"

        year = ""
        for pd in root.findall('.//pub-date'):
            y_node = pd.find('year')
            if y_node is not None and y_node.text:
                year = y_node.text.strip()
                break
        if not year:
            year = "Not specified"

        doi = ""
        pmid = ""
        pmcid = default_pmcid
        for aid in root.findall('.//article-id'):
            id_type = aid.get('pub-id-type')
            if id_type == 'doi' and aid.text:
                doi = aid.text.strip()
            elif id_type == 'pmid' and aid.text:
                pmid = aid.text.strip()
            elif id_type == 'pmc' and aid.text:
                pmcid = f"PMC{aid.text.strip()}"

        # Collect sections
        sections = []
        abstract_el = root.find('.//abstract')
        if abstract_el is not None:
            sections.append(("Abstract", "".join(abstract_el.itertext()).strip()))
            
        body = root.find('.//body')
        if body is not None:
            for sec in body.findall('.//sec'):
                sec_title_el = sec.find('title')
                sec_title = "".join(sec_title_el.itertext()).strip() if sec_title_el is not None else "Section"
                paras = ["".join(p.itertext()).strip() for p in sec.findall('.//p')]
                if paras:
                    sections.append((sec_title, "\n\n".join(paras)))

        # Render sections across PDF pages
        current_page = doc.new_page(width=595, height=842)
        y = 45.0
        
        # 1. Header Box / Title
        t_lines = max(1, len(title) // 65 + 1)
        t_h = t_lines * 16.0 + 8.0
        current_page.insert_textbox(pymupdf.Rect(50, y, 545, y + t_h), title, fontsize=12, fontname="helv", color=(0.1, 0.2, 0.4))
        y += t_h + 4.0
        
        # 2. Authors
        a_lines = max(1, len(f"Authors: {authors_str}") // 80 + 1)
        a_h = a_lines * 13.0 + 8.0
        current_page.insert_textbox(pymupdf.Rect(50, y, 545, y + a_h), f"Authors: {authors_str}", fontsize=8.5, fontname="helv", color=(0.2, 0.2, 0.2))
        y += a_h + 4.0
        
        # 3. Journal & Year
        current_page.insert_text(pymupdf.Point(50, y), f"Journal: {journal} | Year: {year}", fontsize=8.5, fontname="helv", color=(0.25, 0.25, 0.25))
        y += 16.0
        
        # 4. DOI, PMID, PMC
        id_parts = []
        if doi:
            id_parts.append(f"DOI: {doi}")
        if pmid:
            id_parts.append(f"PMID: {pmid}")
        if pmcid:
            id_parts.append(f"PMC: {pmcid}")
        id_line = " | ".join(id_parts) if id_parts else "Source: PubMed Central"
        current_page.insert_text(pymupdf.Point(50, y), id_line, fontsize=8.0, fontname="helv", color=(0.35, 0.35, 0.35))
        y += 22.0
        
        # Divider line
        current_page.draw_line(pymupdf.Point(50, y), pymupdf.Point(545, y), color=(0.8, 0.8, 0.8), width=0.75)
        y += 18.0
        
        for sec_name, content in sections:
            # Section header
            if y > 760:
                current_page = doc.new_page(width=595, height=842)
                y = 50.0
            current_page.insert_text(pymupdf.Point(50, y), sec_name.upper(), fontsize=10, fontname="helv", color=(0.2, 0.4, 0.7))
            y += 20.0
            
            # Paragraphs
            for para in content.split("\n\n"):
                p_clean = para.strip()
                if not p_clean:
                    continue
                if y > 760:
                    current_page = doc.new_page(width=595, height=842)
                    y = 50.0
                rect = pymupdf.Rect(50, y, 545, 800)
                rc = current_page.insert_textbox(rect, p_clean, fontsize=9.5, fontname="helv")
                line_count = max(1, len(p_clean) // 85 + 1)
                y += line_count * 13.0 + 12.0
                
        doc.save(output_path)
        doc.close()

    def _create_abstract_pdf(self, output_path: str, title: str, abstract_text: str, metadata: Any = None):
        """Generate a clean single-page PDF containing the abstract and complete bibliographic metadata."""
        if isinstance(metadata, str):
            metadata = {"journal": metadata}
        elif metadata is None:
            metadata = {}
            
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        
        y = 45.0
        page.insert_text(pymupdf.Point(50, y), "[ABSTRACT-ONLY EVALUATION]", fontsize=9.5, fontname="helv", color=(0.8, 0.2, 0.1))
        y += 20.0
        
        # Title Box
        t_lines = max(1, len(title) // 65 + 1)
        t_h = t_lines * 16.0 + 8.0
        page.insert_textbox(pymupdf.Rect(50, y, 545, y + t_h), title, fontsize=12, fontname="helv", color=(0.1, 0.2, 0.4))
        y += t_h + 4.0
        
        # Authors
        authors = metadata.get("authors", "Not specified")
        a_lines = max(1, len(f"Authors: {authors}") // 80 + 1)
        a_h = a_lines * 13.0 + 8.0
        page.insert_textbox(pymupdf.Rect(50, y, 545, y + a_h), f"Authors: {authors}", fontsize=8.5, fontname="helv", color=(0.2, 0.2, 0.2))
        y += a_h + 4.0
        
        # Journal & Year
        journal = metadata.get("journal", "Not specified")
        year = metadata.get("year", "Not specified")
        page.insert_text(pymupdf.Point(50, y), f"Journal: {journal} | Year: {year}", fontsize=8.5, fontname="helv", color=(0.25, 0.25, 0.25))
        y += 16.0
        
        # DOI / PMID
        doi = metadata.get("doi", "")
        pmid = metadata.get("pmid", "")
        id_parts = []
        if doi:
            id_parts.append(f"DOI: {doi}")
        if pmid:
            id_parts.append(f"PMID: {pmid}")
        id_line = " | ".join(id_parts) if id_parts else "Source: PubMed"
        page.insert_text(pymupdf.Point(50, y), id_line, fontsize=8.0, fontname="helv", color=(0.35, 0.35, 0.35))
        y += 22.0
        
        # Divider line
        page.draw_line(pymupdf.Point(50, y), pymupdf.Point(545, y), color=(0.8, 0.8, 0.8), width=0.75)
        y += 18.0
        
        page.insert_text(pymupdf.Point(50, y), "ABSTRACT", fontsize=10.5, fontname="helv", color=(0.2, 0.3, 0.6))
        y += 18.0
        
        rect = pymupdf.Rect(50, y, 545, 800)
        page.insert_textbox(rect, abstract_text, fontsize=9.5, fontname="helv")
        
        doc.save(output_path)
        doc.close()

    def _create_text_pdf(self, output_path: str, title: str, full_text: str, metadata: Any = None):
        """Convert scraped full text to readable PDF with bibliographic header."""
        if isinstance(metadata, str):
            metadata = {"journal": metadata}
        elif metadata is None:
            metadata = {}

        doc = pymupdf.open()
        paragraphs = [p.strip() for p in full_text.split("\n\n") if len(p.strip()) > 30]
        
        page = doc.new_page(width=595, height=842)
        y = 45.0
        page.insert_textbox(pymupdf.Rect(50, y, 545, y + 42), title, fontsize=12, fontname="helv", color=(0.1, 0.2, 0.4))
        y += 46.0
        
        authors = metadata.get("authors", "")
        if authors:
            page.insert_textbox(pymupdf.Rect(50, y, 545, y + 30), f"Authors: {authors}", fontsize=8.5, fontname="helv", color=(0.2, 0.2, 0.2))
            y += 32.0
            
        journal = metadata.get("journal", "")
        year = metadata.get("year", "")
        if journal or year:
            page.insert_text(pymupdf.Point(50, y), f"Journal: {journal or 'Web Publication'} | Year: {year or 'N/A'}", fontsize=8.5, fontname="helv", color=(0.25, 0.25, 0.25))
            y += 18.0
            
        doi = metadata.get("doi", "")
        if doi:
            page.insert_text(pymupdf.Point(50, y), f"DOI: {doi}", fontsize=8.0, fontname="helv", color=(0.35, 0.35, 0.35))
            y += 20.0
            
        page.draw_line(pymupdf.Point(50, y), pymupdf.Point(545, y), color=(0.8, 0.8, 0.8), width=0.75)
        y += 18.0
        
        for p in paragraphs:
            if y > 760:
                page = doc.new_page(width=595, height=842)
                y = 50.0
            rect = pymupdf.Rect(50, y, 545, 800)
            page.insert_textbox(rect, p, fontsize=9.5, fontname="helv")
            lines = max(1, len(p) // 85 + 1)
            y += lines * 13.0 + 10.0
            
        doc.save(output_path)
        doc.close()
