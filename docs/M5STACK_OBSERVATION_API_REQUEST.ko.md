# K151 출고 펌웨어 관찰 API 지원 문의 초안 — 게시 취소

**현재 상태: 사용자 요청으로 게시 취소. 발송·이슈 생성·댓글 작성은 하지 않았다.**
사용자는 제조사 문의 대신 직접 연결을 개발하라고 지시했다. 아래 문안은 과거 초안
기록으로만 보관하며, 향후 게시하려면 새로운 명시적 요청이 필요하다.

작성:2026-11-18(Asia/Seoul). **미발송 초안**이다. 당시 사용자가 선택한 방향은
공식 앱 유지·제조사 지원 경로 우선 확인이며, 이 선택을 외부 공개글 게시나
펌웨어 설치 승인으로 취급하지 않는다.

과거 게시 제안 대상: [m5stack/StackChan의 새 GitHub 이슈](https://github.com/m5stack/StackChan/issues/new).
목표는 출고 펌웨어의 지원되는 사진·센서 읽기 통로를 확인하는 것이다.
이미 답변된 커스텀 빌드 인증 문의를 반복하거나 비공개 키 제공을 요청하지 않는다.

## 공개할 제목

```text
Supported read-only camera/sensor access from a PC with stock K151 firmware
```

## 공개할 본문

```text
Hello M5Stack team,

I am developing a PC-side observer for my StackChan K151 and want to retain the stock firmware and StackChan World integration.

The official Monitoring Camera displays video in Avatar mode, and the external MCP endpoint successfully exposes my PC text tools to AI.Agent. I now need one-shot camera images and touch/IMU events from the robot for a read-only observation step. No custom firmware has been installed.

Last recorded versions are firmware V1.6.2 and app v1.2.12; these were not re-queried after the latest reboot. The source reviewed is commit 28b9f0c8bd6acd81cb3c70f1a93c3e373b39d400.

In the public source, Avatar LAN is phone-hosted, its endpoint is announced over the remote channel, and it uses product RSA configuration. AppAvatar::onClose also requests a warm reboot. The public application uses deployment-time server/key configuration.

I understand the limitation explained in issue #134: production authentication is absent from custom public builds. I am seeking a supported stock-firmware interface, not private production keys or an authentication bypass.

Could you clarify:

1. Is there a supported PC API or SDK for a one-shot JPEG and touch/IMU events on stock K151 firmware? If so, where are the protocol and device-owner authentication instructions documented?
2. Can StackChan World relay/export these observations to an authorized PC through a supported interface?
3. Can that observation path coexist with AI.Agent voice, or must Avatar and AI.Agent run separately?

If this is currently unsupported, an explicit confirmation and any supported extension route would help us choose a compatible design.

Thank you.
```

## 공개 범위와 이후 처리

- 포함: 제품명, 마지막으로 기록한 버전, 공개 소스 SHA, 기본 기능 확인, 지원 API 질문.
- 제외: MAC·계정 식별자·접속주소/token·API 키·카메라 영상·원본 flash·백업 해시.
- 실제 게시 전에 사용자에게 위 제목·본문과 외부 공개 게시 대상을 확인받는다.
- 회신이 오면 지원되는 인증·데이터 출처·최신성·모드 공존 조건으로 연결 설계를 갱신한다.
  회신 전까지 현재 관찰 펌웨어의 실물 설치 HOLD를 유지한다.

근거: [추가 경로 검토](validation/2026-11-18-stock-observation-api-review.md),
[실물 확인](validation/2026-11-18-k151-usb-preflight.md),
[기존 인증 답변](https://github.com/m5stack/StackChan/issues/134#issuecomment-6812198686).
