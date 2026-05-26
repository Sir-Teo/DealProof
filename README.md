# DealProof

DealProof is an AI diligence red team for VC and PE investors. It turns messy deal materials into a claim ledger, maps each claim to evidence, grades risk, generates follow-up questions, and exports a partner-ready investment committee memo.

The app is now a two-service MVP: a Next.js frontend and a Python FastAPI + LangGraph backend. DeepSeek powers extraction, evidence assessment, memo generation, and chat through an OpenAI-compatible API.

## Run

```bash
npm install
cd backend
uv sync
export DEEPSEEK_API_KEY=...
cd ..
npm run dev:all
```

Open `http://127.0.0.1:3000`. The backend runs at `http://127.0.0.1:8000`.

You can also run each service separately:

```bash
npm run backend
npm run dev
```

## Test

```bash
npm test
npm run test:backend
npm run build
npm run e2e
```

The default Playwright configuration starts the backend with an empty
`DEEPSEEK_API_KEY`, so the demo, real-case, and report-quality E2E tests run
against deterministic fallback analysis paths. To manually exercise the live LLM
path, start the backend yourself with `DEEPSEEK_API_KEY` set and then run the UI
or Playwright tests with the existing server reused.

Generated exported memo files belong in `generated_reports/` and are treated as
local demo/reference artifacts rather than source-controlled snapshots.

## Demo Flow

1. Start on Upload and click Load Harvey (legal AI) or Load SynthPay (fintech).
2. Click Run LangGraph Agent.
3. Walk through extracted claims and status counts.
4. Open the evidence drawer for weak/missing/contradicted claims.
5. Export the generated risk memo.
6. Ask: "Can we trust the market and model-dependency claims?"

## API Routes

- `POST /deals` creates a deal.
- `POST /deals/demo` creates the seeded Harvey legal AI packet.
- `POST /deals/demo2` creates the seeded SynthPay fintech packet.
- `POST /deals/{deal_id}/materials` uploads files or a supplied URL.
- `POST /deals/{deal_id}/analyze` runs the LangGraph diligence workflow.
- `GET /deals/{deal_id}` returns persisted deal state.
- `POST /deals/{deal_id}/chat` answers against stored claims/evidence.
- `GET /deals/{deal_id}/export-memo` downloads Markdown.
