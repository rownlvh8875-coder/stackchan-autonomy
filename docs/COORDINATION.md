# 제어권과 지속형 API 예산

장치·API 키 없이 검증한 로컬 SQLite 기반 기능이다. 실물 실행 차단을 해제하지 않는다.

## 공용 설정

| 설정 | 기본값 |
|---|---|
| state_path / STACKCHAN_STATE_PATH | .local/autonomy.sqlite3 |
| control_resource / STACKCHAN_CONTROL_RESOURCE | stackchan:default |
| lease_ttl_s / STACKCHAN_LEASE_TTL_S | 10초 |
| budget_namespace / STACKCHAN_BUDGET_NAMESPACE | openai:default |

상대 경로는 **작업 디렉터리 기준**이다. 여러 실행 디렉터리/프로세스가 같은 로봇과
API 예산을 공유하려면 같은 절대 경로를 설정한다. 예시 PowerShell:

```powershell
$env:STACKCHAN_STATE_PATH = "C:/StackChanData/autonomy.sqlite3"
$env:STACKCHAN_CONTROL_RESOURCE = "stackchan:my-k151"
$env:STACKCHAN_BUDGET_NAMESPACE = "openai:default"
uv run --frozen stackchan-autonomy --mode mcp-sim --cycles 3 --event touch
```

resource/namespace에는 비밀키를 쓰지 않는다. 다른 namespace는 별도 예산이다.
예산을 공유하는 프로세스는 같은 한도를 사용한다. SQLite 파일은 로컬 디스크에서 사용한다.
초기 검증은 Linux에서 수행했다. 후속 [CI](CI.md)에서 Windows/Python3.11·3.12의
subprocess 경쟁·설치 wheel 실행도 통과했다. fork 회귀는 Linux에서만 실행한다.

## Lease 수명

ControlLease는 SQLite BEGIN IMMEDIATE 트랜잭션으로 owner UUID·generation·만료 시각을
획득한다. 다른 살아 있는 owner가 있으면 획득하지 못한다. 만료·반환 뒤의 새 획득은
generation을 증가시킨다. 예전 handle은 새 소유자를 갱신하거나 반환하지 못한다.
owner는 프로세스 ID에도 바인딩된다. Linux fork로 객체가 복사되면 자식은 새 owner를
사용하고 부모의 handle을 check/renew/release할 수 없다. 자식 프로세스에서는 asyncio
engine/executor를 새로 생성하며, 부모의 진행 중 태스크를 이어서 사용하지 않는다.

CLI는 시작 시, ActionExecutor 직접 사용은 최초 명령 전에 획득한다.
정상 실행 중 TTL/3마다 heartbeat로 갱신하고, 명령 직전에도 현재 소유권을 확인한다.
갱신 실패·만료·DB 오류는 새 명령 차단과 로컬 작업 취소로 이어지며, 대기 중 엔진도
관찰 주기를 기다리지 않고 ERROR로 종료한다. 자동 재획득·이전 명령 재실행은 하지 않는다.

정상 종료의 aclose는 로컬 명령/heartbeat 태스크가 끝난 뒤 조건부 release한다.
프로세스가 강제 종료되면 기본 10초 TTL까지 기다린다. 다른 프로세스 점유 중인 CLI는
종료 코드 2와 제어권 안내 메시지를 출력한다. DB 오류도 코드 2이며 명령을 보내지 않는다.

**적용 범위:** 이 규약을 따르고 같은 DB/resource를 공유하는 프로그램끼리의 협력 제어다.
다른 PC·다른 앱·출고 펌웨어 애니메이션은 통제하지 않는다. gateway가 generation을
검증하는 fencing이 없으므로, 이미 전송된 작업이나 멈췄다가 재개한 외부 프로세스를
하드웨어에서 차단하는 보장까지 제공하지 않는다. 실물 활성화 전 별도 검증이 필요하다.

## 지속형 예산

SQLiteRequestBudget는 HTTP 요청 전에 분/시간/일 rolling 예산을 한 트랜잭션에서 확인하고
예약한다. 기본 2/30/100회다. 동시 프로세스의 확인과 예약이 원자적이므로 같은 한도를
사용하면 경쟁으로 한도를 초과하지 않는다. SDK retry는 계속 0이다.
음성 STT/TTS 어댑터도 같은 namespace의 예약을 사용하며 주입한 SDK 클라이언트에도
retry=0을 적용한다. 오디오 endpoint의 token/요금은 추정하지 않고, 현재 token 집계는
알려진 Responses API usage만 반영한다. STT+Decision+TTS에는 최소 3회의 예약이 필요해
기본 분당 2회에서는 마지막 호출이 차단될 수 있다. 실제 연결 시 사용자가 비용에 맞는
한도를 명시적으로 설정해야 하며 앱이 한도를 자동으로 올리지 않는다.

확정된 예약은 HTTP 실패/시간초과/취소/강제 종료 때도 환급하지 않는다. 예약 직후
HTTP를 보내지 못하고 종료해도 1회로 계산한다. 알려진 응답의 input/output token 수와
전송·해석 오류 수는 집계한다. 응답을 받지 못한 token 수나 실제 청구액은 추정하지 않는다.
모델을 바꿔도 동일 namespace의 이력이 유지된다. 이 앱 밖의 OpenAI 요청이나 계정 전체
청구 한도와 연동하는 기능은 아니다.

누적 메타데이터 조회는 외부 API를 호출하지 않는다:

```python
from stackchan_autonomy.budget import SQLiteRequestBudget
from stackchan_autonomy.settings import Settings

settings = Settings.from_yaml("config/robot.yaml")
print(SQLiteRequestBudget(settings).snapshot())
```

DB에는 요청 예약 시각·누적 요청/토큰/오류 수와 제어권 메타데이터만 저장한다.
API 키, 원시 이미지·음성·대화는 이 모듈의 입력/저장 대상이 아니다.
DB를 사용할 수 없으면 메모리 예산이나 무소유 제어로 전환하지 않는다.

## 시각과 복구

시각은 재시작을 견디도록 wall clock을 쓰고, scope별 이전 최대 시각보다 뒤로 가지 않게
한다. 시계가 뒤로 이동하면 만료가 늦어질 수 있으며, 큰 앞으로의 점프는 만료를 앞당길 수 있다.
재시작할 때 같은 DB/namespace를 유지한다. DB 삭제·다른 경로/namespace 사용은 기존 이력과
제어권을 분리한다. 오류 원인을 해결하기 전 새 제어/요청은 차단되며, 복구 시 이전 명령을
자동으로 재전송하지 않는다. 파일 손상 시 모든 참여 프로세스를 종료하고 백업·진단 후
이력을 복구해야 한다. 앱이 DB를 임의로 삭제하거나 한도를 초기화하지 않는다.
