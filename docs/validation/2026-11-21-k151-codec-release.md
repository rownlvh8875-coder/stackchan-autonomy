# K151 driver 해제 후속 — 실물 미적용

2026-11-21, Asia/Seoul. 기준4829b33a9c20795af066a3ee96fb211d66c55de6의
같은 feat/wakeword-josu/PR3 후속이다. [계획](../superpowers/plans/2026-11-21-codec-release-ownership.md),
[오디오 범위·원본 소스 링크](../K151_AUDIO_IO.ko.md).

## 변경과 재현

기존 shutdown은 disable/delete 실패 뒤에도 raw RX/TX handle을 비워 정리할 대상을
잃었다. 실제 포트+C ABI double에서 RX/TX/both/상태조회 실패를 포함한4개 시험이
RED였다. 이제 삭제 성공 때만 pointer를 비우며, 다음 명시적 shutdown에서 남은
채널을 한 번씩 시도한다. 이미 해제한 자원은 재접근하지 않는다. PCM은 계속 차단·
wipe하며 나중의 정리 성공으로 fault나 반환 false를 지우지 않는다.

초기 계획의 bus 보존은 고정 IDF 감사 뒤 채택하지 않았다. i2c_master_bus_destroy는
wrapper를 free한 뒤에도 pin 정리 오류를 반환할 수 있다. 반대로 interrupt 정리나
device 잔류로 free 전에 실패할 수도 있다. 반환값만으로 재접근 여부를 결정할 수
없어 기존 no-reaccess/fault를 유지했다. 두 bus 결과의 주입 시험은 baseline PASS인
회귀이며 이를 새로 해결한 문제로 세지 않는다. 아직 살아 있는 bus 회수는 미해결이다.

지난 검토의 AW88298 두 바이트 gap을 보완했다. 원래 control에 전달되는 register
주소/길이/두 바이트 read/write 값과 canary를 검사한다. read/write를 각각 한 바이트로
자른 임시 source 사본은 실제 boundary assertion에서 실패한다. production source를
시험 중 수정하지 않았다. ES7210의 한 바이트 경로와 원문 SDK SHA는 보존한다.

집중 codec66PASS11.20s, 전체 root495PASS2SKIP92.89s, 선택 NumPy/cryptography 포함
standalone625PASS5SKIP103.07s. Zig0.15.2/Clang20.1.2 -O2 assertions ON이다.
Ruff/format·owned diff PASS, 원문 SDK15파일 archive byte 일치와 checkout SHA를 확인했다.

단일 fresh 검토의 Important1은 시험 double의 GCC misleading-indentation 가능성으로
줄을 분리했다. 형식만 바꾸며 GCC 경고 자체를 로컬에서 재현한 것은 아니다.
실제 GNU 컴파일은 CI에서 확인한다. Minor인 오래된 계획의 bus 보존 문장도 고쳤다.
운영 cleanup의 추가 Critical/Important는 없으며 물리 mute/drain/recovery는 검토 범위
밖이다. 형식 보강 뒤 집중66PASS를 재확인했다.

이 사전 기록의 새 head 실제 CI는 아직 미실행이며,
[PR3/checks](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3)로 exact head와 연결한다.
직전4829b33 CI9/9는 새 변경의 결과가 아니다. 실패job을 다시 실행하지 않는다.
[기계 판독 사전 기록](2026-11-21-k151-codec-release.json).

## 남은 한계

자원 해제는 전기적 mute/STOP/DMA drain 증거가 아니다. destructor의 마지막 정리도
실패할 수 있다. SDK control destructor의 하위 device-removal 반환값 누락, 불확실한
bus 회수, 동기 제어 지연은 남아 있다. 실제 질문/TLS/TTS peak·live admission,
마이크 채널·Hi StackChan/독립 GPT 대화도 미검증이다. Windows 물리I/O/OS 지연
원인은 이번 수정으로 해결했다고 주장하지 않는다.

이번 기기 접근·포트 열기·리셋·I2C·flash·실음성 저장/전송·유료 API는0이다.
사용자가 확인한 원본 펌웨어 복구 상태를 변경하지 않았다. HOLD/cloud OFF/출력·
drain false, owner/assets/power 준비 조건,100ms gap/chunk160..2048 및 기존
FIR/STOP/resume/session epoch/SDK 단일 소유권/volatile PCM wipe를 유지한다.
