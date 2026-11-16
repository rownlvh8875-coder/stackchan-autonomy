# Official MCP PC connection diagnostic — design

Date: 2026-11-16 (KST). Status: APPROVED for implementation by the user in chat.
Fresh builder check completed: nothing important left.

## 사용자에게 보이는 결과

출고 K151 V1.6.2와 StackChan World를 유지한다. Windows 노트북에서 전용 명령 하나를
실행하고, 앱의 MCP 접속주소를 노트북의 숨김 입력창에 붙여 넣는다.
연결 후 앱 MCP 목록에 PC 연결 확인 도구가 나타난다. 로봇에게
“PC 연결 확인 코드를 알려줘”라고 말하면, 노트북 화면과 같은 6자리 코드를 읽어 준다.
이는 실제 PC 도구 호출의 확인이며 로봇 자세·모터·마이크의 PC 직접 제어를 뜻하지 않는다.

## Intent and agreed choices

The user completed factory setup, service HTTP checks, LAN ping and the mobile app's
Local Network indication. See the [field record](../../validation/2026-11-16-k151-factory-bringup.md).
They explicitly chose to preserve the factory firmware/mobile app and complete
official-AI-to-PC tool integration before PC OpenAI direct robot control.
Assistant's proposed initial scope: one bounded, read-only connection diagnostic tool.

The existing autonomous engine and physical adapter blocks remain in place. The
official AI/voice service still handles conversation; this bridge does not route
microphone audio to OpenAI or replace the model. Voice service availability/billing
remains governed by the user's existing official service.

## Approaches

1. **Official external MCP tool endpoint, selected.** An outbound PC WebSocket
   presents a small MCP server to the official AI. Preserves firmware/app and has a
   documented extension precedent. It adds PC tools rather than PC-directed robot control.
2. **PC implementation of the factory Avatar transport, deferred.** Requires verifying
   production authentication/bootstrap, phone coexistence and ownership/stop behavior.
   Public source structure and LAN reachability alone do not establish a supported client.
3. **Custom firmware plus the audited HTTP gateway, rejected for this step.** It is
   closer to the engine's current simulated contract but changes the firmware/account path.

