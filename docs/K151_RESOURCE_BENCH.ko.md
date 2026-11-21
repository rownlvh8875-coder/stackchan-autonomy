# K151 무음 자원 진단 앱 — 실물1회·원본 슬롯 복구

2026-11-21 사용자의 “진행해 승인” 뒤 검토한 앱을 한 번 임시 설치했다.
실제 모델 준비/64 합성 chunk(최대7.615ms)/질문·TTS 동시 PSRAM 배치를 확인하고,
원본slot1을 복구·독립 verify했다. 표/OTA도 전후 동일하다. 이번 복구 뒤의
출고 얼굴/메뉴 복귀도 다음 보드 조회 승인 전에 사용자 확인을 받았다.
[실물 기록](validation/2026-11-21-k151-silent-resource-bench.md)을
현재 판정으로 사용한다. 실제 호출어·TLS·독립 GPT·운영 admission은 미검증이다.

이 별도 앱은 **기본 호출어의 자원 측정 준비물**이다. 기본 HOLD 앱과 운영 대화
경로를 바꾸지 않는다. 마이크·스피커·모터·디스플레이·Wi-Fi·NVS·실제 API를
초기화하지 않는다. 새 실음성 수집/저장/업로드도 없다.

고정 SDK의 `srmodel_load`가 앱 내 불변 pack을 읽는 경로를 사용한다. pack의
실제 길이292607, SHA256, DROM 위치와 PSRAM 제외, 로컬 동의와 STOP을 검사한
뒤에만 기존 K151WakeNetPort가 SDK global loader를 독점한다. 파티션 표와
별도 model 영역을 설치할 필요가 없다. 이 경로의 성공은 partition 경로의 성공
증거가 아니며, 기존 partition 검증 경로도 유지한다.

설치 승인 범위에서 USB Serial/JTAG가 부팅 nonce를 표시한다.
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
실제 checkout commit40자와 앱 내부 version의12자 접두부도 결합한다. 컨테이너
Git 소유권 오류/빈 커밋을 성공으로 발행하지 않으며 ELF SHA도 bin descriptor와
일치해야 한다. 빌드 성공과 설치 검토 자료의 완전성을 따로 검증한다.

승인한 `ota_1@0x510000`은 출고 앱이 들어 있는 슬롯이었다. 전체 원본 slice와
장치 digest가 일치한 뒤625968bytes 진단 앱을 썼고, erase 영향은626688bytes였다.
진단 한 번 후 같은 슬롯5177344bytes를 원본으로 되돌리고 별도 verify했다.
메타데이터 선택 후보와 안전한 spare를 동일시하지 않았다. 진단/복구의 정확한
SHA와 범위는 [실물 manifest](validation/2026-11-21-k151-silent-resource-bench.json)에 있다.
bootloader/partition/NVS/otadata/assets/coredump에는 쓰지 않는다. 생성된
IDF bootloader/table/flash_args는 실물에 적용하지 않는다.

설치 전 로컬 private 검토 묶음에 실제 app+SHA, 원본 A/B 전체 SHA 일치,
원본 slot1 복구 slice+SHA, 정확한 쓰기/검증/복구 명령, 중단 조건을 준비한다.
2026-11-21에 C: disk0과 D: disk1이 서로 다른512GB 내장 NVMe/NTFS임을 확인했다.
D:의 새 접근 제한 폴더에 전체 원본16MiB 사본을 만들고 SHA 일치를 확인했다.
폴더와 파일은 현재 사용자/SYSTEM만 허용하며 원본 내용은 업로드하지 않았다.
이번 이미지의 factory bootloader 부팅과 같은 슬롯 복구 쓰기는 관측했다.
다른 이미지/전체flash 복구나 일반적인 spare 안전성으로 확대하지 않는다.
슬롯 단독 복구 slice는 전체 원본 백업에서 추출한 정확한 slot1 범위이며, 다른
영역이 바뀐 경우의 전체 flash 복구를 대신하지 않는다. 승인받은 임시 실험 범위는
진단 앱 쓰기/검증→합성 진단1회→같은 슬롯 원본 복구/검증→출고 복귀 관찰이다.
이 범위의 쓰기2회와 재부팅 요청을 마쳤고, 이후 사용자가 새 화면 복귀를 확인했다.
각 쓰기 전에 포트/칩/보호 상태/원본 표·OTA를 재검증했다. 이 값이 달라지면
중단한다. write/verify 실패나 brownout 시 자동 재시도·다른 슬롯 쓰기는 하지 않는다.

근거: [고정 SDK loader](https://github.com/espressif/esp-sr/blob/2f8c4b0459db5bbb39abd77adae27962d6d94bcb/src/model_path.c),
[K151 공식 Quad PSRAM 사양](https://docs.m5stack.com/en/StackChan),
[원본 복구 절차](K151_BACKUP_RECOVERY.ko.md).
