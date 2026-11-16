# Official MCP: completed 24-hour soak summary

Date: 2026-11-17 (KST). Status: PROPOSED; awaiting user design approval.
Small extension to the existing, live-verified official AI → PC tool bridge.

## Intent

The user asked to proceed with the recommended next step: ask the robot by voice
for the completed 24-hour test results. Keep the K151 factory firmware, official
app and existing `stackchan-pc-mcp` command. The official AI speaks the PC tool's
structured result; the PC bridge does not need an OpenAI or speech API.

## Approaches and proposed choice

1. **Bundle the one verified historical report (recommended).** It works without
   configuring paths, including in an independent wheel installation. The result
   explicitly identifies a historical PC Fake/Mock test. It does not discover
   or monitor future tests.
2. **Let the operator configure a local report path.** This could support later
   reports, but adds path setup, file validation and report-selection mistakes
   to this first voice feature.

Assistant's proposed choice: option 1, matching the already completed test the
user wants to hear about. No report/path argument is exposed to the AI. Updating
the selected historical report is a later deliberate repository change.

## Source and output

The authoritative source is the unchanged
[home Windows 24-hour PASS report](../../validation/2026-11-15-windows-home-soak-24h-passed.json).
Its recorded date is the report receipt date, **2026-11-15 KST**; the report has
no execution start/end timestamps or source revision. Do not invent these.

Add `stackchan_pc_soak_report_summary` with no arguments and read-only annotations.
Its description includes Korean wording for “24시간 시험 결과 알려줘”. Return a
small structured summary with fixed report identity/date/scope labels and the
validated numeric results:

- PASS, actual elapsed time 86,400.047 seconds and requested time 86,400 seconds;
- 83,157 cycles; 332 restarts and 332 restoration checks;
- Python-traced memory growth 20,697 bytes;
- task growth 0, remaining tasks 0, cloud requests 0, no violations/failure.

The scope is **PC Fake/Mock, real wall-clock duration**, not an accelerated virtual
run or a 24-hour physical-device test. Python-traced memory is not total process
memory. These scope labels accompany every response, so the official AI has the
information needed to describe the result accurately. The summary is historical,
not a current running-test status or a fresh measurement.

## Boundaries and implementation choices

- Preserve the existing connection diagnostic tool, code and call counter.
- Emit a distinct `PC_SOAK_REPORT_CALLED=N` marker for summary invocations so the
  operator can verify that this new tool was actually called.
- Read only the fixed bundled report; never scan directories, read `.local`,
  accept remote paths/URLs, or expose arbitrary JSON strings from a file.
- Preserve the original report bytes. Packaging/source checks must detect drift
  between the bundled resource and the authoritative checked-in report.
- Validate bounded input and required result fields. A missing, malformed or
  inconsistent resource returns a fixed unavailable error; never substitute PASS,
  disclose file paths, raw contents, exception text or the MCP endpoint.
- No new dependency, endpoint, listening port, reconnect, firmware change, device
  action, media capture or application database access. Existing transport bounds
  and hidden endpoint entry remain in place.
- Resource layout and schema details are builder decisions. Source/editable and
  independent wheel installations must all support the same fixed report.

## Verification and operator acceptance

Use the existing real local WebSocket/MCP SDK tests to verify listing/calling both
tools, unknown-argument rejection, numeric provenance, separate invocation markers,
and safe unavailable behavior. Exercise invalid/missing report data without a real
endpoint. Build and independently install the wheel, then query the summary from
outside the source checkout; verify the bundled report matches the source.

Run the appropriate offline suite and existing Windows/Linux CI before handoff.
Update the Korean operator guide with the voice request and expected numbers.
After updating/restarting the bridge on the laptop, the operator asks the robot
for the 24-hour result, observes the new marker, and confirms the spoken PASS,
24-hour duration and PC Fake/Mock scope. Until that observation, this new voice
feature's live acceptance remains pending; the earlier connection PASS stands.
