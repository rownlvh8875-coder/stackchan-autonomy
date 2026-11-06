# Phase 4 MCP Simulation Implementation Plan

> Execute inline with test-driven-development. Keep real actuation blocked.

**Goal:** Exercise the autonomy engine through real MCP sessions using an in-process
gateway simulator; implement conservative parsing and schema checks for Phase 4.
**Spec:** ../../DEVELOPMENT_BRIEF.md, ../../NEXT_STEPS.md.
**Architecture:** The default MCPRobotAdapter remains physical/read-only. A factory
creates its simulation subclass together with a local in-memory MCP server; neither
CLI flags nor environment settings can turn an arbitrary remote session into a simulator.
Shared adapter paths validate status, pose, image results, tool schemas, and session IDs.
Only the factory-owned simulator is permitted to execute those write paths.
**Tech:** Existing pinned dependencies, MCP SDK memory sessions, asyncio, Pydantic.

## Constraints
- Reuse the published checkout; no worktree, replay of prior changes, publication,
  paid API calls, real-device requests, firmware modifications or motor activation.
- Real capture/audio remain blocked until gateway retention and consent are verified.
- No dependency updates are needed. Do not rewrite the environment draft.
- Simulator is a bounded protocol fixture, not evidence of ESP32 timing or hardware.

## Review focus
Malformed success/error JSON; schema mismatch; device/session substitution; uncertain
ACK/cancellation; no remote path reads; local command ownership is not global ownership.

## Tasks
1. [x] Confirm published restore and 60-test baseline; read actual firmware reply
   contracts and update newly accessible official-doc audit evidence.
2. [x] Write failing tests for status/pose, tool schema intersections, errors,
   unavailable sensors, session changes and gated writes. Implement mcp_contract.py
   and harden mcp_robot.py without enabling physical execution.
3. [x] Add an in-memory gateway simulator using independently captured audited
   schemas; write failing integration tests for motor quantization/limits, images,
   touch/blink/LED, no-ACK-replay and serial cancellation. Keep real speech/STT blocked.
4. [x] Write failing CLI/engine tests for --mode mcp-sim and simulate the whole loop;
   implement factory-owned lifecycle and preserve default mock/cloud behavior.
5. [x] Run full pytest, Ruff and CLI/package checks; fresh read-only code review;
   resolve findings with regressions. Update README, TEST_REPORT, WORK_LOG and plans.

## Interface decisions
- MCPRobotAdapter.status() -> RobotStatus: read-only, actual absolute pose, no defaults.
- MCPRobotAdapter.execute/capture: reject when physical=True before contacting session.
- simulate_mcp_robot(...) -> async context manager yielding an adapter backed by
  its own in-memory server; physical=False only for this factory-owned session.
- CapabilityReport: distinguish advertised/supported, no physical permission claims.
- Faults latch on malformed replies, timeout, device/session changes or uncertain writes;
  never reconnect or replay implicitly. Commands are serialized within the adapter too.
