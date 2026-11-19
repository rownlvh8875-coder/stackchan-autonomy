# StackChan '조수야' 비공개 녹음 데이터셋 준비·품질검사

**2026-11-20 / 오프라인 사전 검증용 / 실제 녹음 미실시 / 기기 설치 불가**

## 1. 이번 단계의 범위

`tools/wake_corpus_template.py`는 새 **개인용** `*.wake-corpus.json` 파일을 만들고, `tools/wake_corpus_audit.py`는 그 목록의 WAV 파일을 검사한다. 인터넷·클라우드·마이크·로봇·API에 접근하지 않으며, 기존 파일을 변경하거나 오디오를 생성하지 않는다.

다음 명령을 **개인 PC에서** 실행한다. 먼저 본인이 관리하는 비공개 폴더를 만들어야 한다.

```powershell
# 예시: 원하는 로컬 폴더를 사용. 실제 경로는 본인이 선택.
New-Item -ItemType Directory -Force C:\private\stackchan-corpus

uv run --frozen python firmware/standalone/tools/wake_corpus_template.py --output C:\private\stackchan-corpus\private.wake-corpus.json
```

템플릿에는 18개 **파일 경로 자리표시자**가 기록되며 WAV 파일은 만들어지지 않는다. 서브폴더 `enrollment`, `calibration`, `evaluation`를 만들고 각 상대 경로에 실제 별도 녹음본을 준비한 뒤 아래 명령으로 확인한다.

```powershell
uv run --frozen python firmware/standalone/tools/wake_corpus_audit.py C:\private\stackchan-corpus\private.wake-corpus.json
```

반드시 개인 데이터는 Git 저장소 **외부**에 보관한다. `.gitignore`에 `*.wav`, `*.WAV`, `*.swk1`, `*.wake-corpus.json`를 추가·유지하지만 `git add -f`처럼 강제 추가하면 개인정보가 올라갈 수 있다.

## 2. 데이터 구분

| 단계 | 레이블 | 템플릿 최소 수 | 용도 |
|---|---|---:|---|
| enrollment | wake | 1 | 호출 특징 등록 |
| calibration | wake | 5 | 등록하지 않은 발화로 임계값 보정 |
| calibration | nonwake | 10 | 비호출어로 임계값 보정 |
| evaluation | wake | 1 | 훈련·보정에 사용하지 않는 독립 평가 |
| evaluation | nonwake | 1 | 훈련·보정에 사용하지 않는 독립 평가 |

위 표는 기존 `calibrate_wake()`의 최소 입력 조건과 실행 전 검증을 위한 **자리표시자 계획**이다. 최종 평가 각각 1개로는 호출 인식률·오인식률이나 실용적 성능을 판단할 수 없다. 독립적 시험에서는 더 많은 발화·화자·거리·소음·로봇 출력 음성을 확보해야 한다. 보정에 사용한 파일을 최종 성능 평가에 **재사용하지 않는다**.

`session` 값은 다른 날짜/시점/환경에서 별도 녹음을 했다는 **사용자 입력 라벨**이며, 코드가 실제 녹음 시점을 검증하지 못한다. 같은 세션 라벨이 등록·보정·최종평가 단계에 중복되면 검사를 거부한다.

## 3. 형식·품질 판정

- PCM16, 단일 채널, 정확한 24,000Hz, 0.1초~3초 WAV/RIFF만 허용한다. 동일한 PCM을 파일명만 바꾸거나 단계별로 중복 배정하면 거부한다.
- 디지털 무음 또는 기존 MFCC 코어의 최소 에너지 게이트보다 낮은 신호는 거부한다. 단순 화면 이름·문구로 실제 한국어 발화를 인식하지는 못한다.
- 샘플의 **1% 이상이 절댓값 32700 이상**이면 클리핑 의심, 평균 DC 오프셋이 풀스케일의 **10% 초과**이면 오프셋 주의, 정규화 RMS **0.01 미만**이면 저레벨 주의라고 출력한다. 이는 개발 편의용 휴리스틱이며 전문 음향 계측·교정 기준은 아니다.
- 시험 번호·상대 경로·중복 JSON 키·심볼릭 링크·경로 이탈·중복 녹음·그룹별 세션 중복 등을 거부한다.
- 검사 결과에는 역할별 파일 수·길이 범위·문제 유형의 집계만 출력한다. **원본 녹음, 실제 파일 경로, 해시/개별 특징, 사용자 식별 정보는 출력하지 않는다.**

`CORPUS_STRUCTURALLY_SCREENED` 상태는 파일 구조를 통과했다는 뜻일 뿐 **실제 발화의 정확한 라벨, 화자별 독립성, 데이터의 실측 품질, 호출 정확도, 펌웨어 설치 허가를 의미하지 않는다.** `safe_to_install=false`는 항상 유지한다.

## 4. 오프라인 다음 단계

검사를 통과하고 실제 독립 발화가 준비됐다면, 이미 구현된 `tools/wake_wav_enroll.cpp`를 사용해 개인 로컬 컴퓨터에서 등록용 SWK1를 생성한다. 최종 평가용 WAV는 임계값 보정에 **절대로 포함하지 않는다**. `tools/wake_wav_eval.cpp`로 최종 평가 집계만 계산한다. 로봇 하드웨어용 HOLD 펌웨어는 그대로 유지하며, 공장 펌웨어 복구 및 전원·마이크·스피커·물리 STOP 검증 전 설치하지 않는다.
