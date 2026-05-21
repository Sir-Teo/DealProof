from fastapi.testclient import TestClient

from app.main import app


def test_demo_deal_can_be_created_and_loaded():
    with TestClient(app) as client:
        created = client.post("/deals/demo")
        assert created.status_code == 200
        deal = created.json()

        loaded = client.get(f"/deals/{deal['id']}")
        assert loaded.status_code == 200
        assert len(loaded.json()["materials"]) >= 3
