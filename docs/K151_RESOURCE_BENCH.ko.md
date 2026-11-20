# K151 무음 자원 진단 앱 — 설치 미승인

이 별도 앱은 **기본 호출어의 자원 측정 준비물**이다. 기본 HOLD 앱과 운영 대화
경로를 바꾸지 않는다. 마이크·스피커·모터·디스플레이·Wi-Fi·NVS·실제 API를
초기화하지 않는다. 새 실음성 수집/저장/업로드도 없다.

고정 SDK의 `srmodel_load`가 앱 내 불변 pack을 읽는 경로를 사용한다. pack의
실제 길이292607, SHA256, DROM 위치와 PSRAM 제외, 로컬 동의와 STOP을 검사한
뒤에만 기존 K151WakeNetPort가 SDK global loader를 독점한다. 파티션 표와
별도 model 영역을 설치할 필요가 없다. 이 경로의 성공은 partition 경로의 성공
증거가 아니며, 기존 partition 검증 경로도 유지한다.

향후 설치를 별도 승인받은 경우에만, USB Serial/JTAG가 부팅 nonce를 표시한다.
60초 내 `START <표시된 8자리 대문자 nonce>` 한 줄을 보내야 동의가 열린다.
한 번만 실행하며 `STOP`/잘못된 입력/시간 역행/기한 경과는 취소 latch다.
시작 뒤10초 제한과 최대64개 chunk를 적용한다. 별도 reader task가 동의를
취소하며, 이미 실행 중인 SDK 동기 호출을 강제 선점하지는 못한다.
이는 로컬 실험자의 명시적 시작이며 인증된 사용자 신원이나 운영 STOP 증거가 아니다.

측정 대상은 실제 model context 전후의 capability별 free/largest/minimum heap,
동시 질문384000bytes/TTS960000bytes vector의 실제 PSRAM 배치, 합성 무음
64chunk의 최대 detect 시간/100ms 초과 수다. 모델 flash 길이를 RAM으로
환산하지 않는다. PCM은 기존 volatile wipe를 재사용한다. TLS/JSON/네트워크와
codec/DMA 동시 부하는 **미측정**, operating_admission은 항상false다.
64chunk 완료도 실제 호출어 인식이나 GPT 대화 성공이 아니다.

## 산출물과 변경 범위

CI는 기존 HOLD와 별도 진단 앱을 모두 pinned IDF6.1/SR2.4.7로 compile/link한다.
진단 artifact에는 generic app bin/ELF, SHA/offset 검증 manifest, Espressif
모델 라이선스만 넣는다. 원본 백업·사용자 설정·키는 포함하지 않는다.
`check_resource_bench.py`는 ESP32-S3 header/segment/checksum/SHA, 전용 app
descriptor와 DROM 내 모델 SHA, 슬롯 크기와 sector 반올림 범위를 검증한다.

**아직 쓰기 승인은 없다.** 제안 대상은 `ota_1@0x510000`이며 이미 출고 앱이
들어 있다. 원본 메타데이터는 이 슬롯을 선택 후보로 가리키지만 현재 실행 슬롯과
안전한 spare를 확정하지 않는다. 설치는 해당 출고 앱 일부를 파괴하는 교체다.
정확한 bin 길이와 SHA/sector 범위는 실제 빌드 manifest로 확정해야 한다.
bootloader/partition/NVS/otadata/assets/coredump에는 쓰지 않는다. 생성된
IDF bootloader/table/flash_args는 실물에 적용하지 않는다.

설치 전 로컬 private 검토 묶음에 실제 app+SHA, 원본 A/B 전체 SHA 일치,
원본 slot1 복구 slice+SHA, 정확한 쓰기/검증/복구 명령, 중단 조건을 준비한다.
현재 실행 슬롯·factory bootloader 호환·복구 쓰기와 별도 저장장치 사본은
미검증으로 표시한다. 승인 이후에도 포트/칩/보호 상태/원본 표·OTA가 달라지면
중단한다. write/verify 실패나 brownout 시 자동 재시도·다른 슬롯 쓰기는 하지 않는다.

근거: [고정 SDK loader](https://github.com/espressif/esp-sr/blob/2f8c4b0459db5bbb39abd77adae27962d6d94bcb/src/model_path.c),
[K151 공식 Quad PSRAM 사양](https://docs.m5stack.com/en/StackChan),
[원본 복구 절차](K151_BACKUP_RECOVERY.ko.md).
