# 조수 보정 거부 진단 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Existing explicit PC diagnosis implementation authorization and native execution continue.

**Goal:** 보정 분리/문턱 표현 범위 거부와 helper 실행·형식 오류를 구분한다.
**Architecture:** host --calibrate의 실패 진단만 추가하고 Python에서 검증해 CLI로 전달한다. 성공 wire, core calibrator, 인식/등록 기준 유지.
**Tech Stack:** Python3.11+, C++20, 기존 NumPy 합성 검사/Windows CI.
**Spec:** docs/superpowers/specs/2026-11-20-josu-calibration-diagnostics-design.md

## Global Constraints

원본/특징/프로필 콘솔 출력·새 음성 파일·업로드 없음. 새 의존성/실물/API/장치코드 변경 없음. 평가 재학습/threshold 완화/저장 보호 변경 없음. 기존 branch 일반 push/PR3 갱신, main merge/환경 게시 없음.

## Review Focus

- stderr 임의 텍스트/추가 key/NaN/음수/범위 밖 index/oversize를 콘솔에 노출하거나 원인으로 신뢰하지 않음.
- 잘못된 stdout/종료코드/다른 모드가 보정 진단으로 승격되지 않음.
- 거부 원인과 성공/품질 상태를 혼동하지 않으며 실패에서 평가/저장하지 않음.
- 동일 특징/잘못된 길이는 기존 일반 거부이며 성공 SWK1 byte는 그대로.
- 진단은 수집된 operator 라벨의 거리이지 실제 단어/원인 확정/실물 성능 증거가 아님.

### Task1: 보정 실패 진단 및 CLI 전달

Files: tools/wake_stage1_probe.cpp, tools/pc_mic_profile.py, tools/pc_mic_enroll.py, tests/test_pc_mic_wake_probe.py, tests/test_pc_mic_enroll.py (모두 firmware/standalone/ 하위).
Interfaces: 기존 --calibrate 성공 bytes 보존. 실패 stderr JSON 고정 reason/index/유한 q8 거리 -> CalibrationError(reason,diagnostics) -> PC_ENROLLMENT_REJECTED의 calibration 필드. 입력18*832byte 고정.

- [x] RED: 실제 C++ 비분리 feature(templates0/1/2,positive3..7,negative-1..-10)로 calibration_not_separable 및 최악 wake5/가장 가까운 nonwake1을 확인. sparse features로 threshold<1 거부를 구분. 기존 성공 bytes/invalid/duplicate 거부 유지.
- [x] RED: helper의 strict schema/모드/종료코드/stdout/길이 오류는 private 일반 거부. 실제 C++ 오류를 CLI에 전달해 평가·저장 없음 확인.
- [x] Run: uv run --frozen --with numpy==2.3.5 pytest -q firmware/standalone/tests/test_pc_mic_wake_probe.py firmware/standalone/tests/test_pc_mic_enroll.py; Expected: 새 진단 assertions FAIL, 기존 회귀 PASS.
- [x] 최소 구현 후 같은 명령 GREEN. 거부 조건/음향 모델은 변경하지 않음.
- [x] Ruff/전체 Python/standalone+NumPy 검증 및 docs 기록. Expected: 실패0; platform 의존 SKIP 구분.
- [ ] 단일 fresh whole-change reviewer, Important/Critical만 RED->GREEN 단일 수정 패스. 새 Minor는 ledger/final에 기록.
- [ ] 커밋/일반 push/기존PR3 갱신, 정확한 head의 Linux/Windows/ESP compile-only CI 검증. 원격 결과는 PR에 기록.
