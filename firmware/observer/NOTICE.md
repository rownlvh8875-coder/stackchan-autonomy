# Provenance and distribution

The observer core, adapter and host tests in this directory are original project
code under the adjacent MIT license. The integration patch modifies the official
M5Stack StackChan firmware (MIT, copyright2026 M5Stack Technology CO LTD), exact
SHA28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400. Its original license remains in
the prepared upstream checkout. Upstream code is not vendored here.

`dependencies.json` pins every Git source; upstream `firmware/dependencies.lock`
pins the managed components. Dependencies retain their own licenses, including
licenses with distribution obligations. This change distributes our source/patch
and build checksums, not an upstream/dependency binary release. Any future firmware
release needs the corresponding source and dependency license review.

The separate custom-firmware StackChan MCP projects are not copied into this observer.
This prototype neither supplies production service keys nor preserves their behavior
by assumption. A compiled image is **not approved for device installation**.
