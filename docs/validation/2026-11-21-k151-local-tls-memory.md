# K151 메모리 TLS 진단 사전 검증

기존 실물 합성 응답 진단의 후속이다. 새로운 자원 진단은 별도 서버나 Wi-Fi
없이 Mbed TLS 1.2를 실행한다. 런타임에 볼 수 있는 상태는 연결 전, 연결 후,
TLS와 합성 JSON/PCM이 동시에 유지되는 단계다. 임시 CA와 leaf의 개인키는
volatile PSA에만 생성하며 파일, 빌드 이미지 또는 직렬 출력으로 내보내지 않는다.
실제 서비스 trust bundle, 호스트 네트워크, 기기 오디오와 운영 admission은
다른 검증 대상이다. [측정 범위](../K151_RESOURCE_BENCH.ko.md).

Windows에서 [공식 Mbed TLS 4.1.0](https://github.com/Mbed-TLS/mbedtls/releases/tag/mbedtls-4.1.0)
release archive를 게시된 SHA256과 비교하고 Zig/Clang으로 C 라이브러리를
빌드했다. 호스트 fixture에서 정상 인증서·호스트 이름의 연결, 암호화 레코드
수신, 틀린 이름의 handshake 거부, 인증서 준비 중과 handshake 진입 STOP을
확인했다. 재호출 거부와 `NDEBUG` 빌드 거부도 확인했다.

고정 IDF 포크의 일반 호스트 빌드는 ESP 전용 헤더가 필요했다. Windows
검증에는 upstream 4.1.0 release를 사용하고, IDF 포크는 고정 ESP32-S3 CI로
확인한다. 처음 호스트 fixture는 ECDSA 모드와 opaque key의 알고리즘이
달라 cipher 선택에서 실패했다. SDK 매크로가 선택하는 ECDSA 모드로 PSA
키를 만들면 검증을 유지한 상태로 통과한다.

새 진단의 측정에는 서버 상태가 포함된다. 운영 OpenAI 피어의 인증서·Wi-Fi·
TLS 자원 최대치를 이 결과로 판정하지 않는다. 새 기기 접근·쓰기, 실음성,
유료 API 실행은 0회다. 이전 실물 시험의 원본 복구 및 출고 부팅 요청은
확인했고 화면은 사용자 관찰 대기 상태다.
