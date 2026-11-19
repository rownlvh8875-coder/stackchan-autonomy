# 2026-11-20: 한국어 '조수야' 로컬 TTS 호출어 검증

**범위: Windows 내장 한국어 SAPI 합성 음성, 오프라인 MFCC/DTW 스모크 테스트.**
**실제 화자 인식 정확도, 실기기 K151 구동, 시간당 오작동률에 대한 증거가 아님.**

## 테스트 환경

- 연결된 사용자의 Windows 노트북에서 **Microsoft Heami Desktop (ko-KR)** SAPI 음성 확인.
- `tools/synthesize_korean_wake_sapi.py`로 **장치·마이크·유료 API 없이** 한국어 WAV 24개 생성. Windows SAPI `SpeechSynthesizer.SetOutputToWaveFile`만 사용하며, 24kHz 모노 PCM16으로 정규화.
- 등록용 1개, 보정용 호출 5개·비호출 10개, 따로 선언한 평가용 호출 2개·비호출 6개. 호출 음성은 모두 실제 단어 **‘조수야’**를 읽는 TTS 음성이다. 비호출어에는 ‘조수’, ‘조수님’, ‘주스야’, ‘조수석’, ‘준수야’, ‘소주야’ 등 다른 한국어 발화가 포함된다.
- 속도 변경으로 음성을 달리 만들었지만 **동일한 TTS 음성엔진·동일한 화자**이므로 독립 화자·독립 녹음 환경 검증으로 주장하지 않는다. 학습/평가 파일 그룹을 코드에서 분리했더라도 분포 독립성을 증명할 수 없다.
- `wake_corpus_audit.py` 결과: `CORPUS_STRUCTURALLY_SCREENED`, 24 WAV, 형식 불일치/동일 PCM 중복/음질 사전 경고 없음. WAV 길이는 사전 검사 결과 등록 1389ms, 보정 1121~1912ms, 평가 905~1711ms였다.
- Windows에는 시스템 C++ 컴파일러가 없어서, **일회성 개발 도구 다운로드**로 PyPI `ziglang==0.15.2`를 uv 캐시에 준비했다. 이는 오직 **컴파일러를 받기 위한 네트워크 사용**이며, 음성 생성이나 API 추론을 위한 외부 전송이 아니다. 이후 빌드에는 `uvx --offline`을 사용했다.

## 기존 실제 C++ MFCC/DTW 경로의 관측 결과

`wake_corpus_pipeline.py`의 `--offline-zig` 경로로 기존 `wake_wav_enroll.cpp`와 `wake_wav_eval.cpp`를 컴파일하고 **비공개 로컬 WAV**를 평가했다. 템플릿+보정 데이터로 `SWK1` 1개를 생성했으며 `scfg_offline.validate_profile`에서 1개 템플릿과 CRC 유효성을 확인했다. 표본은 절대로 Git에 업로드하지 않았다.

| 오프라인 평가 | 실제 관측값 | 해석 |
|---|---:|---|
| 합성 ‘조수야’ 2개 | **2/2 수락** | 이 TTS 조건에서 2개 음성 일치 |
| 합성 비호출어 6개 | **0/6 수락** | 이 TTS 조건에서 오탐 없음 |
| 생성 SWK1 파일 | **843 bytes** | 1개 템플릿 SWK1 포맷 (CRC 검증) |
| 실인물 발화·마이크 | **0건** | 성능 검증 근거 없음 |

이 수치로 ‘한국어 인식률 100%’나 ‘실기기에서 오탐 0%’를 주장할 수 없다. 같은 TTS 모델에서 가까운 발음 몇 개를 시험한 소규모 **기능 연결 검증**일 뿐이다.

## 동일한 테스트를 비공개 환경에서 반복하는 방법

```powershell
# 출력 위치는 Git 저장소 밖의 새 개인 폴더를 지정한다.
uv run --frozen python firmware/standalone/tools/synthesize_korean_wake_sapi.py --output C:\private\wake-sapi-demo

# 데이터셋 구조·음질·그룹 분리 확인
uv run --frozen python firmware/standalone/tools/wake_corpus_audit.py C:\private\wake-sapi-demo\synthetic-sapi.wake-corpus.json

# 오프라인 Zig 컴파일러는 사전에 한 번만 명시적으로 캐시한다.
uvx --from ziglang==0.15.2 python-zig version

# 실제 실행은 --offline만 허용하며 외부 TTS·OpenAI API를 사용하지 않는다.
uv run --frozen python firmware/standalone/tools/wake_corpus_pipeline.py C:\private\wake-sapi-demo\synthetic-sapi.wake-corpus.json --output C:\private\wake-sapi-demo\demo.swk1 --offline-zig
```

위 경로는 예시이며 출력 폴더와 프로필 파일은 **기존 파일이 없어야 한다**. Windows Heami 음성이 설치되어 있어야 한다. `tools/synthesize_korean_wake_sapi.py`는 생성된 개인 폴더를 기본적으로 건드리지 않으며, 실패한 *신규* 폴더만 정리한다.

## 다음 단계와 한계

실제 설치 가능성 판단에는 독립적으로 녹음한 한국어 ‘조수야’, 다른 발음/방언/거리/잔향/소음/로봇 스피커의 에코가 필요하다. 보정에 사용한 음성은 최종 정확도 평가에 재사용할 수 없다. 실제 마이크 입력 레인, 샘플 클럭, K151 전원·리셋·증폭기 전기적 뮤트, 물리 STOP 지연 및 공장 펌웨어 복구 절차도 별도로 확인해야 한다.

**이번 음성은 실제 사용자의 목소리도, 음성 생체인증 모델도 아니다.** `app_main`의 HOLD, `kK151PhysicalOutputEnabledInHoldImage=false`, OTA/NVS 변경 금지, 실제 요금 발생 API 차단은 그대로 유지한다.
