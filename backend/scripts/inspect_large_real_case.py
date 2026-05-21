from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

os.environ["DEEPSEEK_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_cases" / "large_data_room"
FILES = [
    "01_company_overview.txt",
    "02_raise_terms.txt",
    "03_traction_observed.txt",
    "04_financial_model.txt",
    "05_roi_unit_economics.txt",
    "06_market_and_competition.txt",
    "07_founder_call_notes.txt",
    "08_customer_reference_notes.txt",
    "09_risk_and_validation_notes.txt",
    "10_apple_10k_financials.txt",
    "11_apple_10k_supply_chain.txt",
    "12_target_annual_report_retail.txt",
    "13_public_source_index.txt",
    "14_analyst_claim_packet.txt",
]


def main() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/deals",
            json={
                "company": "DMs Revenue Flow",
                "tagline": "Large public-material data room",
                "stage": "Expanded real-world fixture diligence",
            },
        )
        created.raise_for_status()
        deal = created.json()
        files = [("files", (name, (FIXTURES / name).read_bytes(), "text/plain")) for name in FILES]
        uploaded = client.post(f"/deals/{deal['id']}/materials", files=files)
        uploaded.raise_for_status()
        analyzed = client.post(f"/deals/{deal['id']}/analyze")
        analyzed.raise_for_status()
        payload = analyzed.json()

        questions = [
            "Which public materials support the ARR and ROI claims?",
            "What are the biggest unsupported or contradicted claims?",
        ]
        answers = [
            client.post(f"/deals/{deal['id']}/chat", json={"question": question}).json()
            for question in questions
        ]

    print("=== Large Real-World Data Room Inspection ===")
    print(f"Deal: {payload['company']} ({payload['id']})")
    print(f"Materials: {len(payload['materials'])}")
    print(f"Claims: {len(payload['claims'])}")
    print(f"Evidence: {len(payload['evidence'])}")
    print(f"Memo grade: {payload['memo']['overallGrade']}")
    print(f"Status counts: {dict(Counter(claim['status'] for claim in payload['claims']))}")
    print()

    for claim in payload["claims"]:
        evidence = [item for item in payload["evidence"] if item["claimId"] == claim["id"]]
        print(f"- {claim['id']} [{claim['status']}/{claim['category']}/{claim['importance']}] {claim['text']}")
        print(f"  rationale: {claim['riskRationale']}")
        for item in evidence[:2]:
            print(f"  evidence: {item['stance']} | {item['citation']} | {item['snippet'][:140]}")
    print()

    print("=== Memo ===")
    print(f"Question: {payload['memo']['investmentQuestion']}")
    print("Material risks:")
    for item in payload["memo"]["materialRisks"]:
        print(f"- {item}")
    print("Follow-up questions:")
    for item in payload["memo"]["followUpQuestions"]:
        print(f"- {item}")
    print(f"Recommendation: {payload['memo']['icRecommendation']}")
    print()

    print("=== Chat Answers ===")
    for question, answer in zip(questions, answers, strict=True):
        print(f"Q: {question}")
        print(f"A: {answer['answer']}")
        print(f"Citations: {', '.join(answer['citations'])}")
        print(f"Confidence: {answer['confidence']}")


if __name__ == "__main__":
    main()
