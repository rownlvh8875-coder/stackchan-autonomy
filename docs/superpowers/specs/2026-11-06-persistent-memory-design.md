# Persistent metadata memory

User asked to continue the next project task after voice and Windows CI. The next
hardware-independent roadmap item is DEVELOPMENT_BRIEF §10 / NEXT_STEPS Phase5.4.
Implementation choices below are the implementer's defaults within that request.

Extend the existing optional `STACKCHAN_MEMORY_PATH` SQLite memory. Default remains
in-memory; persistent control/quota storage is unchanged. Alternatives considered:
using the mandatory coordination DB would silently enable personal history;
JSON preferences beside the DB would split migration/atomicity. An independent,
versioned SQLite component preserves explicit opt-in and existing interfaces.

Persist only closed event/intent/result metadata, successful speech/greeting times,
two typed preferences (`automatic_speech_enabled`, `minimum_speech_interval_s`) and
last observed connected/yaw/pitch with its timestamp. No text, keys or media accepted.
Preference interval can only increase the configured speech cooldown; explicit
VOICE_REQUEST retains its existing cooldown exemption. Disabling automatic speech
blocks background speech while touch/voice interactions remain available.

Scope data by control_resource. On migration, legacy unscoped history belongs only
to stackchan:default; copy only retained bounded valid metadata, atomically. Reject
unknown future schemas and invalid metadata without resetting or overwriting them.
Recent history is bounded by history_size and a configurable 7-day default retention
(60..31536000 seconds); speech/status timestamps also expire. Preferences last until
explicitly cleared. Clock rollback must not resurrect expired records. Speech times
survive history eviction, and live processes must see other processes' writes.
Review refinement: current schema version2 adds a separate logical speech suppression
guard; raw history timestamps still expire normally after rollback. Legacy/v1 migrations
and retained-data validation commit together. Retention covers cooldown in both modes.

Recorded robot pose is historical information, never restored or used to move the
robot. Memory storage failure with persistence enabled stops the engine; if it occurs
after an action, no retry is attempted. Complete optional-memory commands through a
separate `stackchan-memory` CLI: show, set, clear, scoped to configured resource.
Clear deletes this component's logical data, not leases/API quota or backups.

Verify real SQLite migration, retention, restart, process visibility, typed privacy,
engine preference enforcement, failure cleanup and CLI/wheel behavior. Continue the
existing offline Windows/Linux CI. No hardware, paid API or cloud environment publish.
