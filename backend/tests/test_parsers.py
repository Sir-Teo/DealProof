from pathlib import Path

import httpx
import pytest

from app.parsers import fetch_url_text, infer_kind, parse_file, request_headers_for_url, summarize


def test_parse_txt(tmp_path: Path):
    path = tmp_path / "transcript.txt"
    path.write_text("Founder: ARR grew from 10 to 20. Human review is required.")

    assert "ARR grew" in parse_file(path)
    assert infer_kind(path.name) == "transcript"


def test_parse_csv(tmp_path: Path):
    path = tmp_path / "financials.csv"
    path.write_text("metric,jan\nARR,82000\n")

    assert "metric | jan" in parse_file(path)
    assert infer_kind(path.name) == "financials"


def test_summarize():
    summary, excerpt = summarize("First claim. Second claim. Third claim.")

    assert "First claim" in summary
    assert excerpt.startswith("First claim")


def test_sec_request_headers_include_contact_user_agent():
    headers = request_headers_for_url(
        "https://www.sec.gov/Archives/edgar/data/1387222/000095010326007678/xslF345X06/ownership.xml"
    )

    assert "DealProof" in headers["User-Agent"]
    assert "contact" in headers["User-Agent"]
    assert "application/xml" in headers["Accept"]
    assert headers["Accept-Encoding"] == "gzip, deflate"


@pytest.mark.asyncio
async def test_fetch_url_text_sends_headers_and_extracts_sec_xml_html(monkeypatch):
    seen_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(
            200,
            text="<html><head><title>SEC FORM 4</title></head><body><script>ignore()</script><p>Common stock sale</p></body></html>",
            request=request,
        )

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.parsers.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    text = await fetch_url_text(
        "https://www.sec.gov/Archives/edgar/data/1387222/000095010326007678/xslF345X06/ownership.xml"
    )

    assert seen_headers["user-agent"].startswith("DealProof/")
    assert seen_headers["accept-encoding"] == "gzip, deflate"
    assert "SEC FORM 4" in text
    assert "Common stock sale" in text
    assert "ignore()" not in text
