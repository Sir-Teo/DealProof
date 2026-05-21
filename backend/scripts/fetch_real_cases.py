from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "real_cases"
SCRATCH = ROOT / "tests" / "fixtures" / "_downloads" / "real_cases"

SOURCES = {
    "dm_revenue_flow": "https://dmrevenueflow.com/",
    "apple_2025_10k": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm",
    "apple_2025_10k_index": "https://www.sec.gov/Archives/edgar/data/320193/0000320193-25-000079-index.htm",
}

DM_PATTERNS = [
    r"Raising \$3M Pre-Seed[^.]+",
    r"1,000\+ Influencers Managed[^.]+",
    r"3 Creator Houses[^.]+",
    r"10\+ Brand Campaigns[^.]+",
    r"Positive Cash Flow[^.]+",
    r"HeyGen, Runway, Kling, Sora[^.]+",
    r"\+40%DM Conversion[^.]+",
    r"2\.3×LTV Increase[^.]+",
    r"ANNUAL SAVINGS:[^.]+",
    r"\$3\.18M 24-Month Total Revenue[^.]+",
    r"\$2\.56M ARR by Month 24[^.]+",
    r"95\.3% Gross Margin[^.]+",
    r"1,200 accounts[^.]+",
    r"10× Conservative[^.]+",
]

APPLE_PATTERNS = [
    r"Services gross margin percentage increased during 2025 compared to 2024[^.]+",
    r"Services\s+75\.4%73\.9%70\.8%",
    r"Research and development\$34,550[^\\n]+",
    r"The growth in R&D expense during 2025 compared to 2024[^.]+",
    r"cash, cash equivalents and marketable securities[^.]+\$132\.4[^.]+",
    r"outstanding fixed-rate notes[^.]+\$91\.3 billion[^.]+",
    r"manufacturing purchase obligations of \$56\.2 billion[^.]+",
    r"significant majority of the Company’s manufacturing[^.]+",
    r"future gross margins can be impacted[^.]+",
    r"increased competition[^.;]+",
]


def text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def extract_patterns(text: str, patterns: list[str]) -> list[str]:
    excerpts = []
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            excerpts.append(match.group(0).strip())
    return excerpts


def write_fixture(path: Path, header: str, excerpts: list[str]) -> None:
    path.write_text(header + "\n\n" + "\n\n".join(excerpts) + "\n")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "DealProof real-case fixture refresher contact@example.com"}
    with httpx.Client(timeout=30, follow_redirects=True, headers=headers) as client:
        dm_response = client.get(SOURCES["dm_revenue_flow"])
        dm_response.raise_for_status()
        apple_response = client.get(SOURCES["apple_2025_10k"])
        apple_response.raise_for_status()
        index_response = client.get(SOURCES["apple_2025_10k_index"])
        index_response.raise_for_status()

    (SCRATCH / "dm_revenue_flow.html").write_text(dm_response.text)
    (SCRATCH / "apple_2025_10k.html").write_text(apple_response.text)
    (SCRATCH / "apple_2025_10k_index.html").write_text(index_response.text)

    dm_text = text_from_html(dm_response.text)
    apple_text = text_from_html(apple_response.text)

    dm_excerpts = extract_patterns(dm_text, DM_PATTERNS)
    apple_excerpts = extract_patterns(apple_text, APPLE_PATTERNS)

    write_fixture(
        FIXTURES / "dm_revenue_flow_pitch.txt",
        f"Source snapshot: DMs Revenue Flow public investor page, {SOURCES['dm_revenue_flow']}\nSnapshot date: {date.today().isoformat()}",
        [f"DMs Revenue Flow public source excerpt: {item}" for item in dm_excerpts],
    )
    write_fixture(
        FIXTURES / "dm_revenue_flow_public_evidence.txt",
        f"Source snapshot: DMs Revenue Flow public investor page, {SOURCES['dm_revenue_flow']}\nSnapshot date: {date.today().isoformat()}",
        [f"Public evidence excerpt: {item}" for item in dm_excerpts]
        + [
            "Public evidence excerpt: adjacent competitors include HeyGen, Runway, Kling, Sora, GPT-4o, and Claude 3.5 Sonnet in AI video or multimodal content workflows."
        ],
    )
    write_fixture(
        FIXTURES / "apple_2025_10k_evidence.txt",
        f"Source snapshot: Apple Inc. 2025 Form 10-K, SEC EDGAR, {SOURCES['apple_2025_10k']}\nSnapshot date: {date.today().isoformat()}",
        [f"Apple 2025 Form 10-K evidence says {item}" for item in apple_excerpts],
    )

    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    manifest["snapshotDate"] = date.today().isoformat()
    (FIXTURES / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Refreshed {len(dm_excerpts)} DMs excerpts and {len(apple_excerpts)} Apple excerpts.")
    print(f"Raw downloads saved under {SCRATCH}.")


if __name__ == "__main__":
    main()
