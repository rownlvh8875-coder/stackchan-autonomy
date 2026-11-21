# 2026-11-20: Windows 노트북 내장 마이크의 “조수” 호출어 1회 검사

## 목적과 적용 범위

실기기 ESP32-S3 K151의 출고 펌웨어와 NVS에 쓰지 않고, PC 마이크의 음성을 기존 C++ SWK1 인식기에 연결하는 **오프라인, 1회성 시험 기능**.

- 기존 tools/wake_stage1_probe.cpp에 표준 입력 WAV 입력 추가. 기존 파일 시험과 동일한 parse_wake_pcm24k_wav → offline_wake_extract → SWK1 매처 실행.
- WAV는 최대 196,608바이트. 잘못된 RIFF/PCM, 지나치게 큰 입력, 무음, 비정상 프로필은 거부. 오디오 바이트를 출력하지 않음.
- tools/pc_mic_wake_probe.py는 **--listen 명시**와 장치 번호 지정이 있어야 마이크를 연다. 장치는 Windows의 노트북 입력이며 K151 마이크가 아니다.
- 노트북 입력: 48kHz mono PCM16, 최대 3초 1회. FIR 저역통과 및 24kHz 변환, 20ms 에너지 구간 검출, 구간 앞뒤 최대 400ms 보존.
- PCM/생성 WAV는 메모리에서만 C++ 프로세스 stdin으로 전달한다. 도구 자체는 파일 저장, 상시 녹음, 로봇 USB/서보 명령, OpenAI 계정/API/네트워크 요청, STT/TTS를 사용하지 않는다.
- --fixture는 마이크를 열지 않고 이미 준비된 합성 WAV로 경로를 시험한다.

**“조수”가 검출돼도 현재 경로는 콘솔에 판정만 출력한다.** GPT 응답 또는 로봇 스피커 출력은 자동 실행하지 않는다.

## Windows 노트북에서 사용한 C++20 빌드

저장소 루트에서 다음 명령으로 PC용 판별기만 생성했다. 결과 exe는 ESP32 펌웨어 바이너리가 아니다.

    uvx --offline --from ziglang==0.15.2 python-zig c++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic -Ifirmware/standalone/core firmware/standalone/tools/wake_stage1_probe.cpp -o C:\Users\user\Documents\josu_pcm_stdin_probe_20261120.exe

오프라인 합성 음성 파일 시험:

    uv run --frozen python firmware/standalone/tools/pc_mic_wake_probe.py --probe-exe C:\Users\user\Documents\josu_pcm_stdin_probe_20261120.exe --profile firmware/standalone/fixtures/korean_josu_sapi_20261120/josu-20261120.swk1 --fixture firmware/standalone/fixtures/korean_josu_sapi_20261120/evaluation/evaluation_wake_01.wav

사용자가 **직접 마이크 입력을 허용하고 “조수”라고 말할 때만** 다음을 실행한다.

    uv run --offline --no-project --with sounddevice==0.5.3 --with numpy python firmware/standalone/tools/pc_mic_wake_probe.py --probe-exe C:\Users\user\Documents\josu_pcm_stdin_probe_20261120.exe --profile firmware/standalone/fixtures/korean_josu_sapi_20261120/josu-20261120.swk1 --listen --device 9 --seconds 2.5

장치 번호 9는 2026-11-20 해당 Windows 노트북 Realtek 입력의 관측값으로, 다른 환경에는 그대로 적용할 수 없다. 시작 직전 RECORDING_NOTEBOOK_MIC_ONLY를 출력한다.

## 이번 실제 관측

1. Windows Zig C++20 컴파일과 WAV stdin 판별 성공.
2. 새 “조수” Heami 합성 WAV의 stdin 평가: 호출 **2/2 수락**, 비호출 **6/6 거부**(“조수야” 포함).
3. 이 음성을 48kHz로 확장하고 앞뒤 200ms 무음을 추가한 뒤 24kHz 필터·에너지 구간 검출: **호출 2/2 수락, 비호출 6/6 거부**. 이미 공개한 같은 합성 음성을 재사용하므로 독립적인 인식률 증거가 아니다.
4. 초기 100ms 패딩에서는 호출어 2개 모두 거부됐다. 기존 음향 프로필이 음성 앞뒤의 문맥에 민감해 400ms 보존으로 조정했다. 이를 인체 음성에 대한 보정으로 해석하지 않는다.
5. 노트북 Realtek 마이크 device 9로 실제 2.5초 1회 시험: NO_SPEECH_ACTIVITY. 호출어 발화가 관찰됐다고 볼 수 없음. 실물 K151 내장 마이크를 사용하지 않았다.
6. Windows에서 로컬 Zig 판별기와 NumPy로 해당 시험 파일 **25개 PASS**. Linux CI에서는 시스템 C++20 컴파일러로 검증하며, Windows CI에 별도 로컬 Zig가 없으면 일부 시험은 SKIP이다.

## 상태 해석

- UNVERIFIED_MATCH: 현재 SWK1 임계값으로 **이 입력에서** 음향 매칭
- UNVERIFIED_NO_MATCH: 음향 입력이 있으나 프로필 매칭 조건 미달
- NO_SPEECH_ACTIVITY: 유의미한 에너지 구간이 감지되지 않음
- OFFLINE_PC_WAKE_TEST_REJECTED: 잘못된 입력/권한/포맷/프로필/프로세스 실행 불가

이 시험은 **실물 K151 wake-word 성공, 사람 목소리 정확도, 오탐률/시간 또는 GPT 대화 연결을 증명하지 않는다.** 출고 펌웨어 USB Serial/JTAG 연결만으로는 새 인식기에 K151 내장 마이크 PCM이 들어오지 않는다. 실제 로봇 wake-word 입력·출력 경로, STOP과 원본 복구 안전성을 확인하기 전에는 설치 HOLD를 해제하지 않는다.

## 이후 실제 발화 실패와 추가 진단

사용자가 직접 “조수”라고 말한 실행에서 `UNVERIFIED_NO_MATCH`, `trimmed_frames_24khz=22080`을 보고했다. 실제 발화 내용/입력 장치/잘림 원인은 확인되지 않았으며0.92초라는 길이만으로 잘림으로 판정하지 않는다. [입력·DTW 진단 및 개인 음성 등록 안내](2026-11-20-josu-human-mic.md)를 추가했다. 최신 Windows 실행기는 device9를 고정하지 않고 현재 목록에서 선택하며 새 C++ helper를 사용한다. 위 이전 관측과 새 기능의 실제 사람 검증을 혼동하지 않는다.
