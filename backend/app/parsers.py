from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

from .config import HTTP_USER_AGENT


class UrlFetchError(RuntimeError):
    pass


def request_headers_for_url(url: str) -> dict[str, str]:
    headers = {
        "User-Agent": HTTP_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    }
    if "sec.gov" in url.lower():
        headers["Accept-Encoding"] = "gzip, deflate"
    return headers


def summarize(text: str) -> tuple[str, str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return "No readable text extracted.", ""
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(sentences[:2])[:280], clean[:520]


def parse_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    if suffix == ".csv":
        data = path.read_text(errors="ignore")
        rows = list(csv.reader(io.StringIO(data)))
        return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)
    return path.read_text(errors="ignore")


async def fetch_url_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            response = await client.get(url, headers=request_headers_for_url(url))
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UrlFetchError(f"Failed to fetch URL: upstream returned HTTP {status}.") from exc
        except httpx.HTTPError as exc:
            raise UrlFetchError(f"Failed to fetch URL: {exc}") from exc
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else url
    body = soup.get_text(" ", strip=True)
    return f"{title}\n{body}"


def infer_kind(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".pdf") or "deck" in lower:
        return "deck"
    if lower.endswith(".csv") or "financial" in lower:
        return "financials"
    if "transcript" in lower:
        return "transcript"
    return "document"
