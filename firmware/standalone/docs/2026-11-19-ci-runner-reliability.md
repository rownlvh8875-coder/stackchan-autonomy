# GitHub Actions Linux runner network reliability change (2026-11-19)

At commit `ff6cae8`, GitHub Actions run `44522022647` failed on `ubuntu-latest / Python 3.11` before Python tests or C++ compilation, during OS dependency installation. The runner resolved `ubuntu-latest` to Ubuntu 26.04 and `apt` could not fetch `libopus0` / `libcjson-dev` from Ubuntu mirrors, reporting connection timeout and temporarily unavailable network resources. This is evidence of a package retrieval failure, **not an audio integration test failure**.

The CI workflow now selects `ubuntu-24.04` explicitly instead of a moving `ubuntu-latest` label. Apt update/install requests allow `Acquire::Retries=3` to recover from transient download failures. Python 3.11/3.12 and Windows jobs are preserved, and the offline C++ tests, full pytest suite, virtual 24-hour stability simulation, wheel checks, and release HOLD stay unchanged.

This is a deterministic runner baseline and a bounded retry policy, **not proof** that every future network call will succeed. The earlier Windows lease `renew_timeout` during an overloaded accelerated soak must still be evaluated independently; changing a safety lease threshold or masking that failure is not part of this change.

Source: [failed Ubuntu 3.11 run](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44522022647); future rerun status must be checked before claiming CI is green.
