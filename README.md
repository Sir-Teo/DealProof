# DealProof

DealProof is an AI diligence red team for VC and PE investors. It turns messy deal materials into a claim ledger, maps each claim to evidence, grades risk, generates follow-up questions, and exports a partner-ready investment committee memo.

The MVP is optimized for the Raylu Build & Pitch demo. It uses a deterministic fictional dental billing AI deal packet so the live workflow is reliable, with optional DeepSeek-backed Q&A when `DEEPSEEK_API_KEY` is available in the server environment.

## Run

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## Test

```bash
npm test
npm run build
npm run e2e
```

## Demo Flow

1. Start on Upload and show the loaded deck, founder transcript, financial snapshot, and website capture.
2. Click Analyze Packet.
3. Walk through extracted claims and status counts.
4. Open the evidence drawer for the contradicted competitor claim and the missing TAM claim.
5. Generate/export the risk memo.
6. Ask: "Can we trust the ROI claim?"

## API Routes

- `GET /api/analyze` returns the deterministic demo analysis.
- `POST /api/chat` answers diligence questions with DeepSeek when configured, otherwise with fixture-backed logic.
- `GET /api/export-memo` downloads the memo as Markdown.
