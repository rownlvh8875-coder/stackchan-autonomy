# K151 증폭기 전원·리셋 / DMA 배출 사전 검증 (2026-11-19)

상태: **SOURCE-VERIFIED / HOST-CONTRACT ONLY / NOT HARDWARE-TESTED / NO FLASH**.

## 확인한 실제 소스와 범위

- [M5Stack StackChan 고정 커밋 `28b9f0c` / `firmware/main/hal/board/stackchan.cc`](https://github.com/m5stack/StackChan/blob/28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400/firmware/main/hal/board/stackchan.cc): K151 계열 보드 코드는 I2C 주소 `0x34`의 AXP2101 PMIC와 `0x58`의 AW9523 확장기를 초기화한다. AW9523의 `ResetAw88298()`는 레지스터 `0x02`의 출력 상태를 `0b00000011` → 10ms → `0b00000111` → 50ms로 바꾼다. 또한 LCD 리셋, PMIC 레일 변경, 전원 관리 동작이 공유되어 있으므로 이 시퀀스를 독립 펌웨어에 무조건 복제하지 않는다.
- [ESP-IDF v6.1 고정 커밋 `fff9895` / I2S 문서](https://github.com/espressif/esp-idf/blob/fff9895c82d744c7237be8847347bdd1b07c6643/docs/en/api-reference/peripherals/i2s.rst): I2S 전송과 DMA 사용 방식을 기술한다. `esp_codec_dev_write`의 성공 반환을 코덱 큐 배출, 증폭기 아날로그 출력 완료 또는 물리 STOP 검증으로 간주할 수 없다.
- 해당 소스는 코드 상의 설계 근거이며, **실제 소유한 K151의 보드 리비전·전원 레일·앰프 출력 실측을 대체하지 않는다.**

## 이번 변경

1. `core/k151_output_evidence.hpp`: 실물 기동 전 별도로 확인할 항목(보드·I2C 점유·전원 레일·AW9523 리셋·실측 mute·STOP·DMA+코덱 idle)을 항목별로 표시한다. 모든 항목을 `true`로 입력해도 `kK151PhysicalOutputEnabledInHoldImage=false`이므로 기동되지 않는다. 수기 참/거짓은 인증 증거가 아니다.
2. `DmaDrainLedger`: 재생 프레임 수와 단조시간, 독립 DMA 비움·코덱 idle·클럭 관찰·STOP 상태에 대한 향후 드라이버 계약. 대기시간만 지났거나 단순 write ACK만 온 경우에는 완료로 인정하지 않는다. 합성 데이터로만 테스트했으며 실제 관찰자는 구현하지 않았다.
3. `K151CodecPort::speaker_on_low_volume()`: AXP2101/AW9523 및 DMA 경로 미실측 상황에서 실제 코덱 출력을 시작할 수 없도록 컴파일 타임 HOLD 게이트를 추가했다.
4. `K151CodecPort::drain_output_before_mute()`: 실제 DMA·코덱 소진을 확인할 장치 구현이 없으므로 **항상 false**를 반환한다. `k151_unapproved_audio_hooks()`의 주변장치 초기화·마이크 FIFO flush·DMA drain 콜백도 fail-closed이다.
5. `app_main`은 위 헤더를 컴파일 대상에 포함할 뿐 객체 생성/출력/PMIC·AW9523 쓰기 작업을 실행하지 않는다.

## 실제 기기에 적용하려면

독립 보존한 공장 이미지 A/B와 복구 절차, 활성 OTA 슬롯, 정확한 보드 리비전·전원 레일, LCD와 공유 I2C 사용권, AW9523 출력 리드백, 앰프 전기적 mute, 사용 중/정지 시 소비전력, 실제 DMA와 코덱 내부 잔량에 대한 관찰 수단, STOP 반응시간 계측, 별도 실물 설치 승인이 필요하다.

**불가한 결론:** 이번 CI 컴파일과 가짜 소자 테스트만으로 '실제 스피커·전원 초기화·DMA drain 통과', '하드웨어 설치 가능', '조수야 한국어 인식 정확도 확보'를 주장할 수 없다. 로봇 플래시·NVS·전원·I2S·USB·API 키는 변경하지 않았다.
