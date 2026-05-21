from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader


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
        response = await client.get(url)
        response.raise_for_status()
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
