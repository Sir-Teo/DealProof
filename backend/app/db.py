from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import DATABASE_FILENAME, DEFAULT_STAGE, DEFAULT_TAGLINE
from .models import DealAnalysis, DealClaim, EvidenceItem, RiskMemo, SourceMaterial

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / DATABASE_FILENAME


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
              primary key (deal_id, id)
            );

            create table if not exists memos (
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


def save_analysis(deal_id: str, claims: list[DealClaim], evidence: list[EvidenceItem], memo: RiskMemo, generated_at: str) -> None:
    with connect() as conn:
        conn.execute("delete from claims where deal_id = ?", (deal_id,))
        conn.execute("delete from evidence where deal_id = ?", (deal_id,))
        conn.execute("delete from memos where deal_id = ?", (deal_id,))
        for claim in claims:
            conn.execute(
                """
                insert into claims
                (id, deal_id, text, category, source_material, source_snippet, importance, status, risk_rationale)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        for item in evidence:
            conn.execute(
                """
                insert into evidence
                (id, deal_id, claim_id, title, source_type, citation, snippet, stance, reliability)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        conn.execute("insert into memos (deal_id, payload) values (?, ?)", (deal_id, memo.model_dump_json()))
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
        memo_row = conn.execute("select payload from memos where deal_id = ?", (deal_id,)).fetchone()
    return DealAnalysis(
        id=deal["id"],
        company=deal["company"],
        tagline=deal["tagline"],
        stage=deal["stage"],
        status=deal["status"],
        error=deal["error"],
        generatedAt=deal["generated_at"],
        materials=get_materials(deal_id),
        claims=[
            DealClaim(
                id=row["id"],
                text=row["text"],
                category=row["category"],
                sourceMaterial=row["source_material"],
                sourceSnippet=row["source_snippet"],
                importance=row["importance"],
                status=row["status"],
                riskRationale=row["risk_rationale"],
            )
            for row in claims
        ],
        evidence=[
            EvidenceItem(
                id=row["id"],
                claimId=row["claim_id"],
                title=row["title"],
                sourceType=row["source_type"],
                citation=row["citation"],
                snippet=row["snippet"],
                stance=row["stance"],
                reliability=row["reliability"],
            )
            for row in evidence
        ],
        memo=RiskMemo.model_validate(json.loads(memo_row["payload"])) if memo_row else None,
    )


def save_chat(chat_id: str, deal_id: str, question: str, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "insert into chats (id, deal_id, question, answer, citations, confidence) values (?, ?, ?, ?, ?, ?)",
            (chat_id, deal_id, question, payload["answer"], json.dumps(payload["citations"]), payload["confidence"]),
        )
