# K151 보드 조회1회·원본 복구 실물 기록

2026-11-21, Asia/Seoul. 사용자가 이전 복구 뒤 출고 화면 정상을 확인하고
**“정상이야 다음단계진행해”**로 검토한 보드 조회·같은 슬롯 원본 복구를 승인했다.
진단을 한 번 실행하고 원본을 복구·검증했다. 이번 재부팅 뒤에도 사용자가
**“얼굴/메뉴가 돌아왔어요”**로 출고 화면 복귀를 확인했다.
[sanitized 증거](2026-11-21-k151-board-readback-live.json),
[준비 단계](2026-11-21-k151-board-readback-preflight.md), [조회 범위](../K151_BOARD_READBACK.ko.md).

## 실제 실행·복구

이미지 코드 `36c4e98ed1b41aa04e80c7d662986649f29259e5`, 실제 CI checkout
`c991ec9523d6a82c6908c9aa4bade5b8fdb62991`, app version `c991ec9523d6`.
185744bytes, SHA256 `128969c002b9b1242679baf1658b66951fe7c7c076b00e573dd221d34ff5aa17`인
검토 이미지 그대로 사용했다. 이후 문서 커밋의 다른 산출물로 바꾸지 않았다.

COM3/303A:1001 PnP 조회 후 알려진 직렬 통신 프로그램이 없음을 확인했다.
같은 칩 식별은 로컬에서 비공개 비교했고 S3rev0.2/16MB/Secure Boot·Encryption OFF,
현재 table/OTA 원본 일치와 원본 slot1 전체 digest 일치를 쓰기 전에 확인했다.
원본 A/B·별도 디스크 사본·복구 slice·app의 길이/SHA를 재검증했고 slice와 원본
`[0x510000,0xA00000)`의 실제 byte 일치도 확인했다. 전체16MB를 다시 읽지 않았다.

| 작업 | 실제 범위·결과 |
|---|---|
| 임시 app 쓰기 | `[0x510000,0x53D590)`,185744bytes,3.936s, 내부 digest+독립 verify PASS |
| 실제 erase | `[0x510000,0x53E000)`,188416bytes/46sector; 마지막2672bytes 포함 |
| 일회 조회 | actual running_offset `0x510000`, size5177344, chip9/revision2 확인 뒤 fresh START1회 |
| 완료 | READBACK_COMPLETED,7142µs, 이어 HOLD_UNTIL_RESET; reader 총0.0728s |
| 원본 복구 | `[0x510000,0xA00000)`,5177344bytes,85.838s, 내부 digest+독립 verify PASS |
| 표·OTA | prewrite/postbench/postrestore 세 시점 byte 일치, raw metadata 총36864bytes 로컬 보관 |
| 출고 복귀 | 명시적 재부팅 요청 성공·COM3 재조회·사용자 얼굴/메뉴 복귀 확인 |

flash write 명령2회, 명시적 reset4회다. esptool5.6.0의 no-stub/connect-attempts1과
flash-mode/freq/size keep을 사용했다. 실제 erase 범위도 두 쓰기의 로컬 로그에서
대조했다. 생성 bootloader/table/ota_data_initial이나 IDF 기본 flash 예시는 쓰지 않았다.
원본 복구 slice SHA256 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`,
원본 A/B·별도 디스크 사본 각16777216bytes 공통 SHA256
`c1241a7c87145ee8b9569cfbcfbb1f8c289641856f9b9b5ddf2ccd565019543e`.
원본·raw metadata·원시 앱 serial·nonce·비밀은 업로드하지 않았다.

## 실제 관측값과 해석 범위

ACK 순서는 PMIC0x34/IO0x58/touch0x38/mic0x40/amp0x36이며 모두1이다.
모든 조회 그룹의 valid=1, SDK bus cleanup을 포함한 observe_once 성공이다.

| 조회 | 실제 값 (hex) |
|---|---|
| AXP2101 ID0x03 | `4A` |
| PMIC0x90/94/95/97/99 | `BF / 1C / 1C / 1C / 1A` |
| AW9523 ID0x10 | `23` |
| AW9523 output0x02..03 | `07 / 83` |
| AW9523 direction0x04..05 | `18 / 0C` |
| FT6336 version0xA3..A8 | `64 / 01 / 01 / 12 / 00 / 11` |

PMIC/IO ID와 설정 레지스터를 읽은 증거다. 핀 전압·전원 순서·reset 파형·앰프
mute·DMA drain·physical STOP 증거는 아니다. IO의 두 번째 output은 제조사 소스의
초기 설정0x8F와 관측0x83이 다르므로 초기값을 실제 현재 값으로 대신하지 않는다.
touch 패턴은 기존 parser의 ILI9342E candidate에 해당하지만 LCD 확정은 아니다.
이번 진단의 실행 slot1은 실제 getter로 확인했고 safe spare로 판정하지 않는다.
원본 복구 후 factory 앱의 running getter 자체는 관측하지 않았다.

GPIO12/11 mux와 고정 I2C register-pointer/read만 실행했다. 진단의 장치 설정값 쓰기,
mic/I2S·speaker·model·NVS·Wi-Fi/API startup, 새 실음성 저장/전송은0이다. 명시적
NVS/table/otadata/eFuse 쓰기와 RAM stub/전체flash 복구/진단 재시도도0이다.
출고 펌웨어가 재부팅 뒤 내부적으로 수행하는 저장 동작은 별도로 관측하지 않았다.

## Mock·빌드·실물 결과 분리

실행 코드36c4e98은 host root495PASS2SKIP/standalone550PASS5SKIP와 실제 S3 build PASS,
CI **8/9**다. PR Windows3.11 heartbeat의 StateUnavailable는 미해결로 보존한다.
뒤의 문서 head **e13124f도8/9**다: [push44845779127](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44845779127)4/4,
[PR44845785204](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44845785204)3/4,
[S3 44845784950](https://github.com/rownlvh8875-coder/stackchan-autonomy/actions/runs/44845784950)1/1.
이 문서 커밋의 Windows3.11 job136665029854는 STOP 시험에서 첫 명령의 entered.wait()1초가
만료됐다. **STOP 호출 전**의 실패이며 root494PASS/1FAIL/2SKIP163.98s, virtual soak
전에 실패했다. heartbeat 실패와 다른 지점이고 원인은 미확정이다.

노트북에서 이 두 실패 시험을 각각 한 번 계측해2PASS/3.88s였다. heartbeat는
COMMITmax3.0861ms/loop lag18.2599ms, STOP 시험은 COMMITmax3.8772ms/loop lag2.0306ms,
interruption은 모두0으로 CI 실패를 재현하지 못했다. pytest 플러그인의 assert rewrite
warning1개가 있었다. 이 로컬 통과로 CI를 green 처리하지 않았다. 실패 job 재실행,
timeout/lease/내구성/검사 변경은0이다. 현재 문서 커밋 CI는 별도로 확인한다.

실물 조회·복구 성공은 실제 호출어 인식·질문/VAD·STT/GPT/TTS·로봇 음성 재생 성공이
아니다. 운영 app_main은 HOLD, cloud OFF와100ms/chunk160..2048을 유지한다.
다음 코드 과제는 codec1.6.2의1000ms 대기/short count·오류 후 PCM wipe를 보호하는
bounded I/O 연결이다. 그 뒤 실제 audio ownership/STOP/drain과 TLS 동시 peak를
확인해야 한다. 과거 레지스터/메모리 기록으로 owner/assets/readiness를 true로 넣지 않는다.
