# 기본 호출어 → 음성 대화 연결 검증

2026-11-20 / same feat/wakeword-josu / PR#3, base14126606eb9270f44767ec4dd3c45d14863a948e.

## 범위와 실제 동작

StreamingPcm24To16, NativeWakeController, 공통 VoiceDialogEntry를 구현했다. 실제 Session·AudioGuard·질문 segmentation·예산/dispatch permit·재생 guard를 사용해, fake native hit 이후 새 질문만 Mock STT/GPT/TTS로 넘기고 cooldown 이후 새 epoch로 돌아오는 경로를 검사한다. wake와 질문 입력 파형을 다르게 두어 wake PCM이 질문 API에 섞이지 않는지도 확인한다. SDK port는 full ESP-SR2.4.7 public interface C ABI doubles와 실제 ESP32-S3 툴체인으로 검증한다. Doubles는 실제 모델 추론이 아니다.

기본 호출은 새 epoch에 RAM 일회성 권한을 받는다. mismatch·재사용·취소·재부팅·손상 예산에서 거부하며 기존 SWK1 저장 형식/권한과 budget 선차감·read-back·동의·시간·유료3단계 순서는 유지한다. 실제 API를 호출하지 않았다.

HOLD startup에는 compile/link marker만 추가했다. model/assets 준비나 capture를 시작하지 않으며 파티션·sdkconfig·개인 설정/자격증명은 변경하지 않았다. 기존 조수 도구는 보존한다.

## 검증 결과

- Core 최초 RED31, admission 확장 RED8/30PASS → core38+기존 회귀3 =41PASS.
- SDK port 부재 RED25 → public ABI/lifecycle25PASS.
- 최종 수정 후 root pytest487PASS2SKIP; NumPy2.3.5/cryptography46.0.4를 공급한 standalone 전체381PASS7Windows-onlySKIP. 신규 focused70PASS, 별도 PC/NumPy105PASS3Windows-onlySKIP, SCPS19PASS.
- 생성 third-party/build 산출물을 정리한 뒤 Ruff check/format326projectfiles 전체 PASS. Project diff 검사는 `git diff --check 1412660..HEAD -- . ":!firmware/standalone/tests/sdk_esp_sr_2_4_7"`로 수행한다. 복사한 upstream SDK header/license의 기존 trailing whitespace는 보존하며 전체 upstream 포함 diff는 공백 경고를 낸다.
- 실제 IDF6.1/S3 build PASS. 최종 HOLD app325792bytes, 정적 DIRAM59030bytes. ELF에서 prepare/detect와 SDK esp_srmodel_init/esp_wn_handle_from_name 참조를 확인했다. virtual member pointer만으로는 detect가 GC되어 qualified nonvirtual thunk anchor로 고쳤고 marker는 실행을 시작하지 않는다. [기계 판독 artifact 증거](2026-11-20-native-wake-voice-bridge.json)를 따른다. 정적 size는 runtime 메모리나 인식 성능의 증거가 아니다.

## 기존 CI 실패 관측

이전 문서 head1412660의 CI run44735259544는 Windows Python3.12 가상 soak에서 cycle1607에 check_timeout(max cycle12.437s)으로 안전 정지했다. 같은 코드 재실행 attempt2에서도 cycle782 renew_timeout(max cycle8.25s)으로 안전 정지했다. 두 번 모두 wake/PC tests는 통과했다. 실행 지연의 원인을 infrastructure라고 확정하지 않으며 이전330946a의9/9를 현재 head 결과로 대신하지 않는다. 안전 timeout/lease·soak 길이·검사를 완화/생략하지 않았다. 새 head 결과는 별도로 PR에 기록한다.

## 판단과 남은 검증

- boot의 세 번째 bool을 wake-source readiness로 명명했다. 기존 bool/cloud off 동작을 유지한다. 향후 bootstrap이 실제 모델 준비를 증명해야 하며 잘못된 ready 공급은 실행 시 실패할 수 있다.
- 최대100ms feed gap, chunk160..2048은 보수적 prototype 경계다. 실제 처리 지연/SDK chunk가 범위를 벗어나면 자동 완화하지 않고 벤치 검토가 필요하다.
- NativeWakePort를 별도 header로 분리했다. PersistentGuard의 기존 profile 필수 결합은 검증된 로컬 builtin hit의 RAM epoch 권한으로 분리했다. 원격 wire 권한은 추가하지 않는다. 향후 bootstrap에서 이벤트의 신뢰 경계를 지켜야 한다.

모델 저장 위치/실제 assets 무결성/전원·오디오 routing/동적 heap·PSRAM/추론 지연·인식률/오탐/STOP/복구/실제 GPT 대화는 미검증이다. 현재 app은 model data나 운영 bootstrap을 제공하지 않는다. app 크기는 factory bootloader·파티션·설치/복구 호환의 증거가 아니다. 실제 device/COM3·mic·camera·motor·API·flash/NVS/OTA 실행 및 환경 게시 없음.

## 단일 독립 검토 후 보완

검토 Important4건과 입력 중 공급자 변경 경계1건을 한 번의 수정 묶음으로 처리했다. 회귀9FAIL을 먼저 확인했고 신규 focused70PASS로 전환했다. read/detect callback 재개 시험은 단조 시각을 사용해 수정 전 실제 소스에서도 거부 실패를 다시 확인했다.

1. capture 시작 epoch를 기록하고 poll·외부 callback 뒤 동일 세션인지 확인한다. STOP/resume 사이의 이전 부분 음성으로 새 호출을 만들지 않는다.
2. SDK의 process-global cached model list에는 atomic 단일 소유권을 적용한다. 다른 SDK 사용자가 이미 만든 list는 거부하고 건드리지 않는다. 실패한 두 번째 준비·다음 새 객체 획득을 검사한다. 이 이미지의 bootstrap은 다른 직접 SDK 사용자와 동시에 loader를 호출해서는 안 된다.
3. terminal detect 오류는 opaque model data와 list를 즉시 해제한다. 이후 파괴가 다시 해제하지 않는다.
4. owned PCM/FIR history/부분 chunk/임시 frame은 volatile-store 지움을 사용한다. GCC -O2 실제 destructor 출력의 zero store를 검사했다. register copy나 vendor opaque allocation 전체의 보안 삭제를 증명하는 시험은 아니다.
5. 첫 partial read 뒤에도 provider ready/format을 즉시 재확인한다. 원래 검토 Minor였으나 오래된 입력이 감지에 섞이는 영향 때문에 Important로 올려 검사했다.

보류 Minor: upstream SDK 원문의 공백을 재포맷하지 않는다. 프로젝트 소스 검사 범위는 위 명령으로 명시한다. 물리 인식/오탐·오디오/STOP 타이밍·자산 provisioning/무결성·동적 heap/PSRAM·설치/복구·실제 network/API는 검토 대상 코드의 완료 증거로 계산하지 않는다. 이는 HOLD 단계를 유지하는 판단이며 실제 실행 결함은 후속 실물 검증까지 남을 수 있다.

최종 수정 뒤 full standalone381PASS7SKIP, root487PASS2SKIP, 실제 S3 재빌드/심벌 검증 PASS. Linux 가상24시간2880cycles·재시작/복원11회·cloud0 PASS(실제24시간 경과 아님). 새 정확한 GitHub head 결과는 PR#3에 후속 기록한다.
