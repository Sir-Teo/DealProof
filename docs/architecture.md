# Architecture

DealProof is split into a Next.js client and a FastAPI backend so the demo can keep UI iteration, file parsing, retrieval, and LLM orchestration separate.

## Frontend

- `app/page.tsx` owns the single-screen diligence workspace: deal creation, seeded demos, material upload, streaming agent progress, claim review, chat, and exports.
- `lib/app-config.ts` centralizes UI copy and API base URL configuration.
- `lib/scoring.ts`, `lib/readiness.ts`, and `lib/types.ts` keep client-side display logic typed and testable.

## Backend

- `backend/app/main.py` exposes the REST and streaming endpoints.
- `backend/app/graph.py` runs the LangGraph diligence workflow.
- `backend/app/parsers.py` extracts text from uploaded files and URLs.
- `backend/app/retrieval.py` chunks materials and maps claims to local evidence.
- `backend/app/web_research.py` adds optional public-source evidence.
- `backend/app/scoring.py` turns claims, evidence, and reviewer state into memo-ready risk output.
- `backend/app/db.py` persists deals, materials, claims, evidence, reports, and chat history in local SQLite.

## Data Flow

1. A user creates a deal or loads a seeded demo packet.
2. Materials are parsed into text, summarized, and stored.
3. The diligence workflow extracts investor-relevant claims.
4. Local retrieval and optional web research gather evidence.
5. The scorer grades support level, risk, source quality, and IC readiness.
6. The app renders a claim ledger, evidence drawer, diligence asks, chat answers, and exportable Markdown memo.

## Local State

Runtime state is intentionally local for the hackathon MVP:

- SQLite databases are stored under `backend/data/`.
- Uploaded files are stored under `backend/storage/deals/`.
- Exported demo reports are stored under `generated_reports/` when created manually.

These paths are ignored by git and can be reset with `npm run clean`.
