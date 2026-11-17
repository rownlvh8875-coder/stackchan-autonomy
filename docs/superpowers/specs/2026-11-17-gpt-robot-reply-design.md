# GPT API answers through the factory robot

Date: 2026-11-17 KST. User-directed implementation: the user explicitly asked to
move ahead promptly with the final GPT API → robot answer goal and opted out of
further prerequisite discussion/tests. The user confirmed an API key is ready.
No key value was requested or provided. Implementation choices below are the
builder's defaults, not independently approved user choices.

## Result and route

Add an opt-in `stackchan-pc-mcp --gpt` mode. The factory voice service recognizes
speech and invokes `stackchan_gpt_reply(question)`. The Windows PC calls the user's
OpenAI Responses API and returns a validated Korean answer; the official service
speaks it. The two existing tools keep working without GPT enabled.

This is a separate API conversation with a Korean robot persona and bounded
in-memory context, not a transfer of this Codex chat/session. The official service
still chooses/invokes tools and handles voice; MCP cannot force every utterance
through GPT or replace the device's entire voice backend. Provide app Character
instructions for preferring the GPT tool and an explicit “GPT에게 물어봐” request
for reliable operator testing. Exact spoken fidelity still needs live acceptance.

## Approaches

1. **Extend the proven official MCP route, selected by builder.** Preserves the
   user's stock firmware/app preference and reaches a real GPT answer immediately.
   Official speech/tool orchestration remains in the path.
2. **Replace the voice backend with an independent STT → GPT → TTS gateway.** Closer
   to full backend ownership, but stock provisioning/authentication/audio transport
   remain unverified and may need firmware/account changes. Deferred, not silently
   claimed complete by this feature.

The inspected manufacturer source (`m5stack/StackChan`, cache SHA28b9f0c) exposes
agent model selection and Character, not a verified bring-your-own OpenAI key/base
URL field. Do not mutate agent binding, flash firmware or use the user's endpoint
from the cloud. API reference checked read-only:
https://developers.openai.com/api/reference/resources/responses/methods/create

## Contract

- New tool `stackchan_gpt_reply`: exactly one `question` string, trimmed length1–1200;
  reject unknown arguments, empty input, invalid Unicode/control characters before API use.
- Success: service `stackchan-gpt`, provider `openai_responses`, configured model,
  validated `answer` (1–800 characters), `robot_control_available=false`.
- Korean concise persona; strict JSON answer schema, `store=false`, max output600
  tokens, SDK retry0, configured operation timeout (existing default15s).
- Only text questions and the last3 successful user/assistant turns are sent.
  No images/audio, tool execution, shell, file lookup or hardware actions. History
  stays in memory, is bounded, and clears on process exit. Remote prompts cannot
  change input roles or provide system instructions/configuration.
- API model is explicitly configured with `STACKCHAN_OPENAI_MODEL`, never hardcoded.
  Key comes only from `OPENAI_API_KEY` in local `.env`/environment. GPT requires both
  `--gpt` and `STACKCHAN_CLOUD_ENABLED=true`. Default two-tool mode ignores app dotenv.
- Reuse existing Settings, persistent SQLiteRequestBudget and AsyncStorage. Default
  request limits2/minute,30/hour,100/day and shared state/namespace survive restarts.
  Reservations remain spent on failure/uncertainty; store usage counters, never text.
  These are request limits, not a currency-spending guarantee.
- Dial the official OpenAI base URL with redirects disabled; no caller-selected
  API URL or model. Preserve inherited TLS/proxy behavior. Suppress private SDK/HTTP
  logs as well as MCP/transport logs in this dedicated process.
- Fixed errors for configuration, question, budget, storage and API/response failure.
  No raw exception/body/question/answer/key/endpoint in console or logs. API failures
  return a tool error; no mock answer or automatic paid retry.
- Console markers distinguish `PC_GPT_READY`, `PC_GPT_CALLED=N`,
  `PC_GPT_ANSWERED=N`, and fixed error codes. Invocation alone does not prove success.
- Existing connection code/counter, report tool, frame/request bounds and manual
  reconnect behavior remain; no firmware/app reset or motor/STOP claim.

## Verification and acceptance

Use real pinned OpenAI SDK + local MockTransport and real SQLite to prove request
shape, response validation, bounded history, reservations across restart/failure,
timeouts/cancellation and privacy. Real local WebSocket/MCP SDK tests cover the third
tool, default two-tool compatibility, argument errors, counters and API failures.
CLI tests cover explicit configuration and no-echo errors; installed-wheel proof
uses a synthetic key and local HTTP transport only. Run full offline suite, lint,
package checks, fresh final review and Windows/Linux CI on the existing branch.

No cloud paid call is needed. Operator configures the key/model privately on the
home laptop, runs the GPT command, asks a new question, and confirms both ANSWERED
marker and robot answer. Record actual account/model/voice acceptance only after
that evidence. User says prior checks are okay; no measured1h/24h duration is inferred.