Sources: [manufacturer response](https://github.com/m5stack/StackChan/issues/126#issuecomment-6593389244),
[external endpoint example](https://github.com/c1pher-cn/ha-mcp-for-xiaozhi/blob/main/README.en.md).
No third-party code is copied. The linked example's `websocket_transport.py` was inspected:
each WebSocket TEXT message is a JSON-RPC MCP message wrapped into the SDK's SessionMessage;
outbound messages unwrap SessionMessage into JSON. No extra envelope was found there.
That example now targets SDK2; our implementation must use the pinned SDK1.30 public APIs,
without copying its reconnect/raw logging behavior. Actual service negotiation remains unverified.

## Parts and data flow

- New standalone `stackchan-pc-mcp` CLI and bridge module; Python >=3.11.
- Reuse pinned MCP SDK 1.30.0 public server APIs for initialization, tool listing,
  strict argument validation and tool calls. Do not reuse MCPRobotAdapter's HTTP client.
- Add one direct, locked WebSocket client dependency compatible with Python3.11/3.12;
  exact supported version is the builder's choice. No additional service or Home Assistant installation.
- PC starts the outbound TLS WebSocket to the operator's official MCP endpoint.
  The official backend initializes the PC's MCP server and invokes the advertised tool.
  No inbound listening port, router forwarding, firmware flash or mobile app modification.

## Tool contract

Name: `stackchan_pc_connection_status`. No arguments; reject unknown arguments.
Description includes Korean wording for asking for the PC connection check code.
Return JSON/text with only service identity, a run-specific 6-digit `check_code`,
process-monotonic `uptime_s`, call count and `robot_control_available=false`.
The diagnostic code is not an authentication secret. It is generated once per process
and printed locally; repeated calls keep that code and increment call count.
This response describes the running PC tool, not measured robot health or ownership.
No shell, file access, DB access, host/user identifiers, browser, motors, media or paid API calls.
Do not load app `.env`, engine Settings, OpenAI providers or operator application DBs.

## Configuration and privacy

- Default: hidden `getpass` console prompt for the endpoint. The Windows command itself
  contains no token, so it can be shared and does not put a secret in command history.
  An environment-variable input may be added for noninteractive operation; its value is
  never echoed, persisted or shown in errors. Non-TTY input must fail with a fixed message
  rather than fall back to echoing a secret.
- Accept only TLS `wss` to `api.xiaozhi.me`, default443, path `/mcp/` or `/mcp`, exactly
  one nonempty token query field, no userinfo/fragment or extra query fields. Preserve the
  validated original URL for connection. No CLI switch weakening TLS or host validation.
- The operator copies the actual endpoint locally. Never extract/use the screenshot's
  token, ask for it in chat, commit it or connect to it from the cloud environment.
- Print only fixed lifecycle/error codes and the diagnostic check code/call count.
  Never raw messages, URL, token, args, headers, server reason strings or tracebacks.
  Ensure SDK and WebSocket library logging cannot expose them, including debug/error paths.
- Token regeneration/revocation is outside the bridge. Do not promise that reopening
  the screen, generating another token, unbinding or resetting revokes a prior token.

## Bounds, lifecycle and errors

- One endpoint connection, one tool; bounded inbound frame size, response size, queue
  capacity and in-flight calls. Initial targets:16KiB input,64KiB output,16 queued
  messages and one active tool call. The builder may tighten these for observed protocol needs.
- Use normal WebSocket protocol keepalives. Initialization has a finite timeout separate
  from connection establishment; a normally initialized session can idle until Ctrl+C.
- Successful transport connection does not mean tools have been listed or invoked.
  Distinct fixed lifecycle markers show connection, initialization/catalog and tool invocation.
- No automatic reconnect/replay. Disconnect or protocol fault closes the session and
  exits with a fixed failure; restart is manual. Ctrl+C cancels/drains tasks and closes
  the socket, then exits130 without exporting raw errors. Invalid configuration exits2;
  connection/protocol failures exit1. `--help` exits0.
- No motor stop or device offline guarantee is inferred from closing this read-only bridge.

## Verification and acceptance

Before asking the user to run the new command:

1. Observe meaningful RED tests for URL/privacy boundaries and the actual MCP dialogue.
2. A local fake endpoint drives initialize/initialized, list and call through the real
   SDK and WebSocket transport; prove the matching per-run code and incrementing count.
3. Reject malformed/oversized/binary or unsupported frames, unexpected methods/arguments,
   wrong initialization order and disconnects. Check bounded work and shutdown cleanup.
4. Error paths containing sentinel URLs/tokens/server text must not leak to stdout/stderr
   or captured logs. No arbitrary file/engine/provider access should occur.
5. Run relevant/full offline tests, lint/format, package build and independent wheel CLI
   checks, then Windows/Linux CI on the existing feature branch. No real token/API/device
   is needed for these checks. Keep existing full-suite outcomes distinct from this feature.

Live acceptance, performed by the operator on the home laptop after the verified upload:
update checkout with one command, then run one CLI command and enter the endpoint locally.
App MCP catalog must show the PC tool. Ask the robot for the PC connection check code;
the robot answer must match the current local code and CLI must record an actual tool call.
For this spoken test, close the mobile Motion page and switch the robot from Avatar
back to AI Agent using its Home menu. Tool registration does not turn Avatar into a voice agent.
Keep separate outcomes for catalog registration, call arrival and spoken-code match.
Until those observations arrive, report live integration as unverified.

## Remaining work and builder decisions

The user approved implementing this design. The builder owns internal task supervision, test transport
seams, exact WebSocket version and small naming details consistent with this contract.
The single read-only tool is the whole initial scope. Other PC functions, automatic startup,
24h service management, motor/media control and the independent PC OpenAI engine are follow-ups.
