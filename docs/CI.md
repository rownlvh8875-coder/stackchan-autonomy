# Offline CI

GitHub Actions workflow: [CI](../.github/workflows/ci.yml).
Runs on push, pull request and manual dispatch, with four independent jobs:

| Runner | Python | Native differences |
|---|---|---|
| ubuntu-latest | 3.11 / 3.12 | System libopus required; fork regression runs |
| windows-latest | 3.11 / 3.12 | Fork regression skipped; Opus skipped if no trusted system DLL |

Each job uses uv 0.13.4, `uv sync --frozen`, Ruff lint/format, full pytest,
sdist/wheel build and an independent installed-wheel CLI smoke check.
Official actions are pinned to full commit SHAs, verified from their release tags.
The workflow token has `contents: read`; no application secrets are bound to jobs.
No real robot, microphone, speaker or paid API is used. SDK API tests use MockTransport.

`scripts/ci_verify.py` exports hashed runtime requirements from uv.lock, creates a new
temporary venv using the selected interpreter, installs those requirements with
`--require-hashes`, then installs the built wheel with `--no-deps`.
It verifies imports come from that venv and executes the installed console entry point
from outside the checkout, including a directory containing spaces.
Mock, MCP simulation and voice simulation must each return IDLE, one simulated action
and zero cloud requests. Voice must capture/play back once; available Opus must produce
packets. Linux requires the native codec rather than silently skipping it.
The helper removes application settings/keys and source-path overrides from child
environments; network proxy/CA trust configuration remains intact for package installation.

Only JUnit XML is uploaded (seven-day retention). Local state databases, caches, keys,
media, conversation content and built distributions are not uploaded as artifacts.
Missing optional native features appear as SKIP in pytest output/JUnit and smoke output.
SKIP does not mean the feature executed successfully.

Local reproduction, from the repository root (PowerShell or Bash):

```text
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pytest -q -ra --junitxml=.local/ci/junit.xml
uv build --no-sources --out-dir .local/ci/dist
uv run --frozen python scripts/ci_verify.py
```

On Linux with system libopus, add `--require-opus` to the last command.
Build into a directory containing exactly one project wheel; remove an older project
wheel manually if its version differs. The helper leaves the development venv untouched.

## Recorded validation — 2026-11-06

- Local Linux / Python 3.12.14: 194 PASS, 0 failures/errors/skips, 16.05s.
- Ruff lint/format and workflow YAML/matrix/permissions/SHA checks: PASS.
- Offline sdist/wheel build: PASS using cached verified build dependencies.
- Independent wheel: all four runs PASS, including native Opus (seven packets).
- Remote Windows/Linux matrix: pending publication and execution; local results do
  not establish that Windows or Python 3.11 has passed.

The restricted cloud shell denied a build dependency network connection. An offline
build using the existing cache passed; TLS/hash verification was retained.
Threaded SDK/voice checks ran using the environment's approved command execution.
GitHub repository and Actions run listing are readable. The Actions administration
permissions endpoint returns HTTP 403; CI does not require changing that setting.
