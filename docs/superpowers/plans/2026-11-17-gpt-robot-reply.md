# GPT robot reply implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Produce GPT API answers on the PC and speak them through the factory robot.
**Architecture:** Opt-in third MCP tool backed by the official Responses SDK and
existing persistent request budget; stock voice service handles recognition/playback.
**Tech Stack:** Python>=3.11, existing openai3.46, MCP1.30, websockets15, SQLite/pytest.
**Spec:** [design](../specs/2026-11-17-gpt-robot-reply-design.md).
**Execution:** Native inline, preserving prior method and the user's explicit request
to proceed without further prerequisite discussion. Normal existing-branch push is authorized.

## Global Constraints

- Keep factory firmware/app; no motor/media/agent-binding changes or paid cloud test.
- Exactly `stackchan_gpt_reply(question)`; question1–1200 and answer1–800 characters.
- Explicit `--gpt`, cloud enabled and locally configured model/key; no hardcoded model.
- Responses strict answer JSON, store=false, max600 tokens, retry0, configured deadline.
- Persistent2/minute,30/hour,100/day reservations; bounded3-turn in-memory history only.
- Fixed public errors and markers; no question/answer/key/endpoint in logs or console.

## Review Focus

- An incomplete/refused/malformed API response must never be labeled ANSWERED.
- Restart or error must not replenish paid reservations; slow file I/O must not block the loop.
- Remote tool input must not change model/base URL/system roles or read operator files.
- API/HTTP debug logging and initialization errors must not reveal secrets or text.
- Default two-tool mode and independently installed GPT mode must both remain usable.

---

### Task 1: Bounded GPT reply service

**Files:** Create `src/stackchan_autonomy/gpt_chat.py`, shared
`src/stackchan_autonomy/private_logging.py`, `tests/test_gpt_chat.py`.
**Interfaces:** `GPTChat(settings: Settings, *, client=None, clock=time.time)`,
`async ask(question: str) -> dict[str, object]`, `async aclose()` and async context
manager; `GPTChatError` exposes only fixed public codes. Budget/Settings interfaces unchanged.

- [x] Write real SDK/MockTransport tests asserting selected model, literal question,
  strict JSON answer schema, store=false, max_output_tokens600 and no image/audio/tools.
  Assert returned Korean answer/source and that last3 successful turns alone are sent.
- [x] Test invalid/oversized/Unicode input before reservation; malformed/incomplete/
  refused/empty/oversized output,429/500/timeout each consumes one request and no retry.
  Test restart budget exhaustion, storage failure before network, cancellation, and
  no prompt/key/API body in logs. Observe missing-service RED.
- [x] Implement service with AsyncStorage and existing SQLiteRequestBudget. Use the
  fixed official API URL, disabled redirects, timeout and no retries. Record usage
  safely, validate structured answer, then append bounded successful history only.
- [x] Run `uv run --frozen pytest -q tests/test_gpt_chat.py`; expect all PASS. Commit.

### Task 2: Opt-in MCP/CLI and operator path

**Files:** Modify `src/stackchan_autonomy/official_mcp.py`, `official_mcp_cli.py`,
`src/stackchan_autonomy/settings.py` (optional reasoning effort, default unset),
`tests/test_official_mcp.py`, `tests/test_official_mcp_cli.py`, `scripts/ci_verify.py`;
add `docs/GPT_ROBOT.ko.md` and update README, next steps, test report, work log/evidence.
**Interfaces:** `run_bridge(endpoint, *, emit, gpt=None)` accepts Task1 service only
in opt-in mode; default call signature remains usable. CLI creates/closes service
inside privacy protection. `question` is the only remote-configurable value.

- [x] Add failing real WebSocket + SDK/local OpenAI transport tests: three tools in
  GPT mode, correct answer and independent CALLED/ANSWERED markers; default remains
  two tools. Invalid arguments and API/budget errors must not produce ANSWERED or
  leak private content. Exercise diagnostic calls after GPT failure.
- [x] Add failing CLI tests for --gpt configuration, hidden endpoint behavior, fixed
  config errors, no default dotenv reads, cancellation/cleanup and help with no I/O.
- [x] Implement conditional tool registration/dispatch, private OpenAI/HTTP logger
  handling, exact argument validation, lifecycle and configuration-only GPT startup.
- [x] Run target tests to PASS. Extend installed-wheel probe to use GPT with local
  HTTP transport/synthetic key and verify real SDK/MCP answer without live API.
- [x] Document local .env setup (key/model/cloud flag), one CMD command per step,
  Character prompt and explicit voice request, success/error markers and costs.
  Explain separate API session and official voice orchestration; live status pending.
- [x] Run full `uv run --frozen pytest -q`, Ruff check/format, docs/whitespace checks;
  build sdist/wheel and run independent `scripts/ci_verify.py --require-opus`.
  Expect all offline checks PASS. Commit; one fresh whole-change review and tested fix
  pass if needed, normal push, verify existing four hosted OS/Python CI jobs.
- [x] Record evidence and hand off local configuration/voice acceptance. Preserve
  API key privacy and never claim the existing1h/24h or new GPT voice test without evidence.

## Self-review

Task2 consumes Task1 exact service/error interface; no conflicting ownership.
All global constraints and five Review Focus classes have explicit tests/checks.
No new dependency, firmware work or independent voice backend is in this plan.
