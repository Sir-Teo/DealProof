from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import DATABASE_FILENAME, DEFAULT_STAGE, DEFAULT_TAGLINE
from .models import ChatTurn, DealAnalysis, DealClaim, DealProfile, EvidenceItem, QualityReview, RiskMemo, SourceMaterial
from .scoring import score_claims

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / DATABASE_FILENAME


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 30000")
    conn.execute("pragma journal_mode = wal")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            f"""
            create table if not exists deals (
              id text primary key,
              company text not null,
              tagline text not null default '{DEFAULT_TAGLINE}',
              stage text not null default '{DEFAULT_STAGE}',
              status text not null default 'draft',
              error text,
              generated_at text,
              created_at text not null default current_timestamp
            );

            create table if not exists materials (
              id text primary key,
              deal_id text not null references deals(id) on delete cascade,
              name text not null,
              kind text not null,
              source_type text not null,
              path text,
              url text,
              summary text not null default '',
              excerpt text not null default '',
              text text not null default ''
            );

            create table if not exists claims (
              id text not null,
              deal_id text not null references deals(id) on delete cascade,
              text text not null,
              category text not null,
              source_material text not null,
              source_snippet text not null,
              importance text not null,
              status text not null,
              risk_rationale text not null,
              confidence text not null default 'low',
              quality_score integer not null default 0,
              quality_issues text not null default '[]',
              verification_need text not null default '',
              decision_impact text not null default 'medium',
              reviewer_status text not null default 'unreviewed',
              reviewer_notes text not null default '',
              primary key (deal_id, id)
            );

            create table if not exists evidence (
              id text not null,
              deal_id text not null references deals(id) on delete cascade,
              claim_id text not null,
              title text not null,
              source_type text not null,
              citation text not null,
              snippet text not null,
              stance text not null,
              reliability text not null,
              source_independence text not null default 'internal',
              relevance_score real not null default 0,
              quote_span text,
              source_material_id text,
              source_name text,
              source_url text,
              chunk_index integer,
              retrieved_at text,
              primary key (deal_id, id)
            );

            create table if not exists memos (
              deal_id text primary key references deals(id) on delete cascade,
              payload text not null
            );

            create table if not exists deal_profiles (
              deal_id text primary key references deals(id) on delete cascade,
              payload text not null
            );

            create table if not exists quality_reviews (
              deal_id text primary key references deals(id) on delete cascade,
              payload text not null
            );

            create table if not exists chats (
              id text primary key,
              deal_id text not null references deals(id) on delete cascade,
              question text not null,
              answer text not null,
              citations text not null,
              confidence text not null,
              created_at text not null default current_timestamp
            );
            """
        )
        ensure_column(conn, "claims", "confidence", "text not null default 'low'")
        ensure_column(conn, "claims", "quality_score", "integer not null default 0")
        ensure_column(conn, "claims", "quality_issues", "text not null default '[]'")
        ensure_column(conn, "claims", "verification_need", "text not null default ''")
        ensure_column(conn, "claims", "decision_impact", "text not null default 'medium'")
        ensure_column(conn, "claims", "reviewer_status", "text not null default 'unreviewed'")
        ensure_column(conn, "claims", "reviewer_notes", "text not null default ''")
        ensure_column(conn, "evidence", "source_independence", "text not null default 'internal'")
        ensure_column(conn, "evidence", "relevance_score", "real not null default 0")
        ensure_column(conn, "evidence", "quote_span", "text")
        ensure_column(conn, "evidence", "source_material_id", "text")
        ensure_column(conn, "evidence", "source_name", "text")
        ensure_column(conn, "evidence", "source_url", "text")
        ensure_column(conn, "evidence", "chunk_index", "integer")
        ensure_column(conn, "evidence", "retrieved_at", "text")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"alter table {table} add column {column} {definition}")


def list_deals_summary() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            select d.id, d.company, d.stage, d.status, d.generated_at,
                   m.payload as memo_payload,
                   (select count(*) from materials where deal_id = d.id) as material_count
            from deals d
            left join memos m on m.deal_id = d.id
            order by d.created_at desc
            limit 50
            """
        ).fetchall()
    result = []
    for row in rows:
        grade = None
        if row["memo_payload"]:
            try:
                grade = json.loads(row["memo_payload"]).get("overallGrade")
            except Exception:
                pass
        result.append({
            "id": row["id"],
            "company": row["company"] or "Untitled",
            "stage": row["stage"],
            "status": row["status"],
            "generatedAt": row["generated_at"],
            "grade": grade,
            "materialCount": row["material_count"],
        })
    return result


def create_deal(deal_id: str, company: str, tagline: str = DEFAULT_TAGLINE, stage: str = DEFAULT_STAGE) -> None:
    with connect() as conn:
        conn.execute(
            "insert into deals (id, company, tagline, stage, status) values (?, ?, ?, ?, 'draft')",
            (deal_id, company, tagline, stage),
        )


def update_deal_status(deal_id: str, status: str, error: str | None = None, generated_at: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "update deals set status = ?, error = ?, generated_at = coalesce(?, generated_at) where id = ?",
            (status, error, generated_at, deal_id),
        )


def add_material(material: SourceMaterial) -> None:
    with connect() as conn:
        conn.execute(
            """
            insert or replace into materials
            (id, deal_id, name, kind, source_type, path, url, summary, excerpt, text)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                material.id,
                material.deal_id,
                material.name,
                material.kind,
                material.source_type,
                material.path,
                material.url,
                material.summary,
                material.excerpt,
                material.text,
            ),
        )
        conn.execute("update deals set status = 'materials_loaded' where id = ?", (material.deal_id,))


