from pathlib import Path

from app.parsers import infer_kind, parse_file, summarize


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
