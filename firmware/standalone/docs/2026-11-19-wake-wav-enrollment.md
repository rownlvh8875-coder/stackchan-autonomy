# K151 '조수야' WAV 등록·보정 도구 (2026-11-19)

**상태: 개인 PC의 오프라인 C++20 도구. 실음성 자료 없이 구현·합성 데이터 검증만 수행.**

`tools/wake_wav_enroll.cpp`는 이미 보유한 개인 음성 WAV 파일에서 **기존** `core/wake_features.hpp`의 MFCC/DTW 특징을 추출하고, 서로 분리된 입력 그룹을 이용해 `calibrate_wake()` 보정 후 전용 `SWK1` 프로필을 생성한다. 아래 조건은 소프트웨어가 사용하는 **최소 입력량**일 뿐 실제 호출어 인식의 통계적 성능 또는 사용자 인증 수준을 보증하지 않는다.

| 그룹 | 파일 수 | 의미 |
|---|---:|---|
| `--template` | 1~3개 | 등록에 사용하는 '조수야' 음성 |
| `--holdout` | 5~32개 | 등록에 쓰지 않은 별개의 '조수야' 음성 |
| `--negative` | 10~64개 | 다른 말, 일상 음성, 환경 소음 등 비호출어 |
| `--output` | 새로운 SWK1 파일 1개 | 생성 결과 (기존 파일 덮어쓰기 금지) |

모든 WAV는 24kHz, 모노, PCM16, 0.1~3초, 비압축 RIFF/WAVE 형식만 허용된다. 다른 채널/샘플 속도, 침묵, 과도하게 큰 파일, 잘못된 헤더·형식은 거부한다. WAV 메타데이터가 다르더라도 **PCM 내용이 동일하면** 등록·검증·비호출어 전 그룹에 걸쳐 중복을 거부한다. 명칭·내용 중복 차단은 별도 화자/별도 녹음 여부를 입증하지 못한다.

## 개인 PC에서 빌드·실행

C++20 `g++`를 설치한 **개인 PC**에서:

```bash
g++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic \
  -Ifirmware/standalone/core \
  firmware/standalone/tools/wake_wav_enroll.cpp \
  -o wake_wav_enroll

./wake_wav_enroll \
  --template /private/enroll01.wav \
  --holdout /private/positive01.wav \
  --holdout /private/positive02.wav \
  --holdout /private/positive03.wav \
  --holdout /private/positive04.wav \
  --holdout /private/positive05.wav \
  --negative /private/negative01.wav \
  --negative /private/negative02.wav \
  --negative /private/negative03.wav \
  --negative /private/negative04.wav \
  --negative /private/negative05.wav \
  --negative /private/negative06.wav \
  --negative /private/negative07.wav \
  --negative /private/negative08.wav \
  --negative /private/negative09.wav \
  --negative /private/negative10.wav \
  --output /private/owner-profile.swk1
```

각 반복 옵션은 개인 데이터의 종류에 맞춰 추가할 수 있다. 위의 경로는 예시이며 실제 파일이 존재해야 한다. **본 작업에서는 실제 음성파일이나 개인 프로필을 생성하지 않았다.** 테스트에서 생성하는 WAV는 모두 합성 신호이며 실제 '조수야' 발음이 아니다.

출력은 `SWK1` 프로필 검증 및 별도 재평가 `tools/wake_wav_eval.cpp`에 사용한다. 보정된 임계값은 현재 녹음/녹음 환경에 한정되며 잡음·거리·화자 변화·로봇 스피커 자기 음성에 대한 실제 성능은 별도 데이터를 이용해 검증해야 한다. 원본 음성 중 보정에 사용된 파일을 독립 테스트에 재사용하면 안 된다.

## 보안 및 제한

- 오프라인 과정에서 K151/USB/마이크/네트워크/API를 시작하지 않고 출고 펌웨어, NVS, OTA 설정을 변경하지 않는다.
- 개인 WAV는 읽기만 하고, **새 SWK1 파일만 사용자가 명시한 경로에 독점 생성**한다. 이미 존재하는 출력 파일·심볼릭 링크를 덮어쓰지 않는다. POSIX에서는 출력 파일을 사용자 전용(0600)으로 생성한다.
- 터미널 출력에는 파일 경로·PCM·등록 특징을 넣지 않는다. 프로필은 음성에서 파생된 민감한 자료이므로 별도 보관한다. 저장소 `.gitignore`는 `*.swk1`, `*.scfgbundle`, `*.wav`, `*.WAV`를 제외한다. 개인 자료는 처음부터 저장소 밖에 두어야 한다. Git의 강제 추가(`-f`) 등은 별도 주의가 필요하다.
- 등록용 SWK1는 **음성 생체인증서가 아니다.** 출력이 정상이어도 실제 한국어 인식률이나 false wake/hour를 증명하지 못한다.
- 실제 장비 설치는 별도 명시적 승인과 공장 펌웨어 복구·전원·STOP 검증 후에만 판단한다. 현재 K151 HOLD 게이트는 수정하지 않는다.
