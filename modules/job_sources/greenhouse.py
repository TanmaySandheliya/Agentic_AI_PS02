"""
Greenhouse Job Board Adapter for SkillTrace.
Extracts title, company, clean text snapshot, and qualifications from Greenhouse job postings.
"""
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import re


def is_greenhouse_url(url: str) -> bool:
    """Checks if the URL is a Greenhouse job board."""
    return "boards.greenhouse.io" in url or "greenhouse.io" in url


def parse_greenhouse_job(html_content: str, url: str) -> Dict[str, Any]:
    """
    Parses Greenhouse job posting HTML into structured metadata and snapshot text.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Title extraction
    title = "Unknown Position"
    title_el = soup.find(class_=re.compile(r"app-title|job-title", re.I)) or soup.find("h1")
    if title_el:
        title = title_el.get_text(strip=True)

    # Company extraction
    company = "Unknown Company"
    company_el = soup.find(class_=re.compile(r"company-name|company", re.I))
    if company_el:
        company = company_el.get_text(strip=True)
    else:
        # Check URL pattern: boards.greenhouse.io/<company>/jobs/...
        match = re.search(r"greenhouse\.io/([^/]+)", url)
        if match:
            company = match.group(1).replace("-", " ").title()

    # Content extraction: remove scripts, styles, forms, iframes
    for tag in soup(["script", "style", "noscript", "svg", "form", "iframe"]):
        tag.decompose()

    content_el = soup.find(id="content") or soup.find(class_=re.compile(r"body|content|description", re.I)) or soup.body

    if content_el:
        snapshot_text = content_el.get_text(separator="\n", strip=True)
    else:
        snapshot_text = soup.get_text(separator="\n", strip=True)

    # Normalize excessive newlines
    snapshot_text = re.sub(r"\n{3,}", "\n\n", snapshot_text)

    return {
        "title": title,
        "company": company,
        "source_name": "Greenhouse",
        "source_url": url,
        "snapshot_text": snapshot_text
    }
