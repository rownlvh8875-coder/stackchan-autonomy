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

## 최종 독립 검토와 수정

별도 fresh reviewer(`josu_human_final_review`, gpt-6.2-astra)가 e8ee330..ea582cb를 읽고 Critical0/Important4/Minor2를 보고했다. Important4를 모두 수락했다.

1. 목록과 입력 사이 장치 교체: 표시 descriptor snapshot 후 선택/녹음 전후 재확인. 별칭·구분 불가 중복 항목 거부. 원래 코드에서 선택 창 중 A→B 교체 회귀 FAIL 후 수정 PASS. 동일 속성의 물리 기기 자체는 이 API로 완전 식별할 수 없어 실제 hot-plug 검증은 남는다.
2. 마지막 불완전20ms 활동 누락: 2.515초+끝700샘플 톤 회귀 FAIL 후 actual sample RMS/끝시점 계산 PASS. 기존 aligned 합성 판정 유지.
3. 무발화 중복 평가: 같은 quiet 결과3개를 신선한 평가로 집계하던 회귀 FAIL 후 모든 원본의 private in-memory digest 중복 거부 PASS. 조용한 실제 캡처도 digest를 내며 콘솔에 출력하지 않는 CLI 경계 테스트를 추가했다.
4. 취소/경로 경쟁 중 프로필 파일: 동기화 KeyboardInterrupt 및 create 직전 부모 교체 회귀 FAIL 후 bound directory/동기화된 임시 profile/배타적 hard-link 게시·중단 정리 PASS. Windows 핸들 동작은 새 Windows CI에서 확인한다. 원본 오디오 파일은 생성하지 않는다.

수정 후 PC검사 **65PASS3Windows-onlySKIP**, Ruff313filesPASS. Critical/Important는 단일 수정 패스로 처리하고 두 번째 검토를 요청하지 않았다. 전체 suite/새 head CI는 아래 최종 증거에 기록한다.

유보한 Minor2건: trial prompt의 EOF가 traceback(설치 경로)을 출력할 수 있음; 내부 `--features/--calibrate`를 수동 터미널에 직접 실행하면 바이너리를 출력할 수 있음. 제공한 Python pipe/일반 실행기에서는 내부 바이트를 터미널에 내보내지 않는다. 이 두 항목은 이번 수정 패스에 포함하지 않았다.

검토자가 판단하지 않은 실제 노트북 인식·물리 hot-plug·음향 보정·K151 행동은 미검증으로 유지한다(현장 확인 전 배포/설치 주장 불가). Native Windows와 ESP CI는 정확한 새 head 실행을 직접 확인한다(실패하면 추가 호환 수정 필요).

## 수정 후 최종 로컬 증거

- `uv run --frozen pytest -q -ra`: **487PASS2SKIP**,68.27초.
- `uv run --frozen --with numpy==2.3.5 pytest -q -ra firmware/standalone/tests`: **271PASS7SKIP**,123.25초. SKIP 사유는 위와 같다.
- PC3파일: **65PASS3SKIP**,6.05초. Linux에서는 실제 Windows CMD를 실행하지 않았다.
- Ruff check PASS / format313filesPASS / git diff check PASS.
- 수정 후 wheel/sdist 재빌드 및 독립 wheel Opus/Mock MCP·GPT·재연결·observer PASS.

## 첫 새 CI의 Windows 실패 (숨김 없이 기록)

f932d5a에서 Linux Python3.11/3.12 및 ESP32-S3 compile-only는 PASS였다. Windows3.11/3.12의 PC시험은 **67PASS1FAIL**: `test_parent_replacement_before_create_does_not_write_outside`. `FILE_READ_ATTRIBUTES`만 요청한 디렉터리 핸들은 data-access sharing 검사를 강제하지 않아 부모 교체를 막지 못했다. 새 수정은 `GENERIC_READ`(FILE_LIST_DIRECTORY 포함)로 핸들을 열어 WRITE/DELETE 공유 거부를 적용한다. 동일한 Windows 회귀를 완화하거나 건너뛰지 않고 새 head CI에서 다시 확인한다.
