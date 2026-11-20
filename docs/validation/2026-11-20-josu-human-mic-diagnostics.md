# “조수” 실제 사용자 마이크 실패 진단·등록 경로

2026-11-20 / Asia/Seoul. 기준 `feat/wakeword-josu` e8ee330 / PR #3. 새 프로젝트를 만들거나 이전 미완료 브랜치의 펌웨어 변경을 적용하지 않았다.

## 출발점과 판정 범위

사용자의 실제 실행 결과: `UNVERIFIED_NO_MATCH`, notebook mic9/48kHz/2.5초, 추출22,080프레임. 원본 음성은 받거나 저장하지 않았다. 활동 에너지와 프로필 거부만 관측됐으며 장치·발화·자음 잘림·개별 거리 데이터가 없어서 특정 원인을 확정할 수 없다. 길이0.92초만으로 잘림으로 간주하지 않는다.

기존 결과는 동일 Heami 합성 “조수”2/2 수락, 비호출0/6 수락(“조수야” 포함)이며 실제 사용자/K151 성능으로 확대하지 않는다. 새 구현에서도 이 회귀를 유지했다.

## 구현한 경로

- `pc_mic_audio.py`: 기존81tap 48→24kHz FIR/400ms context 유지. PCM형식·길이, RMS/peak/clip·VAD경계/여유·capture-edge 위험·노이즈 수치. 외부 장치 identity 재확인 및 오류 비공개 처리.
- `wake_stage1_probe.cpp`: 기존 판정 모드 호환, bounded stdin의832byte 특징/18개 보정/SWK1+WAV 점수 모드. 기존 MFCC/DTW/`calibrate_wake`를 호출하며 한계를 무조건 올리지 않는다. 기본 Heami limit1003q8 유지.
- `pc_mic_profile.py`: C++ pipe 결과·CRC·프로필·점수 검증. 콘솔에는 음향 특징이나 원본을 출력하지 않는다.
- `pc_mic_enroll.py`: 등록3, 보정5/10, 고정 후 새로운 평가5/10 및 무발화3구간. 정확한 녹음/특징 중복 거부, 품질 문제·보정 분리 불가·평가 실패를 숨기지 않는다. 새 평가를 학습에 재사용하지 않는다. Heami 기준 비교, 처리시간/Python 추적 peak 출력. 원본·특징은 파일 저장하지 않는다.
- 새 Windows build/enrollment runner와 기존 mic runner: pinned Zig/sounddevice/NumPy, 현재 입력 장치 수동 선택, 프로필은 명시한 새 `.local/` 파일만 exclusive 생성. 기존 파일/symlink/junction·추적 경로·실패한 동기화의 파일 잔류를 거부/처리한다.
- CI: Windows에서도 실제 Zig C++20 helper를 빌드해 PC 테스트를 실행하고 Linux NumPy 경로도 강제로 검사한다. ESP32-S3 compile-only workflow와 실제 설치 HOLD는 유지한다.

## 로컬에서 실제 실행한 검증

| 명령 | 관측 결과 |
|---|---|
| `uv run --frozen pytest -q -ra` |487 PASS,2 SKIP /74.80초. SKIP은 Windows CMD 통합2개 |
| `uv run --frozen --with numpy==2.3.5 pytest -q -ra firmware/standalone/tests` |261 PASS,7 SKIP /129.20초. Windows runner3, SAPI2, 로컬 libcjson-dev 부재2 |
| PC3개 테스트 파일 +NumPy |57 PASS,3 Windows CMD SKIP |
| `uv run --frozen ruff check .` / `ruff format --check .` |PASS /311files |
| `g++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic ...wake_stage1_probe.cpp` |실제 Linux host 바이너리 생성 |
| 새 fixture `--diagnostics` 실행 |공개 Heami 입력 거리573.84613q8 <1003, `UNVERIFIED_MATCH`, no API/device/audio file |
| `uv build --no-sources --out-dir .local/ci/dist` |wheel/sdist 생성 성공 |
| `uv run --frozen python scripts/ci_verify.py --require-opus` |독립 wheel 설치·Mock MCP/GPT/reconnect/observer/Opus PASS |

개발 과정에서 missing analyzer11errors, 점수/특징 모드2FAIL, 등록 모듈10errors, 진단 CLI1FAIL, 장치 목록·fsync 잔류2FAIL을 먼저 관측하고 구현 후 해당 회귀를 통과했다. C++ 보정/SWK1 점수는 실제 바이너리를 사용했다. 세션 통합 시험의 Heami 음성 변형은 **합성 재생 회귀 입력**이며 독립 사람 표본으로 집계하지 않는다. 필터18kHz 신호가1kHz 기준35dB 이상 억제되는지와2:1 길이·경계·클리핑·무음·장치 교체를 별도 검사했다.

최종 리뷰/정확한 새 head CI 결과는 아래 후속 검증에 기록한다. 이전 e8ee330의 모든 CI 성공은 확인했으나 새 코드 성공으로 대체하지 않는다.

## 미검증·현장 단계

실제 Windows 노트북 마이크 장치·사람 목소리 등록/인식·빠르기/억양/거리/소음·장시간 무발화 오탐·OS/C++ 전체 메모리 사용량은 **미검증**이다. 이 환경은 사용자의 Windows PC나 COM3에 접근할 수 없다. 숫자가 맞도록 입력/임계값을 맞추지 않았다. [현장 상세 안내](../../firmware/standalone/docs/2026-11-20-josu-human-mic.md)대로 새 진단과 등록을 수행한다.

기존 PC MCP의 GPT답변·로봇 음성 현장 성공은 보존하지만 새 “조수” 감지와 연결한 실물 성공이 아니다. `WakeVoiceEntry`/`MicFrameBridge`/STT·GPT·TTS는 host Mock/compile 검증이다. K151 codec/reader는 dormant이고 출고 USB Serial/JTAG PCM API는 미확보다. 실제 API 권한/모델/비용·음성 송신·펌웨어 설치/OTA/NVS/모터·원본 복구 쓰기·실물24h는 실행하지 않았다.

## 구현 판단

- 기존 SWK1을 유지: 실제 개인 자료 없이 무조건 한계 상향/대형 모델 교체로 넘어가지 않는다. 개인 등록 후에도 새 평가가 실패할 수 있으며 실패로 기록한다.
- 원본은 RAM만, 개인 SWK1만 명시적 저장: 재현 파일 유출을 줄이나 중단 시 새로 녹음해야 한다.
- 품질 문제가 있으면 세션 종료: 묵시적 재시도/평가 골라내기를 피하나 전체 새 세션이 필요하다.

현재 상태는 **PC에서 실제 사용자가 검증할 수 있는 진단·등록 코드 준비**, **실제 인식 성공/기기 적용 승인 아님**이다. `main` 병합·기기 설치·환경 게시를 하지 않는다.
