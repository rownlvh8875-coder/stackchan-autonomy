# Stock K151 observation API follow-up — 2026-11-18

Date uses Asia/Seoul. User explicitly selected **retain the official app and first
check the manufacturer-supported route** after the backup/stock-camera milestone.
This is a source/support review, not a new firmware implementation or hardware trial.

## Inputs retained

- [User evidence](2026-11-18-k151-usb-preflight.md): two full16MB files with matching
  SHA256, normal boot/app/GPT return, official Monitoring Camera display.
- Backups remain private on the user's laptop. No device credentials, image/video,
  original binary or firmware key was read by the cloud agent.
- The USB observer code/build already exists, but production-auth compatibility
  for installing it while retaining StackChan World remains HOLD.

## New source observations

Official main was rechecked and still resolves to
`28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400`.

| Source | Observed behavior | Implication |
|---|---|---|
| `app/lib/view/home/monitoring_camera.dart` | Holds the phone LAN service; subscribes to JPEG messages; sends onCamera/offCamera through the device transport | A working app preview does not expose a documented PC snapshot endpoint |
| `app/lib/network/device_message_transport.dart` | Uses phone LAN when connected, otherwise falls back to the remote channel | LAN and vendor-remote paths both need their actual configuration/auth contracts |
| `app/lib/network/web_socket_util.dart` | Encrypts a MAC/random/time authorization value through RsaUtil and connects to its configured URL | External MCP's URL/token is a different protocol; it is not this authorization |
| `app/lib/network/urls.dart` | Public URL is an `api.example.com` development placeholder | Production service configuration is not established by this public file |
| `app/lib/util/value_constant.dart` | SERVER_PUBLIC_KEY, CLIENT_PRIVATE_KEY and STACKCHAN_BLE_PRIVATE_KEY are build-time inputs with no supplied production values | Do not substitute arbitrary keys or infer that a public-source app build is the shipped app |
| `firmware/main/apps/app_avatar/app_avatar.cpp` | onClose clears Avatar handlers and calls requestWarmReboot(1) | Leaving Avatar is not a proven uninterrupted camera-plus-AI.Agent observation path |

These findings describe the pinned public source. They do not prove that every
possible vendor-supported API is absent, or that all deployed versions behave identically.
No active client, camera command, Bluetooth write, remote login or API request was tried.

## Support information checked

[Issue134](https://github.com/m5stack/StackChan/issues/134) still has the contributor's
2026-11-12 production-auth explanation and a later question about future SDK plans;
no newer answer was present in the returned two-comment list. Public issue searches
for `camera API` returned no results and `SDK` returned issue134 only. This is a
bounded public search, not proof that no private/documented support channel exists.

The contributor explicitly says no published custom-build authentication component
or setup procedure is available. That reply does not itself answer whether a
supported read-only PC interface exists on **stock** firmware.

## Disposition

Follow the user's official-app-retention choice. Prepare a narrowly scoped
[support inquiry](../M5STACK_OBSERVATION_API_REQUEST.ko.md) about stock JPEG/events,
authorized PC access and voice coexistence. **Draft only; not posted or sent.**
Do not install the current observer firmware, extract/replay production credentials,
disable authentication, or treat phone-screen pixels as a verified robot snapshot.
No product code, dependency lock or runtime configuration changed.

## Source links

- [Camera page](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/view/home/monitoring_camera.dart)
- [Device transport](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/network/device_message_transport.dart)
- [Remote connection](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/network/web_socket_util.dart)
- [URLs](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/network/urls.dart)
- [Build configuration](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/app/lib/util/value_constant.dart)
- [Avatar lifecycle](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/apps/app_avatar/app_avatar.cpp)
