"""
Generic URL Ingest and Snapshot Extraction for SkillTrace.
Conforms to SRS Section 4.2 (FR-06 to FR-09) and Section 13.2 (TC-01, TC-02).
"""
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional
import re
from urllib.parse import urlparse

from config import settings
from .greenhouse import is_greenhouse_url, parse_greenhouse_job
from .lever import is_lever_url, parse_lever_job


class JobIngestError(Exception):
    """Raised when job retrieval fails or page blocks extraction."""
    def __init__(self, message: str, url: str, status_code: Optional[int] = None, allow_paste: bool = True):
        super().__init__(message)
        self.message = message
        self.url = url
        self.status_code = status_code
        self.allow_paste = allow_paste


def fetch_job_from_url(url: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """
    Fetches and extracts a job posting from any public URL.
    Dispatches to specialized adapters (Greenhouse, Lever) or falls back to generic extraction.
    """
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise JobIngestError(f"Invalid URL protocol: '{url}'. Expected http:// or https://", url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 SkillTrace/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    req_timeout = timeout or settings.request_timeout_seconds

    try:
        response = requests.get(url, headers=headers, timeout=req_timeout, allow_redirects=True)
    except requests.exceptions.Timeout:
        raise JobIngestError(
            f"Connection timed out while fetching {url} after {req_timeout}s. Please paste the job description manually.",
            url=url,
            allow_paste=True
        )
    except requests.exceptions.RequestException as e:
        raise JobIngestError(
            f"Network error fetching {url}: {str(e)}. Please paste the job description manually.",
            url=url,
            allow_paste=True
        )

    if response.status_code in (401, 403, 429):
        raise JobIngestError(
            f"The job posting host returned HTTP {response.status_code} (access restricted or bot protection). "
            f"Please copy and paste the posting text directly using the manual input option.",
            url=url,
            status_code=response.status_code,
            allow_paste=True
        )

    if response.status_code >= 400:
        raise JobIngestError(
            f"Failed to fetch posting: HTTP {response.status_code} ({response.reason}). Check the link or paste the text.",
            url=url,
            status_code=response.status_code,
            allow_paste=True
        )

    html_text = response.text

    # Route to specialized parsers
    if is_greenhouse_url(url):
        return parse_greenhouse_job(html_text, url)
    elif is_lever_url(url):
        return parse_lever_job(html_text, url)

    # Generic extraction
    return parse_generic_job(html_text, url)


def parse_generic_job(html_content: str, url: str) -> Dict[str, Any]:
    """
    Generic HTML cleaner and parser for arbitrary career pages.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Domain name for fallback company identification
    domain = urlparse(url).netloc.replace("www.", "")
    parts = domain.split(".")
    domain_label = parts[0].capitalize() if parts else "Unknown Company"

    # Extract Title
    title = ""
    # Try og:title
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        elif soup.title:
            title = soup.title.get_text(strip=True)
        else:
            title = f"Role at {domain_label}"

    # Extract Company
    company = domain_label
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        company = og_site["content"].strip()

    # Clean boilerplate tags
    for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "form", "iframe", "button"]):
        tag.decompose()

    # Focus on main/article/job-details if available
    main_el = (
        soup.find("main") or
        soup.find("article") or
        soup.find(class_=re.compile(r"job[-_]?description|posting|career|role|details", re.I)) or
        soup.body or
        soup
    )

    snapshot_text = main_el.get_text(separator="\n", strip=True)
    snapshot_text = re.sub(r"\n{3,}", "\n\n", snapshot_text)

    return {
        "title": title or "Software Engineering Position",
        "company": company,
        "source_name": "Web Ingestion",
        "source_url": url,
        "snapshot_text": snapshot_text
    }


def ingest_pasted_text(title: str, company: str, source_url: str, text: str) -> Dict[str, Any]:
    """Creates a job snapshot from user-pasted text, retaining the source link (SRS TC-02)."""
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Job text cannot be empty.")

    clean_url = source_url.strip() if source_url else "https://manual-entry.local"

    return {
        "title": title.strip() or "Manual Posting",
        "company": company.strip() or "Specified Employer",
        "source_name": "Direct Paste",
        "source_url": clean_url,
        "snapshot_text": clean_text
    }
