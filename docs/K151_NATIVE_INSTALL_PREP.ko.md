# K151 native wake 설치 전 검토 자료

2026-11-20 Windows 인수. **현재 설치 패키지는 HOLD이며 쓰기 승인 요청 단계가 아니다.**
같은 `feat/wakeword-josu` / PR #3에서 기존 모듈을 연결한다. 원본/개인 프로필/키는
배포하지 않는다. [인수 검증](validation/2026-11-20-windows-handoff.md)을 함께 본다.

## 준비한 자산과 배치 제약

공개 ESP-SR commit `2f8c4b0459db5bbb39abd77adae27962d6d94bcb`의 모델 파일 3개를
로컬에 공급하고 각각의 고정 SHA256, 길이, pack header/offset, 최종 SHA를 검증했다.
`prepare_wakenet_assets.py`는 로컬 파일만 읽고 출력은 새 파일로만 생성한다.

| 자산 | 길이 | SHA256 |
|---|---:|---|
| wn9l_histackchan_tts3 model pack | 292607 | `0255855e56bf72d1e072d2e0cbee4fb3ce1ac2c48f7fee6c8cd591f83e59ed95` |
| 원본 factory-a.bin / factory-b.bin 각각 | 16777216 | `c1241a7c87145ee8b9569cfbcfbb1f8c289641856f9b9b5ddf2ccd565019543e` |

모델 pack의 로컬 준비는 **장치 partition의 무결성 검증이 아니다.**
K151WakeNetPort::prepare의 owner/assets_verified 입력에 이 사실을 대신 넣지 않는다.
운영 bootstrap은 실제 로컬 소유자 동의, 장치에서 읽은 model partition SHA,
동적 메모리 증거를 각각 공급해야 한다. SDK global loader는 다른 직접 사용자가
없어야 하며 한 live adapter만 소유한다. 정확한 model/mode/rate/chunk 검사는 유지한다.

원본 파티션 표는 다음과 같이 재검증했다. **변경된 offset/길이는 모두 0**이다.

| 영역 | 시작 offset | 길이 bytes |
|---|---|---:|
| partition table | 0x8000 | 4096 (table sector) |
| nvs | 0x9000 | 16384 |
| otadata | 0xD000 | 8192 |
| phy_init | 0xF000 | 4096 |
| ota_0 | 0x20000 | 5177344 |
| ota_1 | 0x510000 | 5177344 |
| assets | 0xA00000 | 4194304 |
| coredump | 0xE00000 | 65536 |

전용 model 영역 후보는 `0xF00000..0xFFFFFF`(1048576bytes)다. 원본 표의 영역과
겹치지 않고 **검증한 과거 백업에서만** 전부 0xFF임을 확인했다. 실제 현재 빈 공간,
제조사 hardcoded 사용 여부, write safety를 입증하지 않는다. 이를 사용하려면
새 partition table과 그에 맞는 app의 별도 검증/승인이 필요하다. 현재 sdkconfig의
IDF 기본 표나 flash 예제는 실물에 적용할 수 없다. 후보 CSV/bin은 설치 파일로 발행하지 않는다.

원본 otadata는 seq1/seq2 모두 VALID·CRC 정상으로, 고정 IDF의 rollback ON/OFF
두 해석 모두 `ota_1`을 선택 후보로 가리킨다. seq_label은 출력하지 않았다.
현재 실행 슬롯은 제조사 bootloader 설정·이미지 검증/fallback·이후 업데이트의
영향을 받을 수 있다. **ota_1은 빈 슬롯이 아니며 어느 쪽도 안전한 spare로 승인하지 않는다.**

## 운영 연결과 남은 증거

`NativeVoiceLoop`는 이미 준비된 model/audio와 기존 NativeWakeController,
VoiceTurnCoordinator를 단일 owner task에서 직렬로 연결한다. wake mic를 종료한 새
epoch만 질문으로 넘기고, 재생 뒤 cooldown에서 새 wake capture로 돌아간다.
cloud enable을 호출하지 않으며 STOP/동의 철회/readiness 상실/오류는 종료 latch다.
app_main은 이를 생성하지 않고 기존 HOLD를 유지한다.

확장 메모리 admission은 실제 model이 살아 있는 동안의 capability별 free/largest
block, 실제 PCM allocator의 PSRAM 배치, 질문+TLS/JSON+TTS의 동시 peak를 요구한다.
model flash bytes나 HOLD 앱의 정적 크기로 model RAM을 추정하지 않는다. 실제 값은
아직 없으므로 장치 admission은 미충족이다. 큰 snapshot flag를 외부에서 임의로
설정하는 경로는 추가하지 않았다. 모델 이후 free에서 내부32KiB/PSRAM128KiB 여유와
기존 보수적 PCM 예산을 모두 확인하며 이 정책 자체는 실측/설치 승인 증거가 아니다.

