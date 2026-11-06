import asyncio
import time

import pytest
from http_gateway import running_gateway

from stackchan_autonomy.mcp_contract import MCPFailure
from stackchan_autonomy.mcp_robot import MCPRobotAdapter
from stackchan_autonomy.models import RobotCommand


@pytest.fixture(autouse=True)
def loopback_proxy_exemption(monkeypatch):
    # Only the test-owned loopback socket bypasses proxy routing; external trust is unchanged.
    import os

    current = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    value = ",".join(filter(None, [current, "127.0.0.1", "localhost"]))
    monkeypatch.setenv("NO_PROXY", value)
    monkeypatch.setenv("no_proxy", value)


async def test_http_sdk_roundtrip_and_remote_physical_guards():
    baseline = len(asyncio.all_tasks())
    async with running_gateway() as service:
        async with MCPRobotAdapter.connect(
            service.url, headers=service.headers, timeout_s=2
        ) as adapter:
            assert (await adapter.discover()).connected
            status = await adapter.status()
            assert (status.yaw, status.pitch) == (0, 45)
            assert adapter.physical is True
            before = service.post_attempts
            with pytest.raises(PermissionError):
                await adapter.execute(RobotCommand(kind="move", yaw=5, pitch=45))
            with pytest.raises(PermissionError):
                await adapter.capture()
            assert service.post_attempts == before
            assert not service.gateway.robot.history
    await asyncio.sleep(0)
    assert len(asyncio.all_tasks()) <= baseline


@pytest.mark.parametrize("headers", [None, {"Authorization": "Bearer wrong-fixture-token"}])
async def test_http_missing_or_wrong_auth_is_fixed_failure_without_retries(headers, caplog):
    async with running_gateway() as service:
        with pytest.raises(MCPFailure):
            async with MCPRobotAdapter.connect(service.url, headers=headers, timeout_s=1):
                pytest.fail("unauthorized connection yielded an adapter")
        assert service.post_attempts == 1
        assert not service.rpc
        assert service.token not in caplog.text


@pytest.mark.parametrize("fault", ["expired", "drop", "revoked"])
async def test_http_fault_latches_old_adapter_and_explicit_reconnect_is_fresh(fault):
    async with running_gateway() as service:
        adapter = None
        with pytest.raises(MCPFailure):
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=1
            ) as adapter:
                await adapter.status()
                if fault == "revoked":
                    service.authorized = False
                else:
                    service.fault = fault
                await adapter.status()
        assert adapter is not None and adapter.faulted
        before = service.post_attempts
        with pytest.raises(MCPFailure):
            await adapter.status()
        assert service.post_attempts == before
        service.authorized = True
        async with MCPRobotAdapter.connect(
            service.url, headers=service.headers, timeout_s=2
        ) as fresh:
            assert fresh is not adapter and not fresh.faulted
            assert (await fresh.status()).connected
        assert not service.gateway.robot.history
        assert sum(method == "initialize" for method, _ in service.rpc) == 2


async def test_http_stall_is_bounded_and_does_not_replay_rpc():
    async with running_gateway() as service:
        with pytest.raises(MCPFailure):
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=1
            ) as adapter:
                await adapter.status()
                service.fault = "stall"
                start = time.monotonic()
                await adapter.status()
        assert time.monotonic() - start < 4
        assert service.stall_entered.is_set()
        assert adapter.faulted
        assert sum(tool == "get_head_angles" for _, tool in service.rpc) == 2


async def test_http_identity_change_requires_manual_new_adapter():
    async with running_gateway() as service:
        with pytest.raises(MCPFailure):
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=2
            ) as old:
                await old.status()
                service.gateway.session_id = "replacement-session"
                await old.status()
        assert old.faulted
        async with MCPRobotAdapter.connect(
            service.url, headers=service.headers, timeout_s=2
        ) as fresh:
            assert (await fresh.status()).connected


async def test_http_caller_cancellation_propagates_and_closes_connection():
    async with running_gateway() as service:
        holder = []

        async def client():
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=2
            ) as adapter:
                holder.append(adapter)
                service.fault = "stall"
                await adapter.status()

        task = asyncio.create_task(client())
        await asyncio.wait_for(service.stall_entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert holder[0].faulted


async def test_http_context_preserves_consumers_own_error():
    failure = ValueError("consumer error sentinel")
    async with running_gateway() as service:
        with pytest.raises(ValueError) as raised:
            async with MCPRobotAdapter.connect(service.url, headers=service.headers, timeout_s=2):
                raise failure
        assert raised.value is failure


async def test_http_cross_origin_redirect_does_not_forward_authorization():
    async with running_gateway() as target, running_gateway() as service:
        with pytest.raises(MCPFailure):
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=2
            ) as adapter:
                service.fault = "redirect"
                service.redirect_url = target.url
                await adapter.status()
        assert target.post_attempts == 0
        assert not target.rpc


async def test_http_malformed_response_does_not_leak_raw_body_via_sdk_logs(caplog):
    import logging

    async with running_gateway() as service:
        with pytest.raises(MCPFailure) as raised:
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=1
            ) as adapter:
                service.fault = "bad_json"
                await adapter.status()
        assert "private-upstream-content" not in str(raised.value)
        assert "private-upstream-content" not in caplog.text
    logging.getLogger("mcp.client.streamable_http").warning("unrelated transport diagnostics")
    assert "unrelated transport diagnostics" in caplog.text


@pytest.mark.parametrize("timeout", [0, -1, 121, float("nan"), True])
async def test_http_invalid_timeout_is_rejected_before_network_io(timeout):
    async with running_gateway() as service:
        with pytest.raises(ValueError):
            async with MCPRobotAdapter.connect(
                service.url, headers=service.headers, timeout_s=timeout
            ):
                pytest.fail("invalid timeout accepted")
        assert service.post_attempts == 0
