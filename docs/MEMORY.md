# Optional metadata memory

Persistence stays **off by default**. Set `STACKCHAN_MEMORY_PATH` to a local SQLite
file to retain metadata across sessions. Parent directories are created as needed.
Use the same absolute path and `STACKCHAN_CONTROL_RESOURCE` for the same robot.
Control leases and API quotas remain in `STACKCHAN_STATE_PATH` regardless of this opt-in.

```powershell
$env:STACKCHAN_MEMORY_PATH = "C:/StackChanData/memory.sqlite3"
$env:STACKCHAN_CONTROL_RESOURCE = "stackchan:my-k151"
uv run --frozen stackchan-memory show
uv run --frozen stackchan-memory set --automatic-speech off --minimum-speech-interval 600
uv run --frozen stackchan-autonomy --mode mock --cycles 1 --person
uv run --frozen stackchan-memory show
# Explicit reset: deletes retained interactions/times/status and resets preferences.
uv run --frozen stackchan-memory clear
```

On Bash, use `export STACKCHAN_MEMORY_PATH=/absolute/path/memory.sqlite3`.
The management CLI accepts `--config path/to/robot.yaml` before show/set/clear;
environment > .env > YAML > defaults. Without a memory path it exits2 without
creating a memory DB. It never constructs a robot or API provider.

| Stored information | Contract |
|---|---|
| Recent interactions/actions | Time, closed event/intent/result codes; bounded by history_size |
| Last successful speech/greeting | Separate timestamps, survive history-count eviction |
| Preferences | automatic_speech_enabled bool, minimum_speech_interval_s 0..86400 |
| Last recorded robot observation | Observation time, connected, yaw, pitch; historical only |
| Schema/clock | Component version1, per-resource clock high-water mark |

No conversation text, model rationale, image, audio, name/biometric identity, secret,
command queue or saved motor target is accepted. Preferences are changed explicitly
through the CLI/API, never extracted automatically by a model. They cannot grant
cloud/media/hardware consent or relax motor/STOP/API limits. Historical pose is
not restored, trusted for current pose, or used to dispatch commands.

`automatic_speech_enabled=false` blocks speech from background events (priority>=2).
Touch and explicit voice interactions remain available. Effective speech interval is
`max(STACKCHAN_SPEECH_COOLDOWN_S, minimum_speech_interval_s)`; the existing explicit
VOICE_REQUEST exemption remains. Live engines refresh preferences after model latency.
Quiet output preference does not disable observation or change cloud consent settings.

`STACKCHAN_MEMORY_RETENTION_S` defaults to604800 (7days), allowed60..31536000.
History and speech/observation metadata expire on access for that resource, not through
a background deletion service. Preferences persist until cleared. Count/retention
cleanup and updates commit atomically. Expiration is not undone by clock rollback;
a clock jump far forward can expire data early and delay availability after rollback.
Configured retention must cover the configured speech cooldown and stored preference
interval. Invalid combinations stop with a fixed error rather than silently shorten
the interval. Raise retention to edit a preference that exceeds a newly lowered limit.

Legacy `history(id,at,event,intent,result)` files migrate atomically to version1.
Unscoped legacy records belong only to `stackchan:default`, never an arbitrary selected
robot. Migration retains at most history_size recent records; normal retention then
applies. Preserve a backup before an operator migrates an important existing file.
Unknown/future versions and malformed retained metadata are rejected without reset.
Existing live instances also reject a schema changed by another process.

Each persistent operation opens a short SQLite transaction; other processes' commits
are visible on the next read. Participation requires matching resource/path/settings
and a local filesystem with SQLite locks. Separate resources keep independent memory.
`clear` affects only this component/resource, leaving other resources, leases and API
reservations intact. It also resets quiet/interval preferences and speech timestamps,
so a later background greeting can occur. Stop the engine first for a quiescent reset;
subsequent new interactions can populate memory again. Logical deletion does not erase
backups or guarantee removal of historical bytes from SQLite/free filesystem pages.

DB failure during an enabled engine cycle latches ERROR/stop_event, cancels local work
and prevents replay. An action may already have executed if the final metadata write
fails; the CLI exits2. No atomic transaction covers a robot side effect and SQLite:
a crash between dispatch and commit may lose completion metadata. Restart is a manual
recovery, not an exactly-once delivery guarantee. No hardware validation is claimed.

Tests exercise actual SQLite, process restart, migration rollback, typed privacy,
retention/clock rollback, cross-process visibility, pre/post-action failure and CLI.
CI additionally installs the wheel independently and exercises its console entry points,
persisted preference gating and restart cooldown on Windows/Linux, Python3.11/3.12.
