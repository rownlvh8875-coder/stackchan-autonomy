# K151 기본 호출어 → 독립 GPT 대화 진행 상태

2026-11-20 / Asia/Seoul. 기본 호출어 지원 검증을 먼저 진행하라는 사용자의 최신 선택에 따른다. 기존 “조수” 도구와 자료는 보존하며, 현재 작업 우선순위는 **Hi StackChan → 로봇 자체 GPT 대화** 경로다.

USB 재연결 후 현재COM3/S3/16MB·표/OTA 원본 일치를 직접 조회했고 실제 IDF
partition SHA를 검증하는 휴면 진입점을 추가했다.
[최신 장치·자산 연결 기록](validation/2026-11-20-k151-current-usb-and-assets.md)을 우선한다.
기기에는 새 펌웨어/모델을 설치하지 않았으며 현재 app_main도 HOLD다.

Windows 후속: [인수 검증](validation/2026-11-20-windows-handoff.md)에서 Mock timing
진단과 휴면 NativeVoiceLoop를 연결했다. 모델 pack은 같은 SHA로 로컬 재생성했고,
검증한 과거 OTA metadata의 선택 후보는ota_1이다. 현재 실행/안전한 spare 판정은
아니다. [자산·동적 메모리·설치/복구 준비](K151_NATIVE_INSTALL_PREP.ko.md)를 우선한다.
아래의 "아직 구현되지 않았다"는 이전 단계 이력이며, 현재 남은 것은 실제 장치
자산 SHA 공급·메모리 측정 provider·하드웨어 activation/STOP/drain과 실물 검증이다.

## 지금 확인한 결과

공식 StackChan 고정 소스는 ESP-IDF6.1 및 ESP-SR2.4.7의 `wn9l_histackchan_tts3`를 선택한다. 같은 버전으로 기존 K151 HOLD 앱의 임시 사본에 WakeNet API 참조와 모델 묶음을 추가해 **실제 ESP32-S3 컴파일/링크/모델 패킹 PASS**를 확인했다.

| 항목 | 실제 관측 |
|---|---|
| 선택 모델 | wn9l_histackchan_tts3 / Hi,Stack Chan / DET_MODE_90 API 참조 |
| 모델 묶음 | 292,607bytes, 모델1개·파일3개 및 각 SHA256 검증 |
| 검증용 HOLD 앱 bin | 334,688bytes (모든 음성 기능을 실행하는 최종 앱의 크기가 아님) |
| 정적 DIRAM | 65,482bytes (동적 heap/PSRAM 잔여량이 아님) |
| 공식 입력 규격 | 16kHz·모노·signed PCM16 |
| 기존 K151 경로 | 24kHz mic/reference 입력에서 모노 추출 |

원본 모델 파일 합계는292,447bytes이며 묶음 header160bytes가 더해진다. 디버그 ELF8,103,120bytes를 flash 점유량이나 RAM 요구량으로 계산하지 않는다. [기계 판독 증거](validation/2026-11-20-k151-builtin-wakenet-preflight.json)와 [기술 기록](validation/2026-11-20-k151-builtin-wakenet-preflight.md)을 참고한다.

## 이번에 구현한 연결

- 24kHz 10ms 입력을 상태가 이어지는 FIR로16kHz로 변환하고 SDK가 요구하는 chunk로 모은다. 실제 파형으로 DC·블록 경계·고주파 alias 억제를 검사했다.
- 기본 호출 이벤트가 감지되면 wake 마이크를 닫고 새 session epoch로 질문 녹음을 넘긴다. 공통 대화 계층을 사용하므로 기존 조수/SWK1 경로도 보존된다.
- 검증된 기본 호출은 RAM의 일회성 epoch 권한만 받는다. GPT 요청에는 여전히 소유자 동의·별도 cloud enable·신뢰 시간·저장된 예산 선차감과 요청 단계별 중복 차단이 필요하다. 기본 호출 경로에 개인 SWK1 등록을 강요하지 않는다.
- 실제 ESP-SR2.4.7 어댑터는 모델 이름/개수/입력 형식·오류·해제 순서를 검사한다. HOLD 앱에는 링크만 하며 SDK 초기화나 모델 감지를 시작하지 않는다.

실제 core의 **가짜 detector → 질문 캡처 → Mock STT/GPT/TTS → 재생 → cooldown**을 검사했다. 이 통과는 신경망 인식 성공이나 실물 대화 성공을 뜻하지 않는다. [이번 연결 검증 기록](validation/2026-11-20-native-wake-voice-bridge.md)을 따른다.

## 남은 연결 순서

```mermaid
flowchart TD
    A[기본 모델 소스·빌드·패킹 확인 완료] --> B[상태 유지 변환·유한 버퍼 구현 완료]
    B --> C[모델 어댑터·호출 이벤트 구현 완료]
    C --> D[질문 → STT/GPT/TTS Mock 연결 검증 완료]
    D --> E[배치·복구·전원·오디오 및 자원 검증]
    E --> F[실물 변경 범위와 복구 계획 검토]
    F --> G[승인된 실물 호출·음성 대화 검증]
```

1. **구현됨 — 입력 변환:** 기존 질문/출력은24kHz로 유지하고 WakeNet에 전달하는 스트림만16kHz로 변환한다. 매 블록마다 FIR 상태를 새로 만들지 않는다. 실제 model getter로 chunk 크기/채널/샘플레이트를 확인하고 유한 버퍼로 모은다.
2. **구현됨 — 호출 경로:** 기성 모델 준비 여부를 개인 SWK1 등록 여부와 구분한다. STOP·동의·스피커 재생 차단과 session epoch를 유지하며 호출 이벤트 뒤 질문 대기로 전환한다. 기본 모델 경로는 개인 음성 등록을 요구하지 않는다.
3. **Mock 검증됨 — GPT 연결:** 기존 bounded 질문 캡처와 STT/GPT/TTS·재생 완료 후 대기 복귀를 연결했고 Mock으로 검증했다. 지금의 MCP+PC GPT 성공은 이 독립 경로의 완료 증거가 아니다.
4. **실물 전 준비:** model 저장 위치/무결성, 실제 활성 OTA와 복구 대상,8MB PSRAM/내부 heap·지연, 마이크·스피커 전원과 STOP 동작을 확인한다. 모델과 UI/질문/TLS/TTS가 함께 실행될 때의 자원량은 정적 빌드 크기로 대신하지 않는다.

## 현재 실물에서 할 일

기존 출고 펌웨어의 AI Agent 얼굴 화면에서 **“Hi StackChan(하이 스택챈)” 호출 반응**을 확인해 알려준다. 이 결과는 출고 펌웨어의 동작 관측이며 개발 이미지의 인식 성능과 구분한다. 기존 “조수” 등록을 같은 설정으로 반복할 필요는 없다.

현재 모델 자산 공급·메모리 admission·운영 bootstrap은 아직 구현/검증되지 않았다. 현재 검증용 모델은 시작되지 않았다. 실제 마이크 인식률·오탐·처리 지연·동적 메모리와 로봇 단독 GPT 한 턴은 미검증이다. 제품 실행 코드와 app_main은 기존 HOLD를 유지한다. 임시 모델 파티션은 공장 배치와 달라 실물 설치 대상으로 사용할 수 없다. 이번에는 실제 기기/COM3·flash/NVS/OTA/모터·유료 API·음성 전송을 실행하지 않았다.
