from __future__ import annotations

import shutil
import uuid
import json
from pathlib import Path
from queue import Queue
from threading import Thread

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import db
from .config import (
    API_TITLE,
    ANALYSIS_COMPLETE_LABEL,
    DEFAULT_COMPANY,
    DEFAULT_STAGE,
    DEFAULT_TAGLINE,
    DEMO_PACKET_PATH,
    EXPORT_MEMO_FILENAME,
    LOCAL_FRONTEND_ORIGIN_REGEX,
    LOCAL_FRONTEND_ORIGINS,
)
from .graph import answer_question, refresh_review_artifacts, run_diligence
from .models import ChatAnswer, ClaimStatus, DealAnalysis, ReviewerStatus, SourceMaterial
from .parsers import fetch_url_text, infer_kind, parse_file, summarize
from .scoring import memo_to_markdown

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "storage" / "deals"

app = FastAPI(title=API_TITLE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(LOCAL_FRONTEND_ORIGINS),
    allow_origin_regex=LOCAL_FRONTEND_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DealCreate(BaseModel):
    company: str = DEFAULT_COMPANY
    tagline: str = DEFAULT_TAGLINE
    stage: str = DEFAULT_STAGE


class UrlCreate(BaseModel):
    url: str
    name: str | None = None


class ChatRequest(BaseModel):
    question: str


class ClaimReviewPatch(BaseModel):
    status: ClaimStatus | None = None
    reviewerStatus: ReviewerStatus | None = None
    reviewerNotes: str | None = None


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    STORAGE.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/deals")
def create_deal(payload: DealCreate) -> DealAnalysis:
    deal_id = f"deal-{uuid.uuid4().hex[:10]}"
    db.create_deal(deal_id, payload.company, payload.tagline, payload.stage)
    return db.get_deal(deal_id)


@app.post("/deals/demo")
def create_demo_deal() -> DealAnalysis:
    deal_id = f"deal-{uuid.uuid4().hex[:10]}"
    packet = load_demo_packet()
    db.create_deal(deal_id, packet["company"], packet["tagline"], packet["stage"])
    for material in packet["materials"]:
        add_text_material(deal_id, material["name"], material["text"], "seed")
    return db.get_deal(deal_id)


def load_demo_packet() -> dict:
    return json.loads(DEMO_PACKET_PATH.read_text())


@app.get("/deals/{deal_id}")
def get_deal(deal_id: str) -> DealAnalysis:
    try:
        return db.get_deal(deal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Deal not found")


@app.post("/deals/{deal_id}/materials")
async def add_materials(
    deal_id: str,
    files: list[UploadFile] | None = File(default=None),
    url: str | None = Form(default=None),
) -> DealAnalysis:
    ensure_deal(deal_id)
    deal_dir = STORAGE / deal_id
    deal_dir.mkdir(parents=True, exist_ok=True)
    for upload in files or []:
        if not upload.filename:
            continue
        safe_name = Path(upload.filename).name
        path = deal_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
        with path.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        text = parse_file(path)
        summary, excerpt = summarize(text)
        db.add_material(
            SourceMaterial(
                id=f"mat-{uuid.uuid4().hex[:10]}",
                deal_id=deal_id,
                name=safe_name,
                kind=infer_kind(safe_name),  # type: ignore[arg-type]
                source_type="file",
                path=str(path),
                summary=summary,
                excerpt=excerpt,
                text=text,
            )
        )
    if url:
        text = await fetch_url_text(url)
        summary, excerpt = summarize(text)
        db.add_material(
            SourceMaterial(
                id=f"mat-{uuid.uuid4().hex[:10]}",
                deal_id=deal_id,
                name=url,
                kind="url",
                source_type="url",
                url=url,
                summary=summary,
                excerpt=excerpt,
                text=text,
            )
        )
    return db.get_deal(deal_id)


@app.post("/deals/{deal_id}/urls")
async def add_url(deal_id: str, payload: UrlCreate) -> DealAnalysis:
    ensure_deal(deal_id)
    text = await fetch_url_text(payload.url)
    summary, excerpt = summarize(text)
    db.add_material(
        SourceMaterial(
            id=f"mat-{uuid.uuid4().hex[:10]}",
            deal_id=deal_id,
            name=payload.name or payload.url,
            kind="url",
            source_type="url",
            url=payload.url,
            summary=summary,
            excerpt=excerpt,
            text=text,
        )
    )
    return db.get_deal(deal_id)


@app.post("/deals/{deal_id}/analyze")
def analyze_deal(deal_id: str) -> DealAnalysis:
    ensure_deal(deal_id)
    try:
        run_diligence(deal_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return db.get_deal(deal_id)


@app.post("/deals/{deal_id}/analyze-stream")
def analyze_deal_stream(deal_id: str) -> StreamingResponse:
    ensure_deal(deal_id)

    def stream():
        done = object()
        events: Queue[str | object] = Queue()

        def emit(event: str, step: str, payload: dict[str, int | str] | None = None) -> None:
            message = {"event": event, "step": step, **(payload or {})}
            events.put(f"data: {json.dumps(message)}\n\n")

        def run() -> None:
            try:
                emit("run_start", "agent", {"label": "Starting diligence agent"})
                run_diligence(deal_id, on_progress=emit)
                deal = db.get_deal(deal_id)
                emit(
                    "run_complete",
                    "agent",
                    {
                        "label": ANALYSIS_COMPLETE_LABEL,
                        "claims": len(deal.claims),
                        "evidence": len(deal.evidence),
                    },
                )
            except Exception as exc:
                emit("run_error", "agent", {"label": str(exc)})
            finally:
                events.put(done)

        Thread(target=run, daemon=True).start()

        while True:
            item = events.get()
            if item is done:
                break
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/deals/{deal_id}/chat")
def chat(deal_id: str, payload: ChatRequest) -> ChatAnswer:
    ensure_deal(deal_id)
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")
    answer = answer_question(deal_id, payload.question.strip())
    db.save_chat(f"chat-{uuid.uuid4().hex[:10]}", deal_id, payload.question.strip(), answer.model_dump())
    return answer


@app.patch("/deals/{deal_id}/claims/{claim_id}/review")
def update_claim_review(deal_id: str, claim_id: str, payload: ClaimReviewPatch) -> DealAnalysis:
    ensure_deal(deal_id)
    try:
        db.update_claim_review(
            deal_id,
            claim_id,
            status=payload.status,
            reviewer_status=payload.reviewerStatus,
            reviewer_notes=payload.reviewerNotes,
        )
        refresh_review_artifacts(deal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Claim not found")
    return db.get_deal(deal_id)


@app.get("/deals/{deal_id}/export-memo")
def export_memo(deal_id: str) -> PlainTextResponse:
    deal = ensure_deal(deal_id)
    if not deal.memo:
        raise HTTPException(status_code=404, detail="Memo has not been generated")
    return PlainTextResponse(
        memo_to_markdown(deal.memo),
        headers={"Content-Disposition": f'attachment; filename="{EXPORT_MEMO_FILENAME}"'},
    )


def add_text_material(deal_id: str, name: str, text: str, source_type: str) -> None:
    summary, excerpt = summarize(text)
    db.add_material(
        SourceMaterial(
            id=f"mat-{uuid.uuid4().hex[:10]}",
            deal_id=deal_id,
            name=name,
            kind=infer_kind(name),  # type: ignore[arg-type]
            source_type=source_type,  # type: ignore[arg-type]
            summary=summary,
            excerpt=excerpt,
            text=text,
        )
    )


def ensure_deal(deal_id: str) -> DealAnalysis:
    try:
        return db.get_deal(deal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Deal not found")
