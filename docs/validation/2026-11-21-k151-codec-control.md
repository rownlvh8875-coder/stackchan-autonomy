# K151 codec control 오류 전달 — 실물 미적용

2026-11-21, Asia/Seoul. 기준30da931345120f78161e23b0f87122459562e1d4의
같은 feat/wakeword-josu/PR3 후속이다. [설계·범위](../K151_AUDIO_IO.ko.md),
[계획](../superpowers/plans/2026-11-21-codec-control-errors.md).

기존 SDK의 ES7210 update_reg_bit는 register read 오류를 버린다. gain API와
close 역시 일부 하위 반환값을 버린다. 비소유 control observer가 원래 SDK
pointer/프로토콜을 그대로 전달하며 이 오류를 별도로 latch한다. 초기화/open/gain/
close/codec 해제 뒤 독립 검사하고, 오류 후 PCM·재시작을 차단한다. cleanup은
허용하되 나중의 성공이나 detach로 fault를 지우지 않는다. analog mute 증거는 아니다.

## 재현과 검증

- null data callback 5개는 기존 코드에서 Windows 접근 위반3221225477로 RED였다.
  방어 뒤 false/INVALID_ARG, bounded read wipe/write 원본 유지와 무I/O를 확인했다.
- I2S get_info 실패 주입은 기존 처리의 회귀다. best-effort disable이 성공해도
  shutdown은 false이고 반복 shutdown 뒤에도 fault가 남는다. 이 코드는 변경하지 않았다.
- 초기화(out/in)·open·gain·close·해제의 read/write 오류12개를 실제 포트+C ABI
  double에 주입해 모두 RED로 확인한 뒤 observer를 연결했다.
- 고정 SDK1.6.2 archive SHA/원문 SHA를 유지한 ES7210 C를 **C로 별도 컴파일**해
  실행했다. 원문은 read 오류 뒤 성공을 반환하며, observer가 이를 잡는다.
  write 오류·null callback·base 상실·fault 뒤 cleanup도 검사한다. 물리 register
  I/O만 double이며 실제 장치 시간/전압/DMA를 재현하지 않는다.
- 집중 codec56PASS3.08s, 전체 root495PASS2SKIP90.41s, 선택 NumPy/cryptography 포함
  standalone615PASS5SKIP104.79s. Zig0.15.2/Clang20.1.2 -O2 assertions ON이다.
  Ruff/format360files와 owned-source diff 검사를 통과했다. 원문 vendor whitespace를
  임의 수정하지 않고 SHA 및 Windows Git checkout 바이트 보존 시험으로 확인한다.
- 단일 fresh 독립 검토 Critical/Important0. Minor인 AW88298의2바이트 register
  값을 host double로 검사하는 회귀는 후속이다. 현재 production observer는 길이를
  그대로 전달하지만 output double은1바이트이므로 이 회귀를 대신하지 않는다.
- SDK control destructor가 버리는 하위 device-removal 반환값은 register observer
  범위 밖이며 남아 있다. 이후 bus 삭제 실패는 검사한다. 성공을 물리 release/mute
  증거로 해석하지 않는다. 실제 target ABI는 CI에서 별도로 확인해야 한다.
- 해당 새 commit의 실제 target/전체 CI는 이 사전 기록에서 미실행 상태다.
  결과는 [PR3/checks](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)에서
  exact head와 연결한다. [기계 판독 사전 기록](2026-11-21-k151-codec-control.json).

## 제한과 상태

HOLD app_main/물리 출력 false/drain=false/cloud OFF를 보존한다. 기존 owner/assets/
power admission을 우회하지 않으며 SDK 모델 단일 소유권, PCM wipe, STOP/resume
경계와100ms gap/chunk160..2048은 유지한다. 이번 새 기기 접근·리셋·I2C·flash·
실제 음성 저장/전송·유료 API는 모두0이다. 장치는 마지막 사용자 확인상 원본 복구와
얼굴/메뉴 복귀 상태이며 이번 코드가 설치된 것이 아니다.

실제 mic 채널·물리 STOP/mute/drain·제어 동기 지연·질문/TLS/TTS 동시 peak와
실물 Hi StackChan/독립 GPT 대화는 미검증이다. Windows COMMIT 지연의 물리I/O와
OS 비실행 시간도 미분리다. 기존 실패job 재실행/timeout·lease 완화·검사 생략은 없다.
이전30da931의9/9나 이번 host 성공으로 과거 실패가 해결됐다고 해석하지 않는다.
