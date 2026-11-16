# KnicksIQ web

One fixed-light conversation about the Knicks’ 2025–26 season. The public product lives at `/`. Privacy, terms, and explicit feedback remain standalone utilities. Retired application URLs redirect to chat. There is no archive readiness request, public evidence view, or theme provider.

## Local development

Use the pinned pnpm version in `package.json`.

```sh
pnpm install --frozen-lockfile
pnpm dev
```

The development server proxies `/api` to loopback port 8000. Configure the API separately. Production chat needs Redis and a configured model provider; missing dependencies are recovery states, not mocked replies.

`VITE_API_URL` defaults to `/api`. The container’s Nginx proxy forwards that prefix to the API service and disables response buffering. A static Netlify deployment must set `VITE_API_URL` to its approved HTTPS API origin at build time and configure that origin’s CORS allowlist. Netlify deliberately returns 404 for `/api/*` rather than serving successful SPA HTML. It does not provide a streaming API proxy or pretend that static `/health` is a backend health check. Use the API origin’s real health endpoints for readiness.

## Ownership

- `src/chat/domain.ts` names exchanges, attempts, canonical snapshots, and lifecycle states.
- `src/chat/controller.ts` owns tab storage, capability creation, commands, reconciliation, cancellation, and New chat epoch fencing.
- `src/chat/transport.ts` validates bounded JSON and incremental SSE at the network boundary.
- `src/chat/chat.tsx` renders SDK Textarea, Button, Menu, and ScrollArea parts. The SDK owns keyboard composition, textarea sizing, menu focus, and live-edge following.
- `src/main.tsx` creates the SDK agent bridge before React renders. `window.knicksUI` exposes its documented snapshot/action API. It does not register WebMCP or expose chat access tokens.
- `src/lib/telemetry.ts` reduces configured error telemetry to a fixed redacted event. Session replay, breadcrumbs, and tracing are disabled.

The tab persists its draft, capability, and pending command before sending. Refresh reads the canonical server snapshot and never regenerates a reply. Stop keeps the server-owned prefix. Retry explicitly replaces the latest stopped/interrupted attempt without another user message. New chat clears current-tab state, attempts to stop old work, and does not delete retained server records.

## Verification

No browser API mocks or production URLs are used by the chat suite. Build with the relative local proxy before running it.

```sh
VITE_API_URL=/api pnpm build
pnpm test
pnpm lint
pnpm exec prettier --check src index.html public README.md package.json vite.config.ts playwright*.ts
pnpm knip
```

`pnpm test` uses `playwright.chat.config.ts` through the default Playwright configuration. It starts the isolated provider-free API runtime and a preview of `dist`. The coordinator prepares Python dependencies, disposable PostgreSQL, and Redis as documented in `.audit/season-chat-rehaul/proof/`. Do not point it at production. `CHAT_E2E_API_URL` and `CHAT_E2E_BASE_URL` accept only HTTP loopback origins for externally managed local services.

The retained telemetry transport probe is separate and requires a dedicated loopback DSN build.

```sh
VITE_API_URL=/api VITE_SENTRY_DSN=http://public@127.0.0.1:19499/1 pnpm build
KNICKSIQ_TELEMETRY_E2E=1 pnpm test:telemetry
```

That probe captures a real SDK envelope at a local sink. It verifies that both private exception names and messages are absent from transported data. Rebuild without the probe DSN afterward. Scripted upstream fixtures prove protocol and UI behavior, not real-provider voice, factual quality, hosted SSE delivery, or deployment readiness.
