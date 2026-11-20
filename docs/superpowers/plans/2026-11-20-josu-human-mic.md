# 조수 PC 마이크 진단·등록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans; native execution continues under the user's explicit implementation request.

**Goal:** 실패 이유를 관측하고 실제 사용자 목소리로 개인 SWK1을 만들고 별도 평가한다.
**Architecture:** 기존 C++ MFCC/DTW를 pipe 기반 helper로 재사용하고 Python의 동일한 전처리/녹음을 진단과 등록에 공유한다.
**Tech Stack:** Python 3.11+, NumPy, sounddevice 0.5.3, C++20, Linux/Windows CI.
**Spec:** docs/superpowers/specs/2026-11-20-josu-human-mic-design.md

## Global Constraints

기본 호출어 “조수”; 개인 PCM/특징 Git 업로드·음성 파일 저장 없음; 오프라인 명시적 녹음만; 실제 API/로봇/flash/NVS/OTA/모터 제외; e8ee330 기존 합격 보존. 개인 프로필은 명시적 새 `.local/` 파일만 저장. 제조사 문의 없음.

## Review Focus

- 재부팅/장치 목록 변경 시 다른 마이크로 조용히 녹음하지 않아야 한다.
- 녹음 경계의 활동·클리핑·부족한 SNR을 진단하고 등록을 거부한다.
- stdout에 원본/특징/개인 경로가 섞이거나 oversized/truncated helper 입력을 허용하지 않는다.
- 독립 평가를 보정에 재사용하거나 같은 녹음을 독립 표본으로 계산하지 않는다.
- 개인 프로필을 기존 파일/추적 경로에 덮어쓰거나 Windows 실행 오류로 무인 녹음하지 않는다.

### Task 1: 입력·구간 진단

Files: `tools/pc_mic_wake_probe.py`, new `tools/pc_mic_audio.py`, `tests/test_pc_mic_audio.py`.
Interface: `analyze_48k(samples,np) -> (trimmed_or_none, diagnostic_dict)`, legacy trim API 유지. 입력 길이/타입, 48→24k 길이/주파수, RMS/peak/clip, VAD 경계와 위험을 검사한다.
- [x] RED: 무음·클리핑·capture 양끝 활동·FIR alias/길이·장치 변경 시험.
- [x] 구현 후 기존 PC fixture 회귀를 포함해 GREEN 확인.
- [x] 진단 결과와 원인 미확정 제한을 문서화/커밋.

### Task 2: 실제 C++ 점수·메모리 보정

Files: `tools/wake_stage1_probe.cpp`, `tests/test_pc_mic_wake_probe.py`.
Interfaces: `--features -` -> 832 feature bytes; `--calibrate -` -> 3+5+10 feature 입력의 SWK1; `--score -` -> profile length16be + profile + WAV 입력의 sanitized JSON.
- [x] RED: 기존 판정·SWK1 호환, 실제 거리/임계값, malformed/초과/중복 데이터 거부.
- [x] 기존 핵심 함수 호출로 구현 후 GREEN/커밋. 임계값 임의 변경 없음.

### Task 3: 사용자 등록·평가 CLI 및 Windows 실행

Files: new `tools/pc_mic_enroll.py`, existing probe/runner, new enrollment runner/tests.
Interfaces: 명시 장치 선택·기대 identity, 3/5/10 고정 보정 후 5/10 새 평가; 모든 녹음은 Task 1 전처리, 점수는 Task 2. 개인 profile는 새 `.local/` 경로로만 exclusive 생성.
- [x] RED: 품질 거부·중복·평가 누출·실패 시 미저장·취소·민감 출력·경로 보호 테스트.
- [x] 구현 후 오프라인 합성 입력으로 전체 등록→프로필→점수 경로 GREEN/커밋.
- [x] 장치 목록/선택과 수동 실행 설명 제공. 실제 발화 결과는 미검증 유지.

### Task 4: 통합 검증과 PR #3

- [x] Ruff check/format, 전체 Python, C++20 standalone, PC NumPy, wheel 검증.
- [x] CI에 Linux/Windows PC tests 추가; 기존 ESP32-S3 compile-only 유지.
- [x] 작업/검증 문서에 실제 결과·미검증·설치 HOLD·사용자 다음 명령 기록.
- [x] 단일 fresh whole-branch review; Important/Critical만 회귀 RED→GREEN 한 번 수정.
- [x] `feat/wakeword-josu`에 커밋/일반 push, PR #3 내용 갱신.

최종 완료 판정은 [PR #3 현재 head의 CI](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3/checks)를 직접 확인한 뒤 내린다. Windows 경로 교체/정상 게시 회귀를 건너뛰지 않는다. 상세 실행 결과는 PR 설명과 검증 문서의 이력을 구분한다.
