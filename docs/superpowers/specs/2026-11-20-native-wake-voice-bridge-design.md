# K151 기본 호출어 → 음성 대화 연결 설계

사용자가 기본 호출어 지원 검증을 선택한 뒤 다음 구현을 지시했다. 같은 feat/wakeword-josu/PR#3에서 1412660을 기준으로 진행한다. 현재 제품은 출고 펌웨어이며 구현·빌드 승인은 실제 설치/유료 API/음성 전송 승인이 아니다. 이전 한국어 도구/평가를 보존한다.

## 선택과 계약

공식 Hi StackChan 모델의 고정 SDK 빌드/패킹은 선행 검증됐다. batch SWK1 경로를 계속 요구하면 기성 모델에도 개인 등록이 필요하므로, **공통 음성 대화 진입 계층**과 **서로 다른 호출 감지 공급자**를 분리한다. 기존 WakeVoiceEntry API는 유지한다. 질문·STT/TTS는24kHz를 유지하며 wake 입력만16kHz로 변환한다. 기본 모델 경로에 임의 SWK1/학습·새 문턱을 넣지 않는다.

- StreamingPcm24To16: 10ms의240개 PCM16을160개로 변환, 기존 검증된33-tap/2phase/cutoff0.30의 causal FIR.16input-sample 지연을 포함하고 상태를 블록 간 유지한다. 고정 array와 non-elidable owned PCM 지움을 사용하며 잘못된 span은 reset/출력 소거 후 거부한다. 저역 통과/DC와10kHz alias 억제를 실제 신호로 검증한다.
- VoiceDialogEntry: owner consent/STOP/speaker-busy/wake_wait/epoch/질문 소비/기존 OfflineVoiceCycle을 공유한다. WakeVoiceEntry는 기존 MFCC/DTW를 적용한 뒤 공통 confirmed_wake를 호출한다. VoiceTurnCoordinator는 공통 entry를 받아 기존/기본 경로를 모두 처리한다. Session의 세 번째 boot flag는 wake-source 준비 여부로 명명하고 기존 bool 동작·cloud off 기본값은 유지한다.
- PersistentGuard는 기본 호출의 검증된 Session epoch에 RAM 전용 일회성 admission을 묶는다. 소유자 동의·모델 준비·새 epoch를 요구하고, 질문의 동일 epoch 예약에서만 소비하며 취소/실패/재부팅으로 폐기한다. 기존 SWK1 프로필 권한과 별개이며 durable budget 선차감·read-back·시간·단계 순서/중복 차단은 공통이다. 저장 스키마/임의 프로필은 추가하지 않는다.
- NativeWakePort: ready/format(16kHz mono PCM16, chunk160..2048)/detect(mutable bounded PCM)/reset을 제공한다. NativeWakeController는 이미 허가된 AudioGuard+MonoMicReader로 wake 전용10ms를 읽고 변환/고정 최대2048sample chunk에 모은다. begin/poll/cancel은 단일 소유 task에서 직렬 호출한다.
- Controller는 capture 시작 epoch와 STOP/동의/재생/state/format을 입력 및 detect 전후 재확인한다. backward clock 또는100ms를 넘는 capture gap, IO/model/close/reset 오류는 context 소거+정지 latch다. 실제 지연은 미검증이며 이 고정 gap은 보수적 프로토타입 정책이다. DET hit에서 wake mic를 닫고 context를 지운 뒤 정확한 새 epoch를 반환한다. 이후 기존 coordinator가 새 질문 녹음을 시작한다. 요청은 기존 durable budget/clock/별도 cloud enable을 계속 요구한다.
- 기성 모델이 준비되지 않으면 시작하지 않는다. 취소/파괴가 활성 wake capture만 종료하며 이미 질문에 넘긴 inactive controller의 파괴/취소는 질문을 중단하지 않는다. 정상 cooldown 후 새 begin은 새 DSP/model context로 시작한다.
- K151WakeNetPort: ESP-SR==2.4.7을 사용한다. prepare의 두 권한(owner,verified model assets)은 신뢰된 실물/로컬 판단이며 SCFG/원격 값이 아니다. 정확한 wn9l_histackchan_tts3 한 모델/한 호출어, DET_MODE_90,16k mono/유한 chunk를 확인한다. SDK global loader는 단일 live adapter 소유권을 요구하고 다른 직접 SDK 사용자와의 동시 사용을 허용하지 않는다. 기존 외부 cache는 거부한다. 실패/종료 시 model data→model list 순서로 해제하며 lifecycle 한 번만 준비한다. terminal detect 오류도 즉시 해제한다. C API의0/-1은 비호출,1은 호출, 기타 값은 오류다. threshold setter는 사용하지 않는다.
- SDK adapter는 생성/실행하지 않고 HOLD의 marker로 compile/link한다. dependency만 고정하며 현재 partition/PSRAM/부팅 설정·자격증명/NVS/설정 wire는 바꾸지 않는다. model partition 공급·무결성 판단/동적 메모리 admission/실행 bootstrap은 향후 실물 준비다. 현재 firmware image는 model data/운영 bootstrap을 제공하지 않는다.

## 검증과 제한

수학 신호와 실제 C++ core, SDK의 전체 공개 인터페이스를 사용하는 host C ABI doubles로 lifecycle/shape/오류를 검사한다. native wake→질문→Mock STT/GPT/TTS→cooldown 통합과 기존 SWK1 회귀를 유지한다. 실제 ESP-IDF6.1/S3 compile/link로 vendor ABI를 확인한다. Fake detector의 hit는 실제 Hi StackChan 인식률 증거가 아니다. 신경망 실행·실제 마이크/서보/음성/네트워크/API·flash/OTA/NVS 변경을 실행하지 않는다. 실제 응답/자원/latency/복구/모델 assets는 후속 현장 검증이다.
