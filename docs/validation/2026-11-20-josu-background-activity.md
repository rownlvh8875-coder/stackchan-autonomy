# 무발화 배경 활동으로 인한 등록 경계 거부 수정

2026-11-20 / Asia/Seoul / 기준 f3f9fdc / PR#3 `feat/wakeword-josu`.

## 현장 근거와 원인 구분

사용자는3초 무발화 시험에서도 간헐적 에너지와 녹음 끝 활동을 보고했다. 호출어 매칭은 계속 거부됐다. 실제 PCM/음향 특징을 받거나 저장/업로드하지 않았다. 배경음의 정체, 마이크/OS 처리 또는 실제 발음 내용은 확인하지 못했다. 앞선 말하기 타이밍/입력 설정 안내와 녹음 길이 증가는 이 현상을 해소하지 못했다. 사용자가 같은 등록을 반복하기 전에 구간 정책을 검토했다.

코드는 고정 하한/추정 배경을 넘는 **모든** 구간의 첫/끝을 연결했고, 말하지 않은 평가에도 발화의 경계 gate를 적용했다. 이 두 조건은 재현 가능한 소프트웨어 문제다. 에너지 활동을 실제 한국어 발화라고 해석하지 않는다.

## 변경

- 기본 energy gate를 낮추지 않고 최대20ms RMS의10%를 추가한 주활동 기준으로 구간을 선택한다. 기존 public experimental trim의 relative-peak 원칙을 참고했다. 약한 별도 활동 수/원본 경계 여부와 base/주활동 문턱을 진단한다.
- 400ms context 보존. 강한 활동 또는 선택 context 안의 약한 활동이 실제 녹음 경계에 닿으면 계속 거부한다. PCM한계/클리핑 및 모든 발화 품질 gate 유지.
- 독립 quiet평가에서는 edge/clipping 같은 음향 경고가 있어도 실제 C++ 매처로 오탐을 평가한다. 경고 구간 수 집계, falsewake는 모델 미저장/FAIL. 동일 특징을 이유로 falsewake를 숨기지 않는다. 원본/WAV 중복과 IO/형식 오류는 계속 거부한다.
- default3초 및 `NOTEBOOK_MIC_RECORDING_FINISHED` 표시. 현재 녹음 종료 시점을 명확히 한다. 원본/중간 특징/해시는 메모리 전용, 기존 SWK1/DTW/calibrator/파일 저장 보호 변경 없음.
- 새 의존성/모델·장치·API·실물 firmware/OTA/NVS/모터 동작 없음. core/esp_app과 기존 합성 fixture를 변경하지 않는다.

## 확인한 시험

합성 stronginterior+weakseparatetail 및 실제 C++ 매처 quiet검사에서 먼저3FAIL1PASS를 관측했다. 수정 후 PC검사 **78PASS3Windows-onlySKIP**. quiet 정상 무활동은 경고로 세지 않으며, clipped/edge 배경이 잘못 호출되면 FAIL, malformed WAV는 정상 음성 거부로 집계하지 않는다. 기존 Heami “조수”2/2 수락·비호출0/6 수락, 녹음 경계 위험·개인 capture digest·독립 평가·취소·경로 교체/배타 게시도 회귀 범위다.

전체 Python487PASS2Windows-onlySKIP 및 독립 wheel/Mock MCP·GPT/Opus 검증 PASS. Ruff check/format315files PASS. 전체 standalone 재검사와 단일 독립 검토 뒤 수정도 아래와 같이 검증했다. 정확한 새 head CI는 PR#3의 검증 기록과 Checks에서 확인한다. 원본 음성이 없으므로 합성 신호로 수정 구조를 검증한 것이며 실제 사용자의 문제가 해결됐다고 판정하지 않는다.

## 현장 다음 단계

[작업 순서](../../firmware/standalone/docs/2026-11-20-josu-human-mic.md)대로 최신 코드로1회 진단해 새 구간 지표를 확인한다. 실제 주활동이 여전히 녹음 끝에 닿으면 계속 거부해야 한다. 품질이 통과한 경우에만 새 발화 등록·보정·독립 평가를 진행한다. 실제 노트북 인식/거리/소음/상시 오탐과 K151 적용은 미검증이다. 기존 개인 프로필이 있다면 전처리 변경 뒤 새 자료로 재검증하고 덮어쓰지 않는다.

