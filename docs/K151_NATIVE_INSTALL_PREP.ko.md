# K151 native wake 설치 전 검토 자료

## 2026-11-28 재부팅·연속 대화·STOP 통합 시험 준비

현재 판정은 **통합 실물 시험 설치 보류**다. `f275cdf`는 예산
복구 수정이 포함된 비활성 검토 이미지다. 같은 기기에서 한 턴을
확인한 재생 및 STOP 기록은 한 턴 정책에 묶여 있다. 현재 연속 대화
정책은 전원 레일, 리셋 순서, 앰프 음소거, STOP 지연과 DMA·코덱 유휴
근거를 확인해야 시작한다. 계측기 없이 직접 듣고 화면을 보는 단계는
기능 확인에 사용하며, 해당 근거를 대신하지 않는다.

한 번의 임시 설치로 확인할 순서는 아래와 같다.

1. 로봇에 설정을 암호화해 저장한다. 기존 시험에서 NVS를 복구했으므로
   이번에는 재부팅 전에 합의한 짧은 질문으로 비어 있지 않은 예산
   기록을 만든다. 예약이 확인된 시점의 기록을 기준으로 잡는다.
2. 전원을 껐다 켠 뒤 USB 없이 로봇에서 잠금을 해제한다. 새 요청 전
   앞 단계의 예산이 그대로 로드되고 다시 초기화되지 않았음을
   확인한다. 검토용 기록은 일치 여부만 남긴다. 기록을 읽을 수
   없으면 네트워크를 시작하지 않는다.
3. 화면의 유료 대화 동의를 거쳐 첫 응답을 끝까지 듣고 호출어 대기로
   돌아오는 것을 확인한다. 두 번째 답변이 나오는 동안 앞면을 한
   번 터치한다. 재생이 멈추고 새 요청 없이 종료 상태가 유지되어야
   한다. 같은 60초 구간에 세 예약이 겹치지 않도록 기존 분당 제한을
   적용한다.
4. 성공, 중단, 시간 초과 모두 같은 복구 절차를 쓴다. 같은 보드와
   파티션 표·OTA 데이터를 다시 확인하고 OTA1 원본과 **그 시험 직전**
   NVS를 차례로 복원한다. 각 범위를 독립 검증하고 표·OTA 데이터를
   다시 대조한 뒤 순정 부팅과 얼굴 화면을 확인한다. 복구 검증 실패
   때는 완료 처리나 재시험 없이 해당 복구 단계에 머문다.

검토 범위는 재부팅 전 한 턴과 뒤 두 턴이다. 한 턴당 질문 음성
최대 8초를 STT로 보내고, 전사 텍스트를 GPT로, 답변 텍스트를 TTS로
보낸다. 최대 세 턴·아홉 요청 단계이며 중간 STOP 뒤에는 호출을
재개하지 않는다. 기존 한 턴 실행기의 승인은 사용 범위가 다르다.

통합 시험의 예산 가드는 기존 예산과 시험 ID·단계·누적 횟수를
같은 NVS 레코드에 저장하도록 구현했다. 첫 부팅은 검토한 기존
예산 또는 별도로 승인한 최초 생성을 거쳐 한 턴을 갖는다.
재부팅은 첫 응답 뒤 대기 복귀가 확인되고 검토한 예산이 일치할
때 한 번만 다음 단계를 연다. 두 번째 부팅의 시작도 새 요청 전에
저장·재읽기한다. 저장 결과 불확실, 기록 누락·손상, 잘못된 시험 ID,
예정 밖 재부팅은 새 유료 요청을 막는다. 소비한 횟수는 롤링
예산 창이 지나도 초기화되지 않는다.

통합 시험 모드는 첫 설정에서 한 턴을 화면으로 승인받는다. 첫 답변
뒤 대기 복귀를 확인하고 마이크·스피커·모델·네트워크를 닫는다.
STOP 감시를 유지한 채 시험 ID와 당시 예산을 `sc_gpt/trial_ckpt`에
별도로 저장·재확인하고 재부팅 안내를 표시한다. 화면 표시가 실패하거나
그때 STOP이 들어오면 다음 부팅을 열지 않는다.

다음 부팅은 저장한 설정을 잠금 해제하고, 앞의 안내를 본 사람이
화면에서 두 턴을 새로 승인하는 절차다. 별도 저장한 예산과 현재
시험 예산을 바이트 단위로 비교한다. 권한을 다시 저장·검증하고
화면에 예산 확인을 표시한 다음 네트워크를 시작한다. 과거 한 턴
기록은 이 모드의 연속 재생 조건을 충족시키지 않는다.

