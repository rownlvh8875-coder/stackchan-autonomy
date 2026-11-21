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
시작 뒤10초 제한과 기존 직접 추론 단계의 최대64개 chunk를 적용한다. 별도 reader task가 동의를
취소하며, 이미 실행 중인 SDK 동기 호출을 강제 선점하지는 못한다.
이는 로컬 실험자의 명시적 시작이며 인증된 사용자 신원이나 운영 STOP 증거가 아니다.

기존 실물 실행의 측정 대상은 실제 model context 전후의 capability별 free/largest/minimum heap,
동시 질문384000bytes/TTS960000bytes vector의 실제 PSRAM 배치, 합성 무음
64chunk의 최대 detect 시간/100ms 초과 수다. 모델 flash 길이를 RAM으로
환산하지 않는다. PCM은 기존 volatile wipe를 재사용한다. TLS/JSON/네트워크와
codec/DMA 동시 부하는 **미측정**, operating_admission은 항상false다.
64chunk 완료도 실제 호출어 인식이나 GPT 대화 성공이 아니다.

후속 빌드는 모델과 8초 질문 버퍼가 살아 있는 동안 256KiB 합성 JSON과
960,000바이트 합성 speech body를 기존 `BoundedReply`와 `K151VoiceDecoder`에
차례로 공급한다. `model_question_wire_and_decoded_pcm` 단계에서 raw body와
디코딩한 960,000바이트 PCM이 동시에 살아 있다. 이때 세 버퍼의 본문 합계는
2,304,000바이트다. 실제 heap 수치에는 allocator와 모델이 함께 반영되며,
`body_capacity_bytes`와 `decoded_pcm_capacity_bytes`로 실제 vector capacity를
따로 출력한다. JSON 단계의 minimum은 decoder 안의 임시 할당도 포함하는 누적
watermark다. 모든 입력은 메모리에서 생성한 합성 데이터이고 USB에는 수치만 출력한다.
기존 64chunk 합성 추론에는 디코딩 PCM과 질문 버퍼를 계속 유지한다.

WakeNet 입력 후속은 직접 추론 뒤 모델을 초기화하고, 메모리에서 만든
24kHz 무음 10ms 프레임 32개를 추가로 처리한다. 운영 컨트롤러와 같은
FIR과 chunk 누적을 사용하며, 입력 단계 최대 처리 시간과 완료 여부만
출력한다. 모델 입력 형식 변경, 동의 철회, STOP 또는 무음에서 감지가
발생하면 해당 단계는 실패다. 이 단계의 24kHz는 합성 PCM 형식이며
실제 장치 마이크의 입력 증거는 별도 실물 시험으로 확인한다.
[공통 입력 검증](validation/2026-11-21-k151-silent-wake-input.md)

승인한 후속 실물 실행에서는 `synthetic_inference` 뒤 두 번째 시작 대기
메시지가 들어왔다. 수신기가 STOP으로 끝냈고 새 입력 단계 완료는 확인되지
않았다. 같은 슬롯을 복구·검증했고 사용자가 출고 얼굴·메뉴의 복귀를 확인했다.
[실물 중단·복구 기록](validation/2026-11-21-k151-silent-wake-input-live.md)

후속 계측은 시작 메시지에 ESP-IDF reset reason을 넣고, 모델 reset과
입력 버퍼 준비, 첫 poll·detect 및 마지막 reset의 경계를 기록한다.
첫 detect의 checkpoint 출력 비용은 `max_poll_us`에 포함되며, 결과의
`checkpoint_latency_included` 필드로 표시한다. 기존 직결 64개 모델 chunk의
`max_detect_us`는 해당 checkpoint의 영향을 받지 않는다.
[reset 계측과 수신기 범위](validation/2026-11-21-k151-wake-reset-telemetry.md)

승인한 계측 1회에서 두 번째 시작 메시지의 reset reason은 panic이었다.
마지막 수신 경계는 `model_reset_begin`이며 `model_reset_return`은
수신되지 않았다. 원본 슬롯 복구와 검증을 완료했고 사용자가 출고
얼굴·메뉴 복귀를 확인했다.
[reset 경계 실측 기록](validation/2026-11-21-k151-wake-reset-panic-live.md)

후속 reset 구현은 기존 컨텍스트를 먼저 파기하고 검증된 같은 모델 목록에서
새 컨텍스트를 생성한다. 이 경로에서 SDK `clean()`을 호출하지 않는다.
기존 경계 계측은 새 컨텍스트의 reset 반환과 합성 32프레임 완료를 별도로
관측한다. 생성·해제 비용과 실물 안정성은 후속 실행에서 확인한다.
[reset 변경의 검증 기록](validation/2026-11-21-k151-wakenet-recreate-reset.md)

승인한 후속 이미지의 실물 실행은 두 reset과 24kHz 합성 32프레임을
완료하고 HOLD에 도달했다. 직결 64개 chunk의 최대 추론은 7.241ms,
checkpoint 출력이 포함된 합성 입력 최대 poll은 9.006ms였다.
원본 슬롯 복구와 독립 digest를 검증했다.
[새 컨텍스트 실측·복구](validation/2026-11-21-k151-wakenet-fresh-context-live.md)

실물 검증한 `f4878fa` 이미지는 HTTP 본문 처리까지 실행했다. 이후 TLS 후속은
고정 SDK의 Mbed TLS 1.2 클라이언트와 서버를 각각 1KiB의 메모리 FIFO로
연결한다. 실행 때만 존재하는 PSA CA와 leaf를 사용해 인증서 체인과
`bench.stackchan.invalid` 이름을 검증한다. 작은 암호화 레코드 수신을 확인한
뒤 두 TLS 객체가 살아 있는 동안 기존 합성 JSON·PCM 진단을 실행한다.
HTTP 합성 본문은 메모리에서 기존 receiver로 공급한다.

`model_question_before_local_tls`와 `model_question_local_tls_established`는
모델과 질문을 고정한 상태에서 연결 전후를 기록한다.
`model_question_tls_wire_and_decoded_pcm`에서는 speech 원본과 변환 PCM
및 두 TLS 객체가 함께 살아 있다. minimum 값은 해당 측정 단계까지의 누적
watermark다. 이 결과에는 인프로세스 서버와 FIFO 비용도 들어간다.
운영 CA bundle, 실제 피어의 인증서 체인, Wi-Fi와 OS 소켓, 실제 codec/DMA는
별도 측정 대상이다. `local_tls12_peer_verified`와 `tls_measured`를 별도 필드로
기록하고 운영 admission은 false로 보고한다. 후속 이미지의 실물 실행은 승인
이후 한 번 완료했고 [메모리 TLS 실측과 원본 복구](validation/2026-11-21-k151-local-tls-live.md)에
범위와 수치를 기록했다.

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
