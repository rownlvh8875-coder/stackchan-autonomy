# K151 전원·리셋·DMA 보호 검증 추가 — 2026-11-19

상태: **HOST MOCK 검증 전용 / 하드웨어 무접근 / 펌웨어 설치 금지**.

## 기존 커밋 중복 검토

개발 중 동일 브랜치에 신규 커밋 `9becfa4`가 반영된 것을 확인했다. 이 커밋은 `K151CodecPort`에 출력 금지 상수(HOLD)를 적용하고, 검증된 관측 장치가 없는 `drain_output_before_mute()`를 기본 거부하도록 설계했다. 따라서 별도의 독립형 K151 실제 하드웨어 어댑터를 중복 연결하지 않기로 했다. `app_main`에 변경 사항도 남기지 않는다.

## 이번 보완: 오디오 라이프사이클 순서의 호스트 테스트

`tests/audio_hardware_wiring.hpp` 및 `tests/audio_hardware_wiring_test.cpp`는 **FakeCodec / FakeBoard**에서만 이용하는 테스트 고정구이다. 실제 드라이버와 연결하지 않는다. 아래 조건을 확인한다.

- `AudioGuard`가 초기 승인·식별 플래그를 받기 전에 오디오 구동을 시작하지 않음
- 물리 음소거 요청을 코덱 출력 종료보다 먼저 시도하며, 어느 하나가 실패해도 전체 성공으로 오판하지 않음
- 보드 식별, 전원 레일, 증폭기 리셋 확인에 실패하면 코덱 준비와 스피커 시작을 거부
- 캡처와 스피커가 동시에 활성화되지 않고, 마이크 DMA flush 실패 시 녹음을 거부
- 마지막 PCM 전송 후 DMA 소진 확인이 없으면 amp off를 시도하고 오류 상태를 유지
- 오류 후 재차 STOP을 받아도 재개 가능한 상태로 격하되지 않음

## 원천 코드 근거 및 제한

- [M5Stack 고정 소스 `stackchan.cc`](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc): `Aw9523::ResetAw88298()`의 레지스터 `0x02` 변경 및 10ms/50ms 대기, AXP2101 PMIC 구성 확인. LCD·전원 공유 관계 때문에 실제 레지스터 쓰기를 무단 복제하지 않음.
- [Espressif ESP32-S3 I2S 문서](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/i2s.html): DMA 기반 전송 및 드라이버 API 설명. 코덱 write 성공을 K151 아날로그 출력 소진의 계측 증거로 해석하지 않음.

이번 테스트는 전원·리셋·STOP·DMA 동작의 **실측이 아니라 계약 검증**이다. `PhysicalAudioEvidence`는 테스트 전용 추상 인터페이스로, 실제 K151 구현체가 없다. 별도 물리 계측과 보드 호환성/백업 복구 승인 없이는 하드웨어를 켜거나 설치할 수 없다.