실물용 통합 시험 이미지를 검토하고 설치·복구하는 실행기는 남아
있다. 통합 모드에는 별도 빌드 표시를 두었고, 기존 한 턴 검토기는
이 표시가 포함된 이미지를 거부한다. 공개 검토 이미지는 비활성이다.

기존 A/B와 한 턴 시험 직전 사본을 읽기 전용으로 검증했다.
`f275cdf` 검토 이미지 1,919,120바이트를 RAM의
`[0x510000, 0x6E4890)`에 배치했으며 지움 범위 끝은
`0x6E5000`이다. 설치 중단, 실행 중 NVS 변경, OTA1 복구 중단,
NVS 복구 중단 네 상황에서 OTA1 `[0x510000, 0xA00000)`과 NVS
`[0x9000, 0xD000)`를 복원해 기준 전체 이미지와 대조했다.
현재 실물의 설치 전 상태는 승인된 준비 단계에서 별도로 확인한다.
[원본 백업과 복구 근거](K151_BACKUP_RECOVERY.ko.md)

호스트에서 재부팅 기준 예산의 바이트가 첫 요청 전까지 그대로이고,
두 번째 답변의 재생 중 STOP 뒤에도 예약 세 건을 유지하는 것을 확인했다.
STOP 뒤에는 새 요청이나 새 예산 쓰기가 없었다. 설정, 대화, 유료 한 턴
실행기의 승인·복구 관련 오프라인 시험 235개를 통과했다.

최신 [오디오 I/O 코드 보강](K151_AUDIO_IO.ko.md)은 오프라인 작업이다. PCM 짧은
대기·exact count·반환 후 시간 검사와 지움을 추가했으며, 새 실물 설치/음성/API
승인 요청용 운영 이미지가 아니다. 운영 HOLD와 전원/mute/STOP 제약을 유지한다.

후속 [보드 readback](K151_BOARD_READBACK.ko.md)은 사용자 승인 뒤1회 실행·완료했다.
원본 slot1 복구·독립 verify·표/OTA 일치와 사용자 얼굴/메뉴 복귀를 확인했다.
[최신 실물 범위·증거](validation/2026-11-21-k151-board-readback-live.md)를 우선한다.
운영 앱 HOLD를 유지하며, 아래 준비·미승인 문구는 그 이전 단계의 이력이다.

2026-11-21 승인 후속: **운영 앱의 HOLD는 유지**한다. 별도 검토한 무음 진단 앱만
1회 임시 설치해 실물 모델 추론/동시 PCM 배치를 확인한 뒤 원본slot1을 복구했다.
장치의 독립 verify와 표/OTA 전후 일치가 PASS이며, 뒤의 보드 조회 승인 전 사용자가
이 모델 진단 복구 뒤 화면 복귀도 확인했다.
[실물 이미지·쓰기/복구 범위·실측](validation/2026-11-21-k151-silent-resource-bench.md)을 우선한다.
아래의 미설치/복구 미실행 문구는 그 전 준비 단계의 이력이다. 전체16MB 복구와
실제 호출어/질문/TLS/재생/STOP/독립 GPT 및 운영 readiness는 여전히 미검증이다.

2026-11-20 Windows 인수. **현재 설치 패키지는 HOLD이며 쓰기 승인 요청 단계가 아니다.**
같은 `feat/wakeword-josu` / PR #3에서 기존 모듈을 연결한다. 원본/개인 프로필/키는
배포하지 않는다. [인수 검증](validation/2026-11-20-windows-handoff.md)을 함께 본다.

사용자 재연결 후 현재COM3/S3/16MB/보호 OFF와 표/OTA12KiB의 원본 일치를 확인했다.
장치의 readonly DATA model partition 전체 SHA를 사용하는 `prepare_local`도 휴면
연결했다. [후속 조회·코드 검증](validation/2026-11-20-k151-current-usb-and-assets.md)을 따른다.
현재 원본 표에는 model partition이 없으며 새 펌웨어/모델을 쓰지 않았다.

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

휴면 `prepare_local(owner,stop)`은 draft0xF00000/1MiB의 main-flash·DATA·model·readonly·
unencrypted를 확인한 뒤 IDF 전체 파티션 SHA를 비교한다. pack 뒤0xff padding을 포함한
SHA는 `1d04bf6a1f6775d43ab4398bbbac1bc4606f5c4130fe1a853851ec5df7f21d1b`다.
검증 실패는 같은 객체의 legacy bool 진입으로도 우회할 수 없다. 로컬 소유자 UI 및
실제 메모리 admission은 여전히 필요하며 실제 SHA 호출은 장치에서 실행하지 않았다.

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
