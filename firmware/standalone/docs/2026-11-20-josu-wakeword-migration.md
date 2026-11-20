# 2026-11-20 호출어 변경: “조수야” → “조수”

## 구현 범위

1. tools/synthesize_korean_wake_sapi.py는 신규 기본 호출어를 **“조수”**로 사용한다. --wake-phrase 조수야는 기존 학습 재현 실험 전용 명시 옵션으로 남겨 두었다. 새 호출어의 음향 프로필은 반드시 **별도로 생성**해야 한다.
2. 비호출어 보정/평가에 **“조수야”**를 포함해, “조수야”가 이전 호출어였다는 이유로 허용하지 않는다. 한국어 2음절 “조수”는 MFCC/DTW에서 어휘 문자열 비교가 아니라 소리 패턴 비교이므로, 문자열만 바꾸면 동작하지 않는다.
3. **PC 연구용** Vosk/Whisper 2차 인식기는 정확히 “조수”인 전사만 허용하도록 기본값을 변경했다. 호환성 검증에는 --wake-phrase 조수야를 명시할 수 있다. 두 2차 인식기는 K151 firmware 내부에서 동작하지 않는다.
4. 실제 오프라인 매처 core/wake_voice_entry.hpp는 등록된 WakeProfile을 받아 비교한다. 현재 **기기 등록·실물 마이크·상시 감지·GPT 대화**를 새 프로필로 실행한 것은 아니다.

## 오프라인 합성 음성 검증

- Windows에 설치된 **Microsoft Heami Desktop(ko-KR)** 합성 음성만 사용.
- 생성: 24 kHz, mono, PCM16 WAV 24개.
- 보정 입력: 호출어 등록 1, 호출어 보정 5, 비호출어 보정 10.
- 평가 입력: **새로운 TTS 속도**의 호출어 2, 비호출어 6. 비호출어 중 하나가 “조수야”.
- wake_corpus_audit.py: 구조 검사 **CORPUS_STRUCTURALLY_SCREENED**, 품질 사전 경고 없음.
- wake_corpus_pipeline.py --offline-zig: 새 SWK1 생성 완료, 오프라인 평가 **호출어 2/2 수락 · 비호출어 0/6 수락**.
- 위 수치는 통계적 의미의 인식률이 아니며, 동일한 합성 엔진의 음성이라 평가 독립성이 제한된다. 외부 음성/클라우드/API/하드웨어를 사용하지 않았음.

검증 자료는 fixtures/korean_josu_sapi_20261120/에 **기존 “조수야” 원본과 별도로** 보존한다. 코드 변경 이후에도 app_main.cpp의 제조사 AI·서보 미초기화 및 물리 입출력 HOLD는 그대로 유지한다.

## 설치 전 남은 확인

**실제 사용자 목소리로 새 “조수”를 반복 녹음**하고, “조수야”, “조수님”, “조수석”, “주스”, 주변 대화/TV 소리 등의 오탐을 측정한다. 거리(예: 1m), 마이크 이득, 잔향/소음, 로봇 스피커 출력 중 재호출 금지, False Wakes/Hour, 마이크 전원·메모리, STOP 지연, 공장 펌웨어 백업/복구 가능 여부가 확인되기 전에는 장치에 기록하거나 HOLD를 해제하지 않는다. 기존 README에 지정된 1m 20회 중 18회 이상, 일반 음성 60분 내 오탐 1회 이하, 로봇 재생 20회 중 오탐 0회는 **목표**이지 달성 결과가 아니다.

## PC 재현 명령 (검증용, 기기에는 연결하지 않음)

    uv run --frozen python firmware/standalone/tools/synthesize_korean_wake_sapi.py --wake-phrase 조수 --output C:\private\josu-new-corpus
    uv run --frozen python firmware/standalone/tools/wake_corpus_audit.py C:\private\josu-new-corpus\synthetic-sapi.wake-corpus.json
    uv run --frozen python firmware/standalone/tools/wake_corpus_pipeline.py C:\private\josu-new-corpus\synthetic-sapi.wake-corpus.json --output C:\private\josu-new-corpus\new-josu.swk1 --offline-zig

출력 폴더와 프로필 파일은 새 경로여야 한다. 여기서 명령을 재현하더라도 실기기 자동 설치는 수행하지 않는다.
