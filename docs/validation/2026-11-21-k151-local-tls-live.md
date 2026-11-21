# K151 메모리 TLS와 합성 응답 실측

2026-11-21 KST. 검토한 이미지로 한 번 실행했다. 임시 로컬 CA와 leaf 인증서를
검증하는 메모리 TLS 1.2 연결을 열고 암호화 샘플 레코드를 확인했다. 두 TLS
객체를 유지한 채 기존 수신기와 디코더에 최대 합성 응답을 공급했다.
[기계 판독 기록](2026-11-21-k151-local-tls-live.json).

| 관측 시점 | 남은 내부 힙 | 내부 최대 연속 블록 | 남은 PSRAM | PSRAM 최대 연속 블록 |
|---|---:|---:|---:|---:|
| 모델과 질문, TLS 연결 전 | 353,659 B | 237,568 B | 7,662,548 B | 7,602,176 B |
| 두 TLS 객체의 연결과 레코드 검사 뒤 | 307,899 B | 196,608 B | 7,657,168 B | 7,602,176 B |
| TLS 유지, 합성 JSON decode 직후 | 307,899 B | 196,608 B | 7,395,020 B | 7,077,888 B |
| TLS·질문·speech 원본·디코딩 PCM 동시 | 307,899 B | 196,608 B | 5,723,848 B | 5,636,096 B |
| TLS와 원본 반납 뒤, 재생 PCM 유지 | 352,279 B | 196,608 B | 6,694,860 B | 6,684,672 B |

TLS 전후 차이는 내부 힙 45,760 B와 PSRAM 5,380 B다. 인프로세스 서버와
메모리 FIFO를 포함한 값이다. 동시 처리 시 모델 준비 대비 추가 PSRAM은
2,323,728 B였다. 질문 384,000 B와 speech 원본·디코딩 PCM 각 960,000 B는
PSRAM에 배치됐다. 합성 JSON 262,144 B도 PSRAM이었다. 내부 최소치는
298,695 B였고 단계까지의 누적 watermark다. TLS 정리 뒤 내부 힙 차이를
단일 반복으로 누수 또는 고정 오버헤드로 판정하지 않는다.

512샘플 무음 64 chunk를 추론했다. 최대 추론 7.247 ms, 100 ms 초과와
합성 감지 모두 0이었다. 새 nonce에 START 한 번을 보내 완료와 HOLD를
관측했다. 이 기록은 메모리 TLS 시험의 실측이다. 운영용 HTTPS 서버 체인,
Wi-Fi·OS 네트워크·실제 codec과 TLS의 동시 peak, 물리 STOP·mute·drain,
실물 호출어·독립 GPT 대화는 미검증이다. 진단의 `tls_measured=false`는
운영 TLS 경로의 판정이며 `local_tls12_peer_verified=true`가 이번 관측이다.
운영 admission은 false다.

실행 코드 `1c19894c3715f62c5e414defe86d0c181446a0ee`, 실제 CI checkout
`9012a5dc9cd5151d892703dd59b79c8742dbed8a`. 진단 bin 786,688 B,
SHA256 `6f84e4d0f876c3ab18cdc129db31cd5eed5b2b6e3b3d80f52b9740543589afd0`.
COM3에서 동일 칩, ESP32-S3 rev0.2, 16MB, Secure Boot 및 Flash Encryption
OFF와 쓰기 전 원본 전체 슬롯의 digest를 확인했다. 원본 A/B와 별도 디스크
사본의 16MiB 길이 및 기존 SHA256이 서로 일치했다.

| 실행 | 범위 | 결과 |
|---|---|---|
| 진단 쓰기 | `[0x510000,0x5D0100)` | 13.516초, 독립 digest 일치 |
| 진단 섹터 지움 | `[0x510000,0x5D1000)` | 790,528 B |
| 원본 복구 | `[0x510000,0xA00000)` | 5,177,344 B, 84.656초, 독립 digest 일치 |
| 파티션 표·OTA 검증 | 쓰기 전·진단 뒤·복구 뒤 | 세 시점 원본 일치 |

복구 슬라이스 SHA256 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`.
flash 쓰기 2회, 명시적 재부팅 요청 4회였다. 출고 부팅 요청 뒤 COM3이
다시 나타났다. 사용자 화면 확인은 PR 기록에서 이어서 관리한다. 원본과 원시
직렬 내용은 게시하지 않았다. 실음성 수집과 유료 API 실행은 0회다.

실행 코드 CI는 9/9였다. ESP32-S3 세 앱 compile/link와 Windows Mock
네 조합의 2,880 cycle을 통과했다. 이전 Windows 지연의 원인은 미확정이다.
[실행 코드 CI와 이력](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3).
