# KnicksIQ Web

Consumer-facing season archive for reliving the Knicks' 2025-26 season.

The public UI is intentionally one primary experience:

- Ask a grounded Knicks season question.
- Get an answer from available season data.
- Review fan-readable receipts from games and citations.
- Browse compact season highlights without admin/dashboard controls.

Answers are expected to be easy to skim:

- Short answer first.
- Key evidence next.
- Receipts/source games when available.
- Limitation note when the available data is not enough.

The public UI should avoid backend/internal language such as RAG, vector search,
Qdrant, embeddings, chunks, seeded data, and cached.

## Development

```bash
corepack enable pnpm
pnpm install --frozen-lockfile
pnpm dev
```

By default the app calls `/api`. For local API development:

```bash
VITE_API_URL=http://localhost:8000 pnpm dev
```

## Production Build

```bash
pnpm build
```

The static output is written to `dist/`.

## Environment

- `VITE_API_URL`: public API origin, for example `https://knicksiq-api.onrender.com`

No admin API key is exposed in the public frontend. Admin ingestion/report actions are
not part of the v1 consumer UI.