def get_materials(deal_id: str) -> list[SourceMaterial]:
    with connect() as conn:
        rows = conn.execute("select * from materials where deal_id = ? order by name", (deal_id,)).fetchall()
    return [
        SourceMaterial(
            id=row["id"],
            deal_id=row["deal_id"],
            name=row["name"],
            kind=row["kind"],
            source_type=row["source_type"],
            path=row["path"],
            url=row["url"],
            summary=row["summary"],
            excerpt=row["excerpt"],
            text=row["text"],
        )
        for row in rows
    ]


def chat_turn_from_row(row: sqlite3.Row) -> ChatTurn:
    return ChatTurn(
        id=row["id"],
        dealId=row["deal_id"],
        question=row["question"],
        answer=row["answer"],
        citations=json.loads(row["citations"]),
        confidence=row["confidence"],
        createdAt=row["created_at"],
    )


def get_chats(deal_id: str, limit: int | None = None) -> list[ChatTurn]:
    query = "select * from chats where deal_id = ? order by created_at, rowid"
    params: tuple[Any, ...] = (deal_id,)
    if limit is not None:
        query = f"""
            select * from (
              select rowid as chat_rowid, * from chats where deal_id = ? order by created_at desc, rowid desc limit ?
            ) order by created_at, chat_rowid
        """
        params = (deal_id, limit)
    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [chat_turn_from_row(row) for row in rows]


def save_analysis(
    deal_id: str,
    claims: list[DealClaim],
    evidence: list[EvidenceItem],
    memo: RiskMemo,
    quality_review: QualityReview,
    generated_at: str,
    profile: DealProfile | None = None,
) -> None:
    with connect() as conn:
        conn.execute("delete from claims where deal_id = ?", (deal_id,))
        conn.execute("delete from evidence where deal_id = ?", (deal_id,))
        conn.execute("delete from memos where deal_id = ?", (deal_id,))
        conn.execute("delete from deal_profiles where deal_id = ?", (deal_id,))
        conn.execute("delete from quality_reviews where deal_id = ?", (deal_id,))
        for claim in claims:
            conn.execute(
                """
                insert into claims
                (id, deal_id, text, category, source_material, source_snippet, importance, status, risk_rationale,
                 confidence, quality_score, quality_issues, verification_need, decision_impact, reviewer_status, reviewer_notes)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.id,
                    deal_id,
                    claim.text,
                    claim.category,
                    claim.sourceMaterial,
                    claim.sourceSnippet,
                    claim.importance,
                    claim.status,
                    claim.riskRationale,
                    claim.confidence,
                    claim.qualityScore,
                    json.dumps(claim.qualityIssues),
                    claim.verificationNeed,
                    claim.decisionImpact,
                    claim.reviewerStatus,
                    claim.reviewerNotes,
                ),
            )
        for item in evidence:
            conn.execute(
                """
                insert into evidence
                (id, deal_id, claim_id, title, source_type, citation, snippet, stance, reliability,
                 source_independence, relevance_score, quote_span, source_material_id, source_name, source_url,
                 chunk_index, retrieved_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    deal_id,
                    item.claimId,
                    item.title,
                    item.sourceType,
                    item.citation,
                    item.snippet,
                    item.stance,
                    item.reliability,
                    item.sourceIndependence,
                    item.relevanceScore,
                    item.quoteSpan,
                    item.sourceMaterialId,
                    item.sourceName,
                    item.sourceUrl,
                    item.chunkIndex,
                    item.retrievedAt,
                ),
            )
        conn.execute("insert into memos (deal_id, payload) values (?, ?)", (deal_id, memo.model_dump_json()))
        if profile:
            conn.execute("insert into deal_profiles (deal_id, payload) values (?, ?)", (deal_id, profile.model_dump_json()))
        conn.execute("insert into quality_reviews (deal_id, payload) values (?, ?)", (deal_id, quality_review.model_dump_json()))
        conn.execute(
            "update deals set status = 'completed', error = null, generated_at = ? where id = ?",
            (generated_at, deal_id),
        )


