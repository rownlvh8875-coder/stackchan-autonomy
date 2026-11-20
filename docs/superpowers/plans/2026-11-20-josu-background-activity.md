# 조수 배경 활동 경계 거부 수정 계획

> Native execution with superpowers:executing-plans; this is a correction within the authorized PC microphone diagnosis/enrollment work, not device installation.

**Goal:** 분리된 약한 끝 잡음 때문에 주된 활동이 녹음 경계까지 확장되는 경우를 줄이고 무발화 잡음을 실제 오탐 평가에 포함한다.
**Spec:** `docs/superpowers/specs/2026-11-20-josu-human-mic-design.md`의 입력 품질·독립 평가·개인정보·설치 HOLD 제약을 유지한다.

## 근거와 제한

사용자가 말하지 않은3초 대조 시험에서 간헐적 에너지와 끝 활동이 검출됐지만 호출어 매칭은 거부됐다. 실제 PCM을 받지 않았고 물리적인 배경음/장치 처리 원인은 미확정이다. 원본·개인 특징은 공개하지 않으며 사용자 진단 수치로 임계값을 맞추지 않는다. 음성 입력과 무발화 입력의 크기 차이는 보조 단서다.

가설1: `max(0.002,3*floor)`를 넘는 모든 활동의 first/last를 묶어서 멀리 떨어진 약한 tail도 등록 경계 오류를 만든다. 기존 experimental energy trim의 relative-peak 원칙을 PC의 동일 전처리에 적용한다: 주활동 threshold=`max(base,0.10*peak_block_rms)`. 400ms context/원본 clipping/PCM bounds 유지. 선택 context가 실제 녹음 끝에 닿는 경우 그 안의 약한 base 활동도 여전히 경계 위험으로 거부한다. 상대적으로 약하지만 먼 별도 발화를 구분해 주는 음성 모델이 아니며 실제 사람 결과는 미검증이다.

가설2: quiet evaluation에 speech의 edge/clipping 품질 거부를 동일 적용하여, 실제 측정할 잡음/오탐을 평가하기 전에 세션을 중단한다. quiet의 알려진 음향 경고는 집계하고 classifier 결과 그대로3구간을 평가한다. IO/형식/모델·중복 오류는 계속 거부하며 raw digest 및 WAV 중복 검사 유지. quiet의 특징이 기존 템플릿과 같다면 duplicate feature로 숨기지 말고 false wake로 실패 처리한다. 훈련·보정·발화 평가의 품질 게이트와 동결된 SWK1은 유지한다.

대안: 녹음 길이 증가만으로는 무발화 tail 문제가 재현되어 해결되지 않았다. 새로운 speech VAD 의존성/모델은 지금 단계에서 도입하지 않는다. caller wake score를 완화하는 방식은 제외한다.

## Tasks / verification

- [x] RED→GREEN: stronginterior+weakseparatetail은 경계를 확장하지 않음, weakedge inside context와 실제 말 끝은 계속 거부. oldTTS2/2 및 nonwake0/6 유지.
- [x] RED→GREEN: quiet edge/clipping을 실제 C++ matcher로 평가, falsewake는 model미저장/FAIL, warnings 집계, duplicate/invalid/STOP/키보드 취소·원본 RAM 유지.
- [x] 기본3초 및 명시적 녹음 종료 표시로 현장 시간 확인. 출력만의 변경은 별도 미러 테스트를 만들지 않는다.
- [x] 새 진단 설명/실패 원인 미확정/기존 개인 profile은 전처리 변경으로 fresh registration 권장 기록. 원본·특징·해시 파일/업로드 없음.
- [ ] Ruff/전체 Python/standalone C++20/실제 host fixture/wheel 확인, 단일 fresh whole-branch review, Important/Critical만 RED→GREEN 단일 수정 패스.
- [ ] `feat/wakeword-josu` 일반 push / 기존 PR#3 갱신 / 정확한 head의 Linux·Windows·ESP compile-only CI 확인. 기기/API 접근과 main merge 없음.