## 구현 판단

relative-peak10%는 고정된 보수적 에너지 구간 선택이며 음성 모델이 아니다. 약한 별도 발화/비슷한 크기의 배경을 의미적으로 구분하지 못하므로 현장 검증이 필요하다. quiet경고를 점수화하는 것은 평가를 쉽게 통과시키는 예외가 아니라 실제 falsewake를 누락하지 않기 위한 것이며 실패를 그대로 기록한다.

유효한 PCM이지만 특징 추출의 최소 에너지 조건을 충족하지 못한 경우도 분류기의 정상 비호출이다. C++ private score가 `accepted=false,distance_q8=null`을 반환하도록 명확히 구분했다. 잘못된 WAV/프로필/프로세스·프로토콜 오류는 계속 실패하며, 이들을 정상 비호출로 세지 않는다. 기존 default/feature/calibration 모드의 거부 규칙과 MFCC/DTW/수락 한계는 유지한다. 진단 모드는 같은 score 결과를 한번 사용하며 거리가 없으면 margin도 null이다. 이 구분도 먼저 FAIL을 확인하고 실제 C++/Python 통합으로 검증했다.

## 독립 검토 뒤 회귀 수정

별도 fresh reviewer가 ce46f24의3개 Important를 제시했다. 모두 수락하고 먼저4개 FAIL(양끝 연속 약한 영역2개 포함)을 재현한 뒤 수정했다. 두 번째 검토를 요청하지 않는다.

- 주활동 뒤600ms 연속 약한 끝음/앞부분을 잘라서 품질 통과시키는 문제: 인접한 낮은 기준 초과 블록을 양쪽으로 끝까지 확장한다. 실제 경계에 닿으면 계속 거부한다. 분리된 약한 tail 회귀도 유지한다.
- 진단 옵션 유무가 유효한 무특징 PCM의 판정을 바꾸는 문제: Python CLI는 동일한 score 경로를 사용하고 옵션은 출력 필드만 바꾼다. 독립 C++ legacy CLI의 기존 계약은 보존한다.
- 발화 평가에서832byte 특징 추출 성공 뒤 같은 입력에 null-distance 응답이 오면 정상 거부로 셀 수 있는 문제: 일관성 오류로 실패시킨다. 무발화의 실제 특징 미생성 null과 구분하고, 실제 C++ 점수 뒤 fault injection으로 시험했다.

수정 후 PC78PASS3Windows-onlySKIP. 추가 Minor는 없었고 기존 EOF/수동 terminal binary 항목은 변경하지 않았다. 실제 음절/사용자 라벨/마이크 처리/기존 개인 프로필 성능은 합성 입력으로 판단할 수 없어 현장 미검증으로 유지한다. nativeWindows CI는 실제 장치 검증과 구분해 확인한다.

## 최종 로컬 검증

- root Python: **487PASS2Windows-onlySKIP**, 68.02초.
- standalone C++/Python: **284PASS7SKIP**, 126.64초. 건너뛴 항목은 Windows CMD3, Windows SAPI2, 로컬 libcjson-dev 부재2다.
- PC 진단·등록 대상: **78PASS3Windows-onlySKIP**, 9.07초.
- Ruff check/format315files, git diff check PASS. 독립 wheel/sdist 설치 및 Mock MCP/GPT/Opus 검사도 PASS. 실제 기기/네트워크 API를 호출한 시험이 아니다.
- 단일 fresh reviewer의 Important3건을 모두 수락하고4개 실패 회귀를 먼저 확인한 뒤 수정했다. 새 Minor는 없으며 추가 검토를 반복하지 않는다.
- 새 head의 Windows/Linux/ESP compile-only 최종 결과와 커밋 SHA는 [기존 PR#3](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)에 기록한다. [Checks](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3/checks)의 head가 해당 커밋인지 함께 확인한다. 문서 안의 로컬 PASS를 원격 CI나 실제 사용자 인식 성공으로 해석하지 않는다.

실물 설치·API·환경 게시·main 병합은 수행하지 않는다. 장치용 core/esp_app 코드는 기준 f3f9fdc와 동일하다.
