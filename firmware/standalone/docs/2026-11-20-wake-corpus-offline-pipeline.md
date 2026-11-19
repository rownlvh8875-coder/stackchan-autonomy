# K151 오프라인 WAV 데이터셋 → SWK1 → 독립 평가 통합 실행기

**상태: 비공개 개인 PC 전용 / 실제 음성 미검증 / 하드웨어 설치 및 외부 전송 금지**

`tools/wake_corpus_pipeline.py`는 서로 떨어져 있던 다음 세 작업을 연결한다.

1. `wake_corpus_audit.py`로 WAV 형식, 최소 그룹 수, PCM 동일 파일 중복, 사용자 선언 녹음 세션 겹침, 클리핑·DC 오프셋·낮은 음량 경고를 검사한다. **품질 경고가 있으면 자동 프로필 생성을 거부**한다.
2. 개인 PC의 `g++` C++20 컴파일러로 기존 `wake_wav_enroll.cpp`를 빌드해 **등록(enrollment)과 보정(calibration)에 속한 파일만** 전달한다. 사용자가 선언한 최종 평가(evaluation) 파일은 보정용 입력에 넣지 않는다.
3. 생성한 임시 `SWK1`의 CRC와 형식을 확인한 다음 기존 `wake_wav_eval.cpp`로 **최종 평가 그룹만** 실행한다. 유효한 출력과 파일 변경 검사를 확인한 뒤 지정한 새 비공개 경로에 `SWK1`를 *독점 생성*한다. 오류 또는 기존 경로가 있으면 덮어쓰지 않으며 임시 파일은 제거한다.

완료해도 상태는 `UNVERIFIED_OFFLINE_PROFILE_AND_EVALUATION`이다. 실제 인식률, 정답 라벨, 녹음 독립성, 화자 신원, 시간당 오인식률, K151 하드웨어 작동 또는 펌웨어 설치 허가는 **입증하지 않는다**. 결과의 `positive_accepted`, `negative_accepted`는 사용자 선언 라벨에 대한 **검증용 샘플 수**이다. 평가 파일이 1개씩이라면 실용적인 정확도에 대한 결론을 낼 수 없다.

## 실행

먼저 사용자의 저장소 바깥 비공개 폴더에 실제 WAV 18개 이상과 `*.wake-corpus.json` 목록을 준비한다. 절차: [개인 데이터셋 준비](2026-11-20-private-wake-corpus-preflight.md).

```powershell
# g++ 없이도 수행 가능한 구조·형식 사전검사. 기존 출력이 있으면 거부.
uv run --frozen python firmware/standalone/tools/wake_corpus_pipeline.py C:\private\stackchan-corpus\owner.wake-corpus.json --output C:\private\stackchan-corpus\owner.swk1 --check-only

# C++20 g++가 설치된 개인 PC에서만 등록 및 독립 평가까지 수행
uv run --frozen python firmware/standalone/tools/wake_corpus_pipeline.py C:\private\stackchan-corpus\owner.wake-corpus.json --output C:\private\stackchan-corpus\owner.swk1
```

컴파일러가 없으면 `gpp_compiler_unavailable`로 종료한다. 컴파일러를 자동 설치하지 않으며 임의의 시스템 권한 변경을 요청하지 않는다. 처음 호출할 때부터 `SWK1` 출력 경로는 존재하지 않아야 한다. 개인 WAV/목록/결과 파일은 **Git 저장소 밖**에 있어야 하며, 코드는 저장소 내부 출력도 거부한다.

## 평가 독립성과 보호 조건

- 1~3개 등록 WAV, 5~32개 보정 호출 WAV, 10~64개 보정 비호출 WAV, **최종 평가 총 2~51개**가 지원 범위이다. 평가에는 호출/비호출이 각각 최소 1개씩 필요하다.
- 동일한 PCM 해시와 중복 경로, 등록·보정·평가 사이의 같은 사용자 선언 session 식별자, 유효하지 않은 WAV·침묵·샘플 수 부족은 거부한다. 두 녹음이 실제로 다른 상황/화자인지 코드는 검증하지 못한다.
- 본 도구는 원본 WAV와 목록을 읽고, 선택한 비공개 폴더에서 임시 C++ 실행파일·임시 SWK1를 만들며, 완료하면 지정된 **새 SWK1만 남긴다**. 소스파일과 원본 음성은 변경하지 않는다. 자동 컴파일과 시험을 포함한 로컬 작업이며 기기·USB·마이크·Wi-Fi·OpenAI API는 건드리지 않는다.
- 단계 전후 파일 SHA-256을 재확인해 일상적인 파일 변경을 막지만 **동시에 변경되는 파일에 대한 완전한 원자적 스냅샷 보장은 없다**. 원본 녹음이 변경되지 않는 격리된 로컬 폴더에서 실행한다.
- `SWK1`은 음성 특징에서 유도된 민감 정보이다. 출력·임시 폴더 접근 권한과 백업을 사용자가 별도 관리해야 한다. 결과 출력에는 파일 경로, 개별 음성 데이터, 특징값, 음성 내용, 각 파일의 해시를 포함하지 않는다.
- 테스트는 실제 ‘조수야’ 음성이 아니라 **합성 톤**을 사용해 C++ WAV 보정·평가 단계를 검증한다. 가상 합격을 실제 음성 인식 성공으로 보고하지 않는다.

하드웨어 설치용 ESP32-S3 `app_main`은 기존 HOLD 상태를 유지한다. 검증되지 않은 공장 펌웨어 복구, AW9523/AXP2101 전원·리셋, 스피커 DMA 배출, 실제 마이크·STOP을 구동하지 않는다.
