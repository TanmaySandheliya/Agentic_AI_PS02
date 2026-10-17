"""
Lever Job Board Adapter for SkillTrace.
Extracts title, company, clean text snapshot, and qualifications from Lever job postings.
"""
from typing import Dict, Any, Optional
from bs4 import BeautifulSoup
import re


def is_lever_url(url: str) -> bool:
    """Checks if the URL is a Lever job board."""
    return "jobs.lever.co" in url or "lever.co" in url


def parse_lever_job(html_content: str, url: str) -> Dict[str, Any]:
    """
    Parses Lever job posting HTML into structured metadata and snapshot text.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Title extraction
    title = "Unknown Position"
    title_el = soup.find(class_=re.compile(r"posting-headline", re.I))
    if title_el:
        h2 = title_el.find("h2")
        title = h2.get_text(strip=True) if h2 else title_el.get_text(strip=True)
    elif soup.find("h2"):
        title = soup.find("h2").get_text(strip=True)

    # Company extraction
    company = "Unknown Company"
    match = re.search(r"jobs\.lever\.co/([^/]+)", url)
    if match:
        company = match.group(1).replace("-", " ").title()
    else:
        meta_site = soup.find("meta", property="og:site_name")
        if meta_site and meta_site.get("content"):
            company = meta_site["content"]

    # Content extraction: remove non-content elements
    for tag in soup(["script", "style", "noscript", "svg", "form", "iframe"]):
        tag.decompose()

    # Look for posting sections
    content_el = soup.find(class_=re.compile(r"posting-sections|section-page", re.I)) or soup.body

    if content_el:
        snapshot_text = content_el.get_text(separator="\n", strip=True)
    else:
        snapshot_text = soup.get_text(separator="\n", strip=True)

    snapshot_text = re.sub(r"\n{3,}", "\n\n", snapshot_text)

    return {
        "title": title,
        "company": company,
        "source_name": "Lever",
        "source_url": url,
        "snapshot_text": snapshot_text
    }