실물 전 남은 작업은 장치 model partition 공급/읽기 SHA 검증, allocator 배치와
model/TLS 동시 실측, 독립 STOP-to-mute·전원/reset·TX DMA drain 관측, 실제 K151
mic timing과 추론 chunk/지연이다. 현재 codec의 output enable과 drain은 여전히
hard HOLD다. 100ms/chunk160..2048을 실물 근거 없이 완화하지 않는다.

## 원본 복구 명령 초안 (미실행)

복구 범위는 같은 기기의 전체 `[0x0,0x1000000)`다. bootloader/partition/NVS/
OTA 앱/assets/coredump를 과거 백업 상태로 되돌리므로 이후 설정/계정 변경도
되돌아갈 수 있다. eFuse·서보 controller·서버 데이터는 복구하지 않는다.
다른 저장장치 사본과 실제 복구 쓰기는 아직 미검증이다.

실제 복구가 승인된 경우에만, 재조회한 VID303A/PID1001 포트·같은 칩/용량·보호 상태와
두 백업 SHA를 확인하고 다른 GPT/serial 프로그램을 종료한 뒤 사용할 명령 형태다.
`COM_CONFIRMED`는 현재 검증한 실제 포트로 바꾸기 전에는 실행할 수 없는 자리표시자다.
esptool 5.6.0의 아래 옵션은 **로컬 --help만** 조회해 확인했다.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" tool run --from esptool==5.6.0 esptool --chip esp32s3 --port COM_CONFIRMED --before no-reset --after no-reset --no-stub --connect-attempts 1 write-flash --flash-mode keep --flash-freq keep --flash-size keep 0x0 "%USERPROFILE%\stackchan-soak-24h\.local\device-backup\k151-original-20261118-01\factory-a.bin"
```

ROM Download Mode와 조회를 먼저 확인해야 한다. 포트를 여는 동작은 PnP 조회와 다르다.
기본 verify-flash는 차이 내용을 표시하는 `--diff`를 사용하지 않는다.

```cmd
"%USERPROFILE%\.local\bin\uv.exe" tool run --from esptool==5.6.0 esptool --chip esp32s3 --port COM_CONFIRMED --before no-reset --after no-reset --no-stub --connect-attempts 1 verify-flash --flash-mode keep --flash-freq keep --flash-size keep 0x0 "%USERPROFILE%\stackchan-soak-24h\.local\device-backup\k151-original-20261118-01\factory-a.bin"
```

포트/칩/보호/해시 불명, 연결·write·verify 실패, brownout, 출력 불확실이면 중단한다.
자동 재시도·erase-all·force·보호 우회·eFuse 조작을 사용하지 않는다. 검증 뒤에만
정상 부팅/기존 기능 복귀를 별도로 확인한다. 복구 성공을 현재 확인한 것으로 기록하지 않는다.
새 펌웨어 설치 명령은 운영 이미지·SHA·정확한 변경 sector 영향과 복구 조건까지
확정한 manifest를 만든 뒤 실제 쓰기 승인을 요청할 때 제시한다.

## 실제 API 한 턴 시험 준비 범위

현재 cloud OFF, 실제 요청 0이다. 별도 승인 시 전송할 범위는 새 질문만 최대8초
24kHz mono PCM16(384000bytes + WAV/multipart), STT 전사 최대500자, GPT 답변 최대300자,
TTS 요청은 그 답변, 수신 재생 PCM은 최대20초/960000bytes다. 호출어 음성·개인 등록
특징·이미지·원본 flash는 이 요청에 포함하지 않는다. 새 실음성 파일 저장도 별도 승인 대상이다.

한 턴은 STT/GPT/TTS 각 최대1회, 총3개 유료 요청을 저장 예산에 선차감한다. 일부
실패도 이미 발생한 비용을 환불로 처리하지 않고 자동 재전송하지 않는다. 실제 모델/계정은
아직 선택·승인되지 않았으므로 금액 상한은 미정이다. 시험 전 정확한 3모델/voice,
당시 공식 분당/입출력 token 또는 문자 요율, GPT token 상한 및 1턴 비용 상한을 계산해
전송 범위와 함께 제시해야 한다. 이 자료만으로 유료 시험을 승인한 것으로 취급하지 않는다.
