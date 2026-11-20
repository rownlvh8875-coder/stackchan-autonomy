# Native Wake Voice Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Native implementation continues under the user's selected direction and explicit next-step instruction.

**Goal:** 기성 모델의16k wake stream/event를 기존 bounded24k 질문/STT/GPT/TTS 흐름에 연결하고 실제 SDK와 링크한다.
**Architecture:** 공통 VoiceDialogEntry + 기존 WakeVoiceEntry wrapper, fixed-memory FIR/NativeWakeController, dormant K151WakeNetPort. 기존 startup HOLD와 cloud off 기본값 유지.
**Tech Stack:** C++20/Python pytest, ESP-IDF6.1/ESP-SR2.4.7.
**Spec:** docs/superpowers/specs/2026-11-20-native-wake-voice-bridge-design.md

## Global Constraints

기존 조수/SWK1/PC tools 및 공개 fixture 보존. 새 raw 음성/개인 특징/키 저장·업로드 없음. 실제 device/mic/API/network/flash/NVS/OTA/모터 실행 없음. samebranch 일반 push/PR3, main/환경 게시 없음. model assets 준비를 임의로 true로 시작하지 않으며 app_main은 HOLD marker만 추가한다.

## Review Focus

- 중단·gaps·잘못된 모양 뒤 남은 음성이 다음 호출로 이어지거나 중복 epoch가 나오지 않음.
- read/detect/reset/close 중 STOP·동의·재생 변경에 paid call/ready 승격이 발생하지 않음.
- FIR 경계/alias/DC/출력 수/포화에서 실제 frame 모양과 개인정보 소거가 유지됨.
- 정상 wake의 mic 소유권을 닫은 뒤 질문/예산/동의/cloud gate를 공유하며 기존 SWK1 API 호환.
- 잘못된 SDK model/list/function/format/detect 반환과 부분 준비 실패에서 누수·double free·암묵 재시작 없음.

### Task1: core stream and common dialog

Files create core/stream_resampler.hpp, core/voice_dialog_entry.hpp, core/native_wake_controller.hpp, core/native_wake_port.hpp; modify core/wake_voice_entry.hpp, core/voice_turn_coordinator.hpp, core/standalone_core.hpp, core/persistent_store.hpp, core/offline_voice_cycle.hpp. Tests tests/stream_resampler_test.cpp, tests/native_wake_controller_test.cpp, tests/builtin_admission_test.cpp, tests/test_native_wake_build.py (all firmware/standalone).
Interfaces StreamingPcm24To16::process(span<constint16_t>240,span<int16_t>160)->bool/reset(); NativeWakePort{ready(),format(),detect(span<int16_t>),reset()}; NativeWakeController::begin(now)->bool, poll(now)->NativeWakeEvent{step,optional epoch},cancel(). VoiceDialogEntry original question/answer methods and confirmed_wake; legacy signatures retained.

- [x] Write tests: DC/output counts/batch reference/10k alias<0.018of1k/reset/invalid/clipping; actual Native controller chunk480/512/2048, fake wake→actual question/coordinator→3Mock APIs and guarded playback/cooldown; no SWK1 profile provision. Cases STOP/consent/busy during read/detect, bad format/revoke/change, model/IO/close failure, gaps/time rollback, cloud off/no profile and inactive destruction.
- [x] Run uv run --frozen pytest -q firmware/standalone/tests/test_native_wake_build.py. Expected initial FAIL for missing implementation; record compiler messages then implement minimum and rerun PASS. Existing voice/Session regressions must PASS.
- [x] Verify and commit core+tests/spec/plan with task verification result.

### Task2: real SDK binding

Files create esp_app/main/k151_wakenet_port.hpp/.cpp, host tests k151_wakenet_port_test.cpp + publicSDK headers under tests/sdk_esp_sr_2_4_7 with license + tests/test_k151_wakenet_port_build.py; modify esp_app/main/{CMakeLists.txt,idf_component.yml,app_main.cpp}. No partition/sdkconfig change.
Interface concrete NativeWakePort; prepare(bool owner,bool assets_verified), close(), compiled_link_marker(); pins native component2.4.7; no SDK initialization from marker.

- [x] RED real policy against full SDK C ABI doubles: false gates zeroSDKcalls, missing/multiple/wrongmodel/nullinterface/function/create, invalidrate/channel/chunk/wordnum; validbuffer0/-1/1/other; cleanup data/list once in correct order; failed prepare/repeatedprepare/closed lifecycle refused. Actual SDK compile verifies ABI and linkage.
- [x] Implement after RED; rerun new/legacy host tests then entire Python/standalone+NumPy suites, Ruff/diff, actual pinnedIDF S3 build+symbol/size proof. Expected0fail; platform SKIP explicit; no model inference/hardware/API.
- [x] Docs/WORK_LOG/TEST_REPORT/NEXT_STEPS describe exact implementation and remaining bootstrap/assets/physical limitations; preserve prior Windows check_timeout failure and its one rerun result.
- [ ] Single fresh whole-change review; Important/Critical one RED→GREEN pass, Minor ledger/final. Commit/push/PR3; exact head Linux/Windows/ESP CI directly verify and record in PR. Preserve worktree.

Task1 scope correction: 기존 PersistentGuard도 profile을 요구한다. 검증된 로컬 builtin hit의 RAM epoch admission을 추가하며 duplicate/mismatch/cancel/reboot/fatal/default-closed tests RED→GREEN으로 검사한다. 기존3인자 reserve 회계 동작과 SWK1 권한은 보존한다.
