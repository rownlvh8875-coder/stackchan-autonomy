# K151 기본 WakeNet 지원 검증

2026-11-20 (Asia/Seoul) / code base330946a / feat/wakeword-josu / PR#3.

## 근거와 범위

실제 사용자 PC 보정은 녹음 품질을 통과했으나 호출/비호출 거리가 겹쳐 calibration_not_separable로 거부됐다. 이 숫자를 사용해 문턱이나 모델을 학습하지 않았다. 사용자는 기본 호출어 지원 검증을 우선하는 추천 방향에 진행을 지시했다. 한국어 도구/합격 회귀를 보존하고 새 기본 모델의 가능성을 조사했다.

공식 m5stack/StackChan@28b9f0c의 sdkconfig.defaults는 CONFIG_SR_WN_WN9L_HISTACKCHAN_TTS3, manifest는 ESP-SR==2.4.7 및 IDF>=6.1,<6.2를 명시한다. Component Registry HTTP200 및 캐시 패키지의 version/repository commit/component_hash를 확인했다. ESP-SR의 Espressif MIT 라이선스는 Espressif 제품에서의 사용을 허용하며 K151은 ESP32-S3 기반이다. 모델/라이브러리 binary는 저장소에 추가하지 않았다.

## 실제 수행

- 기존 core/esp_app을 무시된 .local의 새 검증 사본으로 복사했다. 제품 실행 소스는 수정하지 않았다.
- 사본에 ESP-SR==2.4.7, 정확한 모델 선택, PSRAM/240MHz 설정, 명백한 비공장 개발 파티션을 추가했다.1MiB model 파티션은 패킹 검증용이며 기존 OTA/assets 배치와 호환되지 않는다.
- API 참조용 dormant 함수는 esp_srmodel_init → 정확한 모델 filter → esp_wn_handle_from_name → create/getters/destroy/deinit를 컴파일한다. HOLD 시작 함수는 이 함수를 호출하지 않고 volatile 함수 주소를 유지하는 marker만 읽는다. symbol table에서 marker/dormant 함수/두 모델 API의 실제 링크를 확인했다. target getter 및 신경망 추론은 실행하지 않았다.
- 고정 IDF6.1 fff9895c에서 `idf.py set-target esp32s3` 및 `idf.py build`가 종료코드0으로 완료됐다(2,108 Ninja steps). 모델 패커는 선택 모델1개를 보고했다.
- 묶음 header를 별도로 읽어 모델명·모델 수1·파일 수3·범위와 각 파일 SHA256을 실제 패키지 원본과 비교했다. 생성 묶음292,607bytes, app bin334,688bytes. 상세 hash와 정적 map은 JSON 증거에 있다.
- size CLI의 최초 `--format json`은 지원하지 않는 형식으로 종료코드2였다. 도움말에서 json2를 확인해 `python -m esp_idf_size --format json2`로 바로잡았고 정적 DIRAM65,482bytes를 확인했다. SDK 경고는 있었으며 오류 없이 빌드가 완료됐다.

## 판정

**PASS: 이 고정 SDK/모델의 ESP32-S3 컴파일·링크·패킹 가능성.** 파일 존재만으로 모델 데이터 포함을 추정하지 않고 실제 pack 내용과 ELF symbol을 확인했다.

**미검증:** K151 target의 모델 생성, getter의 실제 chunk 크기·채널·rate, 추론 지연/CPU/heap/PSRAM peak, 실제 사람 호출/유사어/TV·소음 오탐, 재생 중 재호출, 독립 GPT 대화, 설치/복구. 공식 문서는16kHz모노PCM16을 요구하지만 runtime getter를 대체하지 않는다. 검증 ELF는 대부분 비활성 HOLD이므로 전체 운영 앱의 자원량을 뜻하지 않는다.

기존 stock backup 파티션 표에는 model label이 없다. 기존 assets에 모델이 어떤 방식으로 들어 있는지 확인하지 않은 상태에서 개발용 model 파티션을 stock에 겹쳐 넣지 않는다. 실제 설치 배치·활성 OTA·복구 계획을 준비하는 별도 단계가 필요하다.

이번 source 변경은 문서와 증거뿐이다. 기존 code base330946a의 CI9/9 SUCCESS와 새 문서 head의 CI는 구분해 PR에 기록한다. 새 코드/테스트를 추가하지 않았으므로 기존 Python suite를 같은 코드로 수동 반복 실행하지 않았다. 지원 검증 자체는 실제 타깃 빌드/패킹/별도 크기·내용 검증으로 수행했다.

[다음 연결 순서](../K151_BUILTIN_WAKE.ko.md) / [기계 판독 증거](2026-11-20-k151-builtin-wakenet-preflight.json). 임시 빌드 소스/펌웨어/모델 bin은 배포하지 않으며 NOT APPROVED FOR DEVICE INSTALLATION을 유지한다.
