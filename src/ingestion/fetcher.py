import os
import re
import io
import urllib.parse
from typing import Dict, Any, Optional, Tuple, List
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import pymupdf

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
                    self._generate_pdf_from_jats(root, pdf_path, title)
                    
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
            # First check if there is an associated PMC ID
            sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
            r_sum = requests.get(sum_url, timeout=10)
            if r_sum.status_code == 200:
                data = r_sum.json().get('result', {}).get(pmid, {})
                article_ids = data.get('articleids', [])
                for aid in article_ids:
                    if aid.get('idtype') == 'pmc':
                        pmc_digits = re.sub(r'^[Pp][Mm][Cc]', '', aid['value'])
                        return self._fetch_pmc_fulltext(pmc_digits, source_url)
                    elif aid.get('idtype') == 'doi':
                        res = self._fetch_via_doi_or_unpaywall(aid['value'], source_url)
                        if res.get("status") == "full_text_pdf":
                            return res

            # If no free full-text found, fetch the official abstract via efetch
            fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
            r_fetch = requests.get(fetch_url, timeout=10)
            if r_fetch.status_code == 200:
                root = ET.fromstring(r_fetch.content)
                title_el = root.find('.//ArticleTitle')
                title = ''.join(title_el.itertext()) if title_el is not None else "PubMed Article"
                
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
                    self._create_abstract_pdf(pdf_path, title, abstract_full, f"PMID: {pmid}")
                    
                    return {
                        "status": "abstract_only",
                        "pdf_filename": filename,
                        "is_abstract_only": True,
                        "title": title,
                        "abstract_text": abstract_full,
                        "source_url": source_url,
                        "message": f"Only an abstract is available for PMID {pmid}. No free full-text was located."
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
            
            # Extract main article or body text
            article_body = soup.find('article') or soup.find('main') or soup.body
            all_text = article_body.get_text(separator="\n\n") if article_body else ""
            words = all_text.split()
            
            # If word count > 1800, likely full text HTML
            if len(words) > 1800:
                filename = f"html_paper_{abs(hash(webpage_url)) % 1000000}.pdf"
                pdf_path = os.path.join(self.upload_dir, filename)
                self._create_text_pdf(pdf_path, title, all_text)
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
                self._create_abstract_pdf(pdf_path, title, all_text[:3000], webpage_url)
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

    def _generate_pdf_from_jats(self, root: ET.Element, output_path: str, title: str):
        """Construct a clean, coordinate-indexable PDF from PubMed Central JATS XML."""
        doc = pymupdf.open()
        
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
        y = 50.0
        
        # Header / Title
        current_page.insert_text(pymupdf.Point(50, y), title[:120], fontsize=13, fontname="helv", color=(0.1, 0.2, 0.4))
        y += 35.0
        
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

    def _create_abstract_pdf(self, output_path: str, title: str, abstract_text: str, source_info: str):
        """Generate a clean single-page PDF containing the abstract."""
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        
        y = 50.0
        page.insert_text(pymupdf.Point(50, y), "[ABSTRACT-ONLY EVALUATION]", fontsize=10, fontname="helv", color=(0.8, 0.2, 0.1))
        y += 20.0
        page.insert_text(pymupdf.Point(50, y), title[:130], fontsize=12, fontname="helv", color=(0.1, 0.2, 0.4))
        y += 20.0
        page.insert_text(pymupdf.Point(50, y), source_info[:120], fontsize=8.5, fontname="helv", color=(0.4, 0.4, 0.4))
        y += 30.0
        
        page.insert_text(pymupdf.Point(50, y), "ABSTRACT", fontsize=10.5, fontname="helv", color=(0.2, 0.3, 0.6))
        y += 20.0
        
        rect = pymupdf.Rect(50, y, 545, 780)
        page.insert_textbox(rect, abstract_text, fontsize=9.5, fontname="helv")
        
        doc.save(output_path)
        doc.close()

    def _create_text_pdf(self, output_path: str, title: str, full_text: str):
        """Convert scraped full text to readable PDF."""
        doc = pymupdf.open()
        paragraphs = [p.strip() for p in full_text.split("\n\n") if len(p.strip()) > 30]
        
        page = doc.new_page(width=595, height=842)
        y = 50.0
        page.insert_text(pymupdf.Point(50, y), title[:120], fontsize=13, fontname="helv")
        y += 35.0
        
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
