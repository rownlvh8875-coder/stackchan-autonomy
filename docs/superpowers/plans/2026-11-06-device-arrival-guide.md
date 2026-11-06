# Device Arrival Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 제품 도착부터 실물 장시간 검증까지 실행 가능한 한국어 작업설명서를 GitHub에 제공한다.

**Architecture:** 공식 제품 매뉴얼을 출고 절차의 근거로, 현재 소스를 연동 가능 범위의 근거로
사용한다. 상세 설명서와 빈 기록 양식을 분리하고 기존 진입 문서에서 연결한다.

**Tech Stack:** Markdown, Mermaid, Windows PowerShell, 현재 Python CLI.

**Spec:** [제품 도착 후 설명서 설계](../specs/2026-11-06-device-arrival-guide.md)

## Global Constraints

- 문서만 변경한다. 실물·펌웨어·유료 API·환경 게시를 실행하지 않는다.
- 물리 실행 차단과 개인정보/좌표/복구 조건은 설계 문서의 제약을 따른다.
- GitHub 업로드는 사용자가 승인했다. 기존 브랜치에 일반 push하고 새 PR/병합은 하지 않는다.

## Review Focus

- 다른 SKU/컨트롤러/LCD: 호환성이 확인되지 않으면 플래시를 중단한다.
- 첫 부팅: 제조사 자동 서보 시험 전에 주변·케이블·전원 차단을 준비한다.
- 출고 앱과 커스텀 gateway: 같은 MCP 계약으로 취급하지 않는다.
- PC 종료/절전/중단: Mock 24시간의 완료와 연속성을 오판하지 않는다.
- 물리 차단/매체 보관: 현재 실행 불가 단계와 gateway 잔존 파일을 명시한다.

### Task 1: 설명서와 기록 양식

**Files:** 새 `docs/DEVICE_ARRIVAL_RUNBOOK.ko.md`,
`docs/templates/DEVICE_ACCEPTANCE_RECORD.ko.md`; README, HARDWARE_BRINGUP, NEXT_STEPS의 안내 링크.

**Interfaces:** 공식 문서/소스 → 단계별 작업·통과 기준·보류 조건 → 로컬 기록 양식.

- [x] 공식 제품, M5Burner, uv 안내를 읽고 접근일/사실을 기록한다.
- [x] D00–D10 흐름도와 단계별 설명, 장애 대응, T1–T10 표를 작성한다.
- [x] 미실행 상태의 기록 양식과 진입 링크를 추가한다.
- [x] 로컬 링크/앵커, Mermaid, Python 예시 구문/호출, CLI 옵션, diff를 확인한다.
  Expected: 잘못된 링크/옵션/쓰기 호출 없음, `git diff --check` 성공.
- [x] 새 맥락의 읽기 전용 리뷰로 사실·실행 가능성·보류 조건을 확인하고 필요한 수정을 한다.
- [ ] 문서만 커밋하고 현재 `feat/transport-soak`에 일반 push한다.
  Expected: 원격 커밋과 로컬 HEAD 일치, 공개 문서 URL에서 새 내용 확인.

문서 변경에는 구현을 복제하는 테스트를 추가하지 않는다. CLI smoke는 장치 없는 Mock만
사용하고 장치 연결 예시는 구문/소스 대조만 한다. GitHub의 기존 CI는 별도 자동 실행이다.
