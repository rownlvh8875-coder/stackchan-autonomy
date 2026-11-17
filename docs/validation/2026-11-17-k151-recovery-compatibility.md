# K151 recovery and official-app compatibility review

Checked2026-11-17 UTC. Documentation/research only. The user reports USB connected
but is away from the Windows laptop; no PnP output, security/flash query, readback,
backup file, reboot, erase, write, capture or paid API operation was performed.

## Current disposition

| Area | Public evidence | Actual unit / decision |
|---|---|---|
| Stock firmware + official app + PC GPT speech | Existing user live confirmation | Retain this working path |
| Public custom build + official M5Stack/World auth | Contributor confirms production auth absent, no SDKCONFIG switch or published component | BLOCKED for preserving requested integrations; not just a build-test gap |
| Xiaozhi AI.Agent in custom builds | Contributor says it uses a separate connection and can work independently | Does not prove this unit's complete official app/PC GPT setup survives replacement |
| LCD revision handling | Pinned board code detects FT6336 firm_id0x12/vendor0x11 and applies ILI9342E init; fallback9342C | Code paths present; actual unit revision/detection unverified |
| USB transport | Official manual: both USB-C ports support data; base recommended. CoreS3 schematic USB nets connect ESP GPIO19/20 | Native USB hardware path documented; actual COM/VID/PID/driver/runtime and reset behavior unverified |
| Original flash backup | Pinned esptool ROM read/check procedure prepared | NOT RUN; no file/hash/pass claimed |
| Recovery | Same-device original whole-flash candidate + official M5Burner procedure documented | NOT RUN; no recovery success or calibration/account completeness claimed |
| Observer firmware | Previously compiled with pinned IDF, host/SDK/MCP tests | Installation HOLD remains; build PASS does not resolve production auth |

## Sources

1. [Official product manual](https://docs.m5stack.com/en/StackChan), sections Download
   Mode, Restore Factory Firmware, XiaoZhi Pairing and Unpairing, Version Change.
   RST hold3s is download entry; RST single click is reboot. Both data ports/base
   recommendation, and ILI9342C→E revision/M5GFX notice were confirmed on the live page.
   Unbind/reset removes agent settings/history; not a prerequisite for this backup.
2. [Official repository issue134 contributor response](https://github.com/m5stack/StackChan/issues/134#issuecomment-6812198686),
   Forairaaaaa, contributor,2026-11-12. Key statements:
   “The production implementation used by the official firmware is not included in
   this repository. There is no additional SDKCONFIG setting that enables it for a
   custom build.” Also no published authentication component/setup procedure for
   retaining those official integrations. This is a public contributor statement,
   not a test of the user's unit or a promise of future vendor support.
3. Official main rechecked using `git ls-remote`: unchanged
   `28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400`.
   [LCD detection/init](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc#L607),
   [weak auth placeholders](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/utils/secret_logic/secret_logic.cpp),
   [NVS initialization](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/hal.cpp#L24).
4. Schematics linked directly by the official product page:
   [CoreS3](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/490/Sch_M5_CoreS3_v1.0.pdf),
   [adapter](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/1205/SCH_Adapter.pdf).
   Parsed PDFs show USB_DU_N/P nets on GPIO19/20; adapter carries USB_DM/DP.
   A schematic is not proof of the observed laptop's peripheral/driver selection.
5. Espressif [basic commands](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/basic-commands.html#read-flash-contents-read-flash)
   and [reset/no-stub options](https://docs.espressif.com/projects/esptool/en/latest/esp32s3/esptool/advanced-options.html).
   Actual installed esptool5.6.0 help/source checked. ROM reads use64-byte blocks and
   can be slow; ROM read may need explicit `--flash-size`. No speed promise or stub
   upload fallback is hidden in the procedure. Port opening may still have USB effects.

Downloaded resource SHA256 values identify the reviewed bytes, not vendor signatures:

| Resource | SHA256 |
|---|---|
| Live manual HTML | a833f80844fbe317f8422b911333dfa9bc4eea49b3bd41dc1ba292874755de3c |
| CoreS3 PDF | 58a15454eccb11d2668e1a9a3ad85943b9a58b104c5f1ed137b790192ec27c04 |
| Adapter PDF | 8d0b419244dd0ef18ca371742a5f63b5ab9b55712cd97d6a459fad7b27e7dbbb |

No issue/comment/support message was posted. No credentials, NVS values or firmware
keys were extracted; no runtime code/configuration or dependency lock was changed.
The prepared Windows commands remain unexecuted on the user's laptop. Offline esptool
version/help and non-invoking argument parsing passed for get-security-info, flash-id
and read-flash (including address0,16777216-byte size and explicit16MB option). No serial
loader or command callback was invoked; no output backup file was created. Local links
and Markdown fences checked52 references, and Git whitespace validation passed.
These documentation checks do not establish Windows/device/backup/restore success.
