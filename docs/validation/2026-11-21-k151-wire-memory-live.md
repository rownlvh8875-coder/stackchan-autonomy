# K151 합성 응답 메모리 실측

2026-11-21 KST. 사용자가 검토한 이미지의 진행을 승인한 뒤 무음 자원 진단을
한 번 실행했다. 원본 슬롯을 복구하고 독립 digest 검증과 파티션 표·OTA 일치를
확인한 뒤 출고 펌웨어로 재부팅을 요청했다. 이 기록 작성 시점의 사용자
화면 확인은 실시간 PR 기록에서 이어서 관리한다.
[기계 판독 기록](2026-11-21-k151-wire-memory-live.json).

| 실측 단계 | 남은 PSRAM | PSRAM 최대 연속 블록 | 남은 내부 힙 |
|---|---:|---:|---:|
| WakeNet 모델 준비 | 8,047,576 B | 7,995,392 B | 354,283 B |
| 모델·질문·JSON 파싱 직후 | 7,400,400 B | 7,077,888 B | 354,283 B |
| 모델·질문·speech 원본·디코딩 PCM 동시 | 5,729,228 B | 5,636,096 B | 354,283 B |
| HTTP 원본 반납 뒤 모델·질문·재생 PCM | 6,694,860 B | 6,684,672 B | 354,283 B |

speech 겹침 시점의 모델 준비 대비 추가 PSRAM 사용량은 2,318,348 B다.
384,000 B 질문과 각각 960,000 B의 speech 원본·디코딩 PCM이 PSRAM에 있었다.
두 speech vector의 capacity는 각 960,000 B였다. 내부 최대 연속 블록은
241,664 B였다. 합성 JSON 262,144 B도 PSRAM에 배치됐다. JSON 단계의
PSRAM 최소치 6,867,912 B는 디코더 내부 할당을 포함할 수 있는 누적
watermark다. 큰 문자열 하나를 가진 합성 fixture이며 최악의 JSON 형태는
측정하지 않았다.

512샘플 무음 64 chunk를 추론했다. 최대 detect 7.143 ms, 100ms 초과 및
합성 감지 모두 0이었다. USB nonce에 맞춰 START를 한 번 보내고 HOLD를
관측했다. 이 수치는 이 진단의 Quad PSRAM·할당 정책에서 관측한 값이다.
TLS handshake·certificate chain·Wi-Fi·실제 codec/DMA 동시 부하,
물리 STOP과 실제 호출어 인식·독립 GPT 대화는 미측정이다. 운영 admission은
false 상태다. 실음성·유료 API 요청은 0회다.

실행 코드 `f4878fa8b91b8b0b2d2514c81dc1fc1f37355f6b`, 실제 CI checkout
`69fbc67c9bdbd6e04af22da11699bf5683465910`. 진단 bin은 633,408 B,
SHA256 `8f10313f9a086f5f5a515f1dff0f2492f9af968e41b8892834a5d4a71e6ad9a5`.
COM3의 동일 칩, S3 rev0.2, 16MB, Secure Boot OFF, Flash Encryption OFF,
원본 슬롯의 사전 digest를 확인했다. 원본 A/B 및 별도 디스크 사본 3개의
16MiB 길이와 기존 SHA256이 일치했다.

| 작업 | 확인한 범위 | 결과 |
|---|---|---|
| 진단 쓰기 | `[0x510000,0x5AAA40)` | 11.062초, 독립 digest 일치 |
| 진단 섹터 지움 | `[0x510000,0x5AB000)` | 634,880 B |
| 원본 슬롯 복구 | `[0x510000,0xA00000)` | 5,177,344 B, 86.109초, 독립 digest 일치 |
| 표·OTA 검사 | 쓰기 전·진단 후·복구 후 | 3회 원본 일치 |

복구 slice SHA256 `39280cbec8d01362c559cedce7d8cd088d951096a5d8f045ead27fe6bf9038fb`.
flash 쓰기 2회, 명시적 재부팅 요청 4회였다. 사용한 명령은 같은 앱 슬롯에만
썼다. 원본과 원시 직렬 데이터는 로컬에서만 처리했다.

실행 코드의 실제 CI는 8/9이고 ESP32-S3 세 앱 compile/link가 통과했다.
PR Windows 3.12 job 136716500604의 virtual Mock soak는 cycle 911
`renew_timeout`으로 정지했다. 물리 I/O와 스케줄링 지연의 원인은 미확정이다.
[실행 코드 CI 및 PR 기록](https://github.com/rownlvh8875-coder/stackchan-autonomy/pull/3).
