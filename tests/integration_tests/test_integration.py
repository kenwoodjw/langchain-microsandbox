from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from langchain_tests.integration_tests import SandboxIntegrationTests
from microsandbox import Sandbox

from langchain_microsandbox import MicrosandboxSandbox

if TYPE_CHECKING:
    from collections.abc import Iterator

    from deepagents.backends.protocol import SandboxBackendProtocol

TIMEOUT_EXIT_CODE = 124
TIMEOUT_SECONDS = 1


async def _create_sandbox(name: str) -> Sandbox:
    return await Sandbox.create(
        name,
        image="python:3.13-slim",
        ephemeral=True,
    )


async def _stop_sandbox(sandbox: Sandbox) -> None:
    name = sandbox.name
    if inspect.isawaitable(name):
        name = await name
    await sandbox.stop()

    page = await Sandbox.list()
    if name in {item.name for item in page.sandboxes}:
        await Sandbox.remove(name)
        page = await Sandbox.list()
    assert name not in {item.name for item in page.sandboxes}


class TestMicrosandboxSandboxStandard(SandboxIntegrationTests):
    @classmethod
    @pytest.fixture(scope="class")
    def sandbox_backend(
        cls,
        sandbox: SandboxBackendProtocol,
    ) -> SandboxBackendProtocol:
        return sandbox

    @classmethod
    @pytest.fixture(scope="class")
    def sandbox(cls) -> Iterator[SandboxBackendProtocol]:
        sandbox = asyncio.run(
            _create_sandbox(f"deepagents-integration-{uuid4().hex[:8]}")
        )
        try:
            backend = asyncio.run(MicrosandboxSandbox.create(sandbox))
            yield backend
        finally:
            asyncio.run(_stop_sandbox(sandbox))

    async def test_aexecute_timeout_maps_to_exit_124(
        self,
        sandbox_backend: SandboxBackendProtocol,
    ) -> None:
        result = await sandbox_backend.aexecute("sleep 5", timeout=TIMEOUT_SECONDS)

        assert result.exit_code == TIMEOUT_EXIT_CODE
        assert result.output == f"Command timed out after {TIMEOUT_SECONDS} seconds"
