# 2026-11-20 — 한국어 Vosk 오프라인 2차 호출어 확인 실험

**현재 결론: 실제 PC에서 2단계 연결 성공, 그러나 ‘조수야’ 전부 미인식 → K151 적용 거부**

## 구현 범위

1. 1차: 기존 C++ MFCC/DTW `SWK1` 호출 감지기
   (`tools/wake_stage1_probe.cpp`)를 각 파일에서 실행. 이전
   3템플릿 augmented/trim 실험용 프로필의 경우 **컴파일 시에만**
   `-DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1` 사용.
2. 2차: **1차가 수락한 파일에 대해서만** 로컬 Vosk 한국어
   `vosk-model-small-ko-0.22`로 STT 수행. 24kHz/모노/PCM16
   입력을 16kHz로 resample한 후 Vosk recognizer 사용.
3. 최종 판정: 한국어 전사 문자열을 Unicode NFKC로 정규화하고
   공백과 **후행 문장부호만** 제거해 **정확히 `조수야`일 때만**
   수락. 유사 발음, 앞뒤 추가 단어, 빈 텍스트, 인식 실패,
   모델 미설치, 파일 오류, 1차 미수락은 모두 거부.
   편집거리/유사어 허용, 미인식 때 1차만으로 수락하는 우회는 없음.

이는 PC 오프라인 실험이며 ESP32-S3 펌웨어 코드에 포함되지 않고
로봇 마이크·스피커·전원·GPIO·NVS·OTA·FLASH를 건드리지 않는다.
Vosk 모델/패키지는 실험 노트북 별도 폴더에 설치되며 **모델 파일과
사용자 음성 데이터는 GitHub에 업로드하지 않는다**.

## 실제 실행에 사용한 자료와 출처

- 음성 입력: 이전 공개 합성 테스트 세트
  `fixtures/korean_heami_conv_postfreeze_20261120/`의 **‘조수야’
  4개·비호출어 12개**. 같은 Microsoft Heami Desktop TTS 목소리.
  이미 이전 CNN 실험에서 공개된 자료이므로 **새로운 독립
  평가 세트가 아닌 사전 기능 시험**으로만 해석한다.
- 1차 프로필:
  `fixtures/korean_heami_fresh_holdout_20261120/robust_trim_aug_frozen.swk1`
  (3템플릿, 위 문서의 augmented/trim 실험 후보).
- 오프라인 Vosk 엔진 Python 패키지: `vosk==0.3.45`을 uv 캐시에
  1회 준비한 후 음성 처리 단계에서는 **인터넷 사용 없음**.
- 한국어 모델: 공식 Vosk Models 페이지의
  [vosk-model-small-ko-0.22](https://alphacephei.com/vosk/models)
  (공식 목록상 약 82MB/Apache 2.0; Zeroth Test WER 28.1은
  **본 실험의 실제 오류율이 아님**). 모델 공식 ZIP:
  `https://alphacephei.com/vosk/models/vosk-model-small-ko-0.22.zip`
  (다운로드된 원본 86,914,329 bytes, 해제 후 264,364,726 bytes).
  ZIP **관측 SHA-256**:
  `eea36124087fed26c59996a4761519458e3bd185e8ea9d9865ad8760c4a1d989`.
  이 해시는 **다운로드 사본 식별값**이며 공식 서명/공급망
  인증을 뜻하지 않는다.
- ZIP 다운로드는 개발환경 준비를 위해 한 번 수행했고, 이후 모델
  로딩·추론은 노트북 내에서만 진행했다. 외부 Vosk 서버와 연결하지
  않았다. 공개 문서상 소형 모델은 런타임 메모리를 수백 MB
  요구할 수 있으므로 **K151 ESP32-S3 직접 탑재 적합성은 입증되지
  않았고 현실적으로 어려울 수 있다**.

## 직접 관측한 기초 실행 결과

| 검증 | 1차 DTW만 | 1차 + Vosk 정확 전사 |
|---|---:|---:|
| 합성 ‘조수야’ 감지 (4개) | **4/4** | **0/4** |
| 비호출어 잘못 수락 (12개) | **1/12** | **0/12** |
| Vosk 2차 실행 | 없음 | 1차 수락 **5개만** |
| 로컬 16개 음성 처리 벽시계 시간 | 비교 측정 없음 | 약 **6.0초** (PC, Python+네이티브 실행 합계) |

**판정:** 2차 확인은 이 테스트에서 잘못된 호출은 막았지만
정상적인 호출도 **4개 모두 놓쳤다**. 한국어 짧은 발화 전사가
기대 문구와 일치하지 않았기 때문이다. 실제 보류·평가로
얼마나 일반화되는지는 알 수 없으며, 0/12 오인식은 유용한
인식기가 됐다는 근거가 아니다.

본 결과는 실제 사람 목소리, 화자·방언·거리·소음·잔향,
시간당 오작동, K151 실측 RAM/CPU·전력·시간지연,
기기 출고 펌웨어 복구 가능성 또는 물리 STOP을 증명하지 않는다.

## 재현 명령 (PC에서만)

```powershell
# 라이선스 확인 후 공개 모델을 노트북에 한 번 다운로드·안전 해제한다.
# Vosk 패키지와 모델은 준비 후 절대로 음성 자료를 업로드하지 않는다.

# 설치한 Windows 노트북: 이미 준비한 Zig C++20 컴파일러 사용
uvx --offline --from ziglang==0.15.2 python-zig c++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic -DSTACKCHAN_EXPERIMENTAL_WAKE_TRIM=1 -Ifirmware/standalone/core firmware/standalone/tools/wake_stage1_probe.cpp -o C:\private\wake_stage1_probe.exe

uv run --frozen --with vosk==0.3.45 python firmware/standalone/tools/vosk_wake_second_stage.py --manifest firmware/standalone/fixtures/korean_heami_conv_postfreeze_20261120/cnn-postfreeze.wake-corpus.json --stage1-binary C:\private\wake_stage1_probe.exe --stage1-profile firmware/standalone/fixtures/korean_heami_fresh_holdout_20261120/robust_trim_aug_frozen.swk1 --vosk-model-dir C:\private\vosk-model-small-ko-0.22
```

기본 CI는 다운로드·패키지 설치 없이 1차 C++ 빌드, 오프라인
문자열 판정, WAV 변환, 2차 실행조건과 fail-closed 동작만
검증한다. Vosk 모델 실측은 이미 모델을 설치한 별도 PC에서만
수행한다.

## 후속 개발의 필수 조건

현재 공개된 Heami 합성 평가 WAV는 이미 검사된 데이터이므로
새 후보를 선택할 때 독립 평가로 **재사용하지 않는다**.
본 모델은 한국어 짧은 호출어에 매우 낮은 감지율을 보였다.
소규모 같은 TTS 목소리만으로 성능 개선을 주장할 수 없다.
별도 한국어 ASR/KWS 모델을 검토하거나, 사용자 허가하에
실제 사람 발화의 비공개 녹음본과 독립 테스트 구성이 필요하다.

**이번 결과로는 K151 자동 음성 호출 기능의 배포/실기기 설치 불가.
기존 `HOLD`, STOP, PMIC, AW9523, NVS, OTA, factory firmware 유지.**