def get_deal(deal_id: str) -> DealAnalysis:
    with connect() as conn:
        deal = conn.execute("select * from deals where id = ?", (deal_id,)).fetchone()
        if not deal:
            raise KeyError(deal_id)
        claims = conn.execute("select * from claims where deal_id = ? order by id", (deal_id,)).fetchall()
        evidence = conn.execute("select * from evidence where deal_id = ? order by id", (deal_id,)).fetchall()
        profile_row = conn.execute("select payload from deal_profiles where deal_id = ?", (deal_id,)).fetchone()
        memo_row = conn.execute("select payload from memos where deal_id = ?", (deal_id,)).fetchone()
        review_row = conn.execute("select payload from quality_reviews where deal_id = ?", (deal_id,)).fetchone()
    parsed_claims = [
        DealClaim(
            id=row["id"],
            text=row["text"],
            category=row["category"],
            sourceMaterial=row["source_material"],
            sourceSnippet=row["source_snippet"],
            importance=row["importance"],
            status=row["status"],
            riskRationale=row["risk_rationale"],
            confidence=row["confidence"],
            qualityScore=row["quality_score"],
            qualityIssues=json.loads(row["quality_issues"]),
            verificationNeed=row["verification_need"],
            decisionImpact=row["decision_impact"],
            reviewerStatus=row["reviewer_status"],
            reviewerNotes=row["reviewer_notes"],
        )
        for row in claims
    ]
    parsed_evidence = [
        EvidenceItem(
            id=row["id"],
            claimId=row["claim_id"],
            title=row["title"],
            sourceType=row["source_type"],
            citation=row["citation"],
            snippet=row["snippet"],
            stance=row["stance"],
            reliability=row["reliability"],
            sourceIndependence=row["source_independence"],
            relevanceScore=row["relevance_score"],
            quoteSpan=row["quote_span"],
            sourceMaterialId=row["source_material_id"],
            sourceName=row["source_name"],
            sourceUrl=row["source_url"],
            chunkIndex=row["chunk_index"],
            retrievedAt=row["retrieved_at"],
        )
        for row in evidence
    ]
    quality_review = QualityReview.model_validate(json.loads(review_row["payload"])) if review_row else None
    return DealAnalysis(
        id=deal["id"],
        company=deal["company"],
        tagline=deal["tagline"],
        stage=deal["stage"],
        status=deal["status"],
        error=deal["error"],
        generatedAt=deal["generated_at"],
        materials=get_materials(deal_id),
        claims=parsed_claims,
        evidence=parsed_evidence,
        profile=DealProfile.model_validate(json.loads(profile_row["payload"])) if profile_row else None,
        memo=RiskMemo.model_validate(json.loads(memo_row["payload"])) if memo_row else None,
        qualityReview=quality_review,
        score=score_claims(parsed_claims, parsed_evidence, quality_review) if parsed_claims else None,
        chatHistory=get_chats(deal_id),
    )


def update_claim_review(
    deal_id: str,
    claim_id: str,
    status: str | None = None,
    reviewer_status: str | None = None,
    reviewer_notes: str | None = None,
) -> None:
    assignments: list[str] = []
    values: list[str] = []
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
    if reviewer_status is not None:
        assignments.append("reviewer_status = ?")
        values.append(reviewer_status)
    if reviewer_notes is not None:
        assignments.append("reviewer_notes = ?")
        values.append(reviewer_notes)
    if not assignments:
        return
    values.extend([deal_id, claim_id])
    with connect() as conn:
        result = conn.execute(
            f"update claims set {', '.join(assignments)} where deal_id = ? and id = ?",
            values,
        )
        if result.rowcount == 0:
            raise KeyError(claim_id)


def save_review_artifacts(deal_id: str, memo: RiskMemo, quality_review: QualityReview) -> None:
    with connect() as conn:
        conn.execute("delete from memos where deal_id = ?", (deal_id,))
        conn.execute("delete from quality_reviews where deal_id = ?", (deal_id,))
        conn.execute("insert into memos (deal_id, payload) values (?, ?)", (deal_id, memo.model_dump_json()))
        conn.execute("insert into quality_reviews (deal_id, payload) values (?, ?)", (deal_id, quality_review.model_dump_json()))


def save_chat(chat_id: str, deal_id: str, question: str, payload: dict[str, Any]) -> ChatTurn:
    with connect() as conn:
        conn.execute(
            "insert into chats (id, deal_id, question, answer, citations, confidence) values (?, ?, ?, ?, ?, ?)",
            (chat_id, deal_id, question, payload["answer"], json.dumps(payload["citations"]), payload["confidence"]),
        )
        row = conn.execute("select * from chats where id = ?", (chat_id,)).fetchone()
    return chat_turn_from_row(row)
