# K151 마이크 단독 입력 검증

2026-11-21 Windows, `feat/wakeword-josu`. 기준 `24c5236`의 push, PR,
ESP32-S3 CI는 각각 4/4, 4/4, 1/1이었다.
[Push](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44871476127)
[PR](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44871481333)
[ESP32-S3](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44871481319)

## 검증 범위

- 고정 ESP-IDF와 esp_codec_dev 1.6.2에서 ES7210의 최종 수신 설정을 대조했다.
  24kHz PCM16, Philips TDM, 두 슬롯, mask 3, word select 16비트, left align을
  사용한다. 기존 duplex 경로는 원래 4슬롯 초기값과 SDK 설정을 사용한다.
- 등록된 RX handle의 상태를 핀 초기화 전에 확인한다. 모의 driver는 이 모드의
  TX, AW88298, SDK I2S data factory 접근을 거부하도록 작성했다.
- 모의 ES7210 입력의 두 슬롯에서 mic0만 추출했다. 기존 FIR에서 24kHz 240개
  샘플을 16kHz 160개 샘플로 변환했다. 실제 마이크와 호출어 인식은 검증 대기다.
- 단독 준비가 항상 실패하는 초기 상태에서 정상 준비 시험을 먼저 실패시켰다.
  이후 짝 채널이 있을 때 핀을 먼저 설정하는 문제, 해제 실패 후 후속 읽기가
  다시 해제를 시도하는 문제, 마이크 닫기 오류 후 RX가 남는 문제를 각각
  모의 driver로 재현한 뒤 수정했다. 동의 철회, STOP, 짧은 수신은 PCM을
  지운다. raw RX 해제 실패는 명시적 종료의 결과에도 남는다.
- 최종 코덱 모듈 77 PASS. 마이크 단독 모드 11개와 기존 duplex,
  코덱 데이터·제어 및 해제 오류 회귀를 포함한다.

## 실물 시험 전 확인

마이크 전원과 GPIO0의 MCLK를 포함한 핀 상태, 클록이 동작할 때의 앰프
격리, I2S0 단일 소유권을 현재 보드에서 확인해야 한다. 마이크 FIFO와
마이크 채널, STOP의 실제 지연, WakeNet까지의 실물 인식은 이 검증 범위에
포함되지 않는다. 운영 `app_main`은 HOLD이며 cloud와 물리 출력은 비활성이다.

M5Stack의 K151 문서가 연결한 CoreS3 v1.0 회로도 4–5쪽에서 마이크와
앰프가 BCK/WCK를 공유한다. GPIO0의 ESP_BOOT는 R34를 통해 ES7210
MCLK로 연결된다. AW9523B P0_2의 AW_RST는 AW88298 RSTN으로 이어진다.
확인 대상으로는 ES7210의 VDDA_3V3 및 MICBIAS12, 클록 동작 중 RSTN과
스피커 출력이 있다. 도면은 측정 대상과 신호 이름의 근거다. 현재 장치의
보드 리비전과 신호 상태는 실측으로 확인해야 한다.
[M5Stack CoreS3 v1.0 회로도](https://m5stack-doc.oss-cn-shenzhen.aliyuncs.com/490/Sch_M5_CoreS3_v1.0.pdf#page=4)

이번 작업의 기기 접근, 리셋, 쓰기, 실제 음성 수집, 유료 API 호출은 0회다.
직전 TLS 진단에서 원본 슬롯과 표·OTA 일치를 검증하고 출고 부팅을 요청했다.
그 재부팅 이후 화면 복귀의 사용자 확인은 대기 중이다.
[직전 복구 기록](2026-11-21-k151-local-tls-live.md)
