# 무음 WakeNet 진단의 reset 원인과 중단 경계 계측

이전 실물 진단은 `synthetic_inference` 뒤 두 번째 시작 대기 메시지에서
멈췄다. 출고 슬롯을 복구하고 사용자가 얼굴·메뉴 복귀를 확인했다.
그 실행에는 reset reason과 새 24kHz 단계의 중간 기록이 없었다.
[이전 실물 기록](2026-11-21-k151-silent-wake-input-live.md)

## 기록하는 값

- 첫 번째 및 반복 `WAIT_LOCAL_START`에서 고정 ESP-IDF의
  `esp_reset_reason()` 값과 nonce 변경 여부를 구분한다. 0은 IDF의
  unknown이며, 누락되거나 허용 범위 밖이면 값 없음으로 남긴다.
  두 번째 메시지는 원인 값을 보존한 뒤 이전과 같이 시험을 중단한다.
  [고정 ESP-IDF reset reason 정의](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/components/esp_system/include/esp_system.h)
- 24kHz 합성 단계에서 모델 reset 호출 전후와 입력 버퍼 할당·설정,
  첫 poll, 첫 detect, 마지막 reset 경계를 남긴다. 각 경계는 출력한
  뒤 flush한다. 로그 전송 전에 리셋되거나 USB가 분리되면 최신 경계는
  유실될 수 있다. 모델 반환 표시는 성공 여부와 별도로 호출에서
  복귀했음을 뜻한다.
- 기존 로컬 1회 시작, STOP, 10초 기한, 32개 프레임, 160..2048 chunk,
  PCM wipe를 유지한다. 경계 기록 앞뒤에도 동의를 확인한다.
  `max_poll_us`에는 첫 detect checkpoint 출력이 포함되고
  `checkpoint_latency_included:true`가 이를 표시한다.
  이 값으로 운영 음성 경로의 지연을 판정하지 않는다.

## 검증

실제 합성 벤치 코드에 모델 대역을 넣어 정상 흐름, 첫 poll에서 직접
detect가 호출되는 형식, reset 실패, STOP, 첫 detect 도중의 모의 중단,
경계 출력 실패를 실행했다. Windows 수신기 모의 시험은 두 번째 WAIT에서
숫자 reset reason과 마지막 경계를 남기고, START 직렬 flush 실패
뒤에도 STOP을 한 번 시도하는지 확인했다. raw nonce, raw 직렬 내용,
음성은 결과에 포함하지 않는다.

Windows 루트 500 PASS / 2 SKIP, standalone 661 PASS / 5 SKIP,
집중 142 PASS다. 직전 문서 `ae95699`의 CI는 8/9였다. PR Windows
3.11 루트 시험의 heartbeat 회귀에서 최초 음성 요청의 executed가
false여서 실패했다. 가상 soak까지 진행되지 않았고 원인은 미확정이다.
[직전 실패 job](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44896543033/job/136823380742)

이번 단계에는 장치 접근, 리셋, 쓰기, 새 음성 수집과 유료 API가 없었다.
새 계측의 ESP32-S3 빌드 결과와 실물 재시작 원인 판정을 별도로 기록한다.
