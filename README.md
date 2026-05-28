# DealProof

DealProof is an AI diligence red team for VC and PE investors. It turns messy deal materials into a structured claim ledger, maps every claim to evidence, grades diligence risk, generates follow-up questions, and exports a partner-ready investment committee memo.

The hackathon MVP has two services:

- Next.js frontend for upload, demo loading, claim review, chat, and memo export.
- FastAPI + LangGraph backend for parsing, retrieval, claim extraction, evidence assessment, scoring, memo generation, and chat.

DeepSeek powers the live LLM path through an OpenAI-compatible API. Tests and demos can also run without an API key through deterministic fallback paths.

## Demo

```bash
npm install
cd backend && uv sync && cd ..
cp backend/.env.example backend/.env
npm run dev:all
```

Open `http://127.0.0.1:3000`. The backend runs at `http://127.0.0.1:8000`.

For the strongest live demo, set `DEEPSEEK_API_KEY` in `backend/.env`, then load either seeded packet:

1. Click `Load Harvey (legal AI)` or `Load SynthPay (fintech)`.
2. Click `Run agent`.
3. Review the claim ledger, evidence drawer, IC readiness workbench, and memo.
4. Export the Markdown memo or diligence-request list.
5. Ask a follow-up question such as `Can we trust the market and model-dependency claims?`

## Commands

```bash
npm run dev:all       # backend + frontend
npm run backend       # FastAPI only, on 127.0.0.1:8000
npm run dev           # Next.js only, on 127.0.0.1:3000
npm run check         # lint, frontend tests, backend tests, production build
npm run clean         # remove local generated runtime artifacts
```

## Environment

Backend settings live in `backend/.env`:

```bash
DEEPSEEK_API_KEY=your-key-here
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEALPROOF_WEB_SEARCH_ENABLED=1
```

The frontend uses `NEXT_PUBLIC_API_BASE_URL` when the API is not on `http://127.0.0.1:8000`.

## Test

```bash
npm run lint
npm test
npm run test:backend
npm run build
npm run e2e
```

The default Playwright configuration starts the backend with an empty `DEEPSEEK_API_KEY`, so the demo, real-case, and report-quality E2E tests run against deterministic fallback analysis paths. To manually exercise the live LLM path, start the backend yourself with `DEEPSEEK_API_KEY` set and reuse the existing server.

## API Routes

- `GET /health` checks backend readiness.
- `GET /deals` lists saved deals.
- `POST /deals` creates a blank deal.
- `POST /deals/demo` creates the seeded Harvey legal AI packet.
- `POST /deals/demo2` creates the seeded SynthPay fintech packet.
- `POST /deals/{deal_id}/materials` uploads files or a supplied URL.
- `POST /deals/{deal_id}/urls` adds a URL material.
- `POST /deals/{deal_id}/analyze` runs the diligence workflow.
- `POST /deals/{deal_id}/analyze-stream` streams workflow progress events.
- `GET /deals/{deal_id}` returns persisted deal state.
- `POST /deals/{deal_id}/chat` answers against stored claims and evidence.
- `PATCH /deals/{deal_id}/claims/{claim_id}/review` saves reviewer judgment.
- `GET /deals/{deal_id}/export-memo` downloads the red-team memo as Markdown.
- `GET /deals/{deal_id}/export-diligence-requests` downloads open diligence asks.

## Project Layout

```text
app/                  Next.js app UI
lib/                  Shared frontend config, scoring, readiness, and types
backend/app/          FastAPI routes, LangGraph workflow, parsing, retrieval, scoring
backend/tests/        Backend unit and workflow tests
backend/scripts/      Fixture and real-case helper scripts
e2e/                  Playwright demo and quality specs
tests/                Frontend unit tests
docs/                 Hackathon submission copy, demo script, architecture notes
```

Generated exports, local databases, uploaded files, build output, caches, and virtual environments are ignored by git.

## Submission Notes

DealProof is designed to show investor judgment rather than a generic document summary. It highlights which claims are supported, weak, contradicted, or missing, then turns unresolved risk into concrete diligence requests before IC.
