# OpenCode Go as the model host

Owner decision, 2026-10-22: production calls models through the owner's OpenCode Go
subscription instead of OpenRouter. DeepSeek V4.1 Flash writes; GPT 6 Luna reviews, so the
reviewer is a different model family from the writer.

OpenCode's terms say the service is for "your own internal use, and not on behalf of or for
the benefit of any third party", and Go is described as being for coding-agent traffic. A
public site serves third parties. The owner accepted that risk for a small hobby project. If
the account is suspended, every answer falls back to the deterministic path; switching back
is a configuration change (see below).

## What Go needed (probed 2026-10-22)

| Question | Answer |
| --- | --- |
| DeepSeek on Chat Completions | yes, at `https://opencode.ai/inference/go/openai/v1` |
| DeepSeek reasoning by default | on (72 reasoning tokens on a toy prompt); `reasoning_effort: "none"` turns it off |
| GPT 6 Luna on Chat Completions | no, `ModelProtocolUnsupported`; it answers on the Responses API |
| Per-call cost in the response | none; the ledger would otherwise settle the flat $0.01 reservation per call |
| Client identity | Go asks for a named `User-Agent` and an `x-opencode-session` id |

## Code

- `llm_wire.py`: one table of wire protocols (`chat`, `responses`), each a request builder and
  a reply parser into one normalized shape. `AI_MODEL_PROTOCOLS` maps a model to its protocol.
- Non-OpenRouter chat hosts get `reasoning_effort`; OpenRouter keeps its `reasoning` block, and
  its request bytes are unchanged (`w3-routing/payload_probe.py` passes).
- `AI_MODEL_PRICES` (USD per million input/output tokens) prices calls when the host reports no
  cost. DeepSeek is priced at Go's peak rate, so the ledger never undercounts.
- `ANALYST_REVIEW_MODEL` selects the reviewer; `configure_reviewer` applies it in production and
  in every replay or measurement tool. A reviewer outside the allowlist fails the review closed,
  and preflight reports it.
- Each analyst turn sends a random session id, never the user's session token.
- Health and preflight no longer assume OpenRouter (`model_provider`, `KNOWN_PROVIDERS`).

## Smoke

`smoke-7.json`: one question per category, real Go calls. Every writer call went to
`deepseek-v4.1-flash` over chat and every review to `gpt-6-luna` over responses, all with
`finish_reason=stop` and no reasoning tokens. 5 of 7 met the honest scorer. One trial of seven
questions; not a quality measurement.

## Switching back to OpenRouter

Set `AI_PROVIDER=openrouter`, `AI_BASE_URL=https://openrouter.ai/api/v1`, model ids with their
`deepseek/` and `openai/` prefixes in `AI_CHAT_MODEL`, `ANALYST_REVIEW_MODEL` and the
allowlist, and clear `AI_MODEL_PROTOCOLS` and `AI_MODEL_PRICES`.

## Not done

- Production has not been changed. `render.yaml` is updated, automatic deploys are off, and the
  Go key has to be set as `AI_API_KEY` in the Render dashboard.
- The pending live measurements now run on Go. Latency and cost results describe Go, not
  OpenRouter; the OpenRouter routing study no longer applies.
- Setting names still carry the `OPENROUTER_` prefix (`OPENROUTER_ALLOWED_MODELS`,
  `OPENROUTER_MONTHLY_CUTOFF_USD`) although they apply to any host.
