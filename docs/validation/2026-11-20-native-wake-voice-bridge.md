# 기본 호출어 → 음성 대화 연결 검증

2026-11-20 / same feat/wakeword-josu / PR#3, base14126606eb9270f44767ec4dd3c45d14863a948e.

## 범위와 실제 동작

StreamingPcm24To16, NativeWakeController, 공통 VoiceDialogEntry를 구현했다. 실제 Session·AudioGuard·질문 segmentation·예산/dispatch permit·재생 guard를 사용해, fake native hit 이후 새 질문만 Mock STT/GPT/TTS로 넘기고 cooldown 이후 새 epoch로 돌아오는 경로를 검사한다. wake와 질문 입력 파형을 다르게 두어 wake PCM이 질문 API에 섞이지 않는지도 확인한다. SDK port는 full ESP-SR2.4.7 public interface C ABI doubles와 실제 ESP32-S3 툴체인으로 검증한다. Doubles는 실제 모델 추론이 아니다.

기본 호출은 새 epoch에 RAM 일회성 권한을 받는다. mismatch·재사용·취소·재부팅·손상 예산에서 거부하며 기존 SWK1 저장 형식/권한과 budget 선차감·read-back·동의·시간·유료3단계 순서는 유지한다. 실제 API를 호출하지 않았다.

HOLD startup에는 compile/link marker만 추가했다. model/assets 준비나 capture를 시작하지 않으며 파티션·sdkconfig·개인 설정/자격증명은 변경하지 않았다. 기존 조수 도구는 보존한다.

## 검증 결과

- Core 최초 RED31, admission 확장 RED8/30PASS → core38+기존 회귀3 =41PASS.
- SDK port 부재 RED25 → public ABI/lifecycle25PASS.
- 최종 root pytest487PASS2SKIP; standalone 전체338PASS43SKIP; 선택 의존성을 공급한 PC/NumPy105PASS3Windows-onlySKIP. standalone43SKIP 중36개는 선택 NumPy 의존성으로 PC 별도 실행에서 검사되며7개는 Windows-only다.
- Ruff check/format326files PASS (target 빌드가 다운로드한 third-party managed_components 제외); diff check PASS.
- 실제 IDF6.1/S3 build PASS. 최종 HOLD app325632bytes, 정적 DIRAM59030bytes. ELF에서 prepare/detect와 SDK esp_srmodel_init/esp_wn_handle_from_name 참조를 확인했다. virtual member pointer만으로는 detect가 GC되어 qualified nonvirtual thunk anchor로 고쳤고 marker는 실행을 시작하지 않는다. [기계 판독 artifact 증거](2026-11-20-native-wake-voice-bridge.json)를 따른다. 정적 size는 runtime 메모리나 인식 성능의 증거가 아니다.

## 기존 CI 실패 관측

이전 문서 head1412660의 CI run44735259544는 Windows Python3.12 가상 soak에서 cycle1607에 check_timeout(max cycle12.437s)으로 안전 정지했다. 같은 코드 재실행 attempt2에서도 cycle782 renew_timeout(max cycle8.25s)으로 안전 정지했다. 두 번 모두 wake/PC tests는 통과했다. 실행 지연의 원인을 infrastructure라고 확정하지 않으며 이전330946a의9/9를 현재 head 결과로 대신하지 않는다. 안전 timeout/lease·soak 길이·검사를 완화/생략하지 않았다. 새 head 결과는 별도로 PR에 기록한다.

## 판단과 남은 검증

- boot의 세 번째 bool을 wake-source readiness로 명명했다. 기존 bool/cloud off 동작을 유지한다. 향후 bootstrap이 실제 모델 준비를 증명해야 하며 잘못된 ready 공급은 실행 시 실패할 수 있다.
- 최대100ms feed gap, chunk160..2048은 보수적 prototype 경계다. 실제 처리 지연/SDK chunk가 범위를 벗어나면 자동 완화하지 않고 벤치 검토가 필요하다.
- NativeWakePort를 별도 header로 분리했다. PersistentGuard의 기존 profile 필수 결합은 검증된 로컬 builtin hit의 RAM epoch 권한으로 분리했다. 원격 wire 권한은 추가하지 않는다. 향후 bootstrap에서 이벤트의 신뢰 경계를 지켜야 한다.

모델 저장 위치/실제 assets 무결성/전원·오디오 routing/동적 heap·PSRAM/추론 지연·인식률/오탐/STOP/복구/실제 GPT 대화는 미검증이다. 현재 app은 model data나 운영 bootstrap을 제공하지 않는다. app 크기는 factory bootloader·파티션·설치/복구 호환의 증거가 아니다. 실제 device/COM3·mic·camera·motor·API·flash/NVS/OTA 실행 및 환경 게시 없음.
