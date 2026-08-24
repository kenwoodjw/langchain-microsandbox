# langchain-microsandbox

[![CI](https://github.com/kenwoodjw/langchain-microsandbox/actions/workflows/ci.yml/badge.svg)](https://github.com/kenwoodjw/langchain-microsandbox/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/langchain-microsandbox.svg)](https://pypi.org/project/langchain-microsandbox/)

Community-maintained Microsandbox integration for Deep Agents. It adapts an
existing [`microsandbox.Sandbox`](https://docs.microsandbox.dev/) to the current
Deep Agents `BaseSandbox` interface.

This project targets the current local microVM-based Microsandbox SDK. It does
not use the legacy `PythonSandbox` server/JSON-RPC API.

## Requirements

- Python 3.11 or newer.
- `deepagents>=0.7.0,<0.8.0`.
- `microsandbox>=0.6.8,<0.7.0`.
- A platform supported by Microsandbox: Apple Silicon macOS, glibc-based Linux
  with KVM, or Windows with Windows Hypervisor Platform.
- A sandbox image containing `python3`, because inherited Deep Agents file and
  search operations execute small Python helpers inside the guest.

## Install

```bash
uv add langchain-microsandbox
```

## Usage

Microsandbox's Python SDK is asynchronous, so construct the backend with
`await MicrosandboxSandbox.create(...)`.

```python
from deepagents import create_deep_agent
from microsandbox import Sandbox

from langchain_microsandbox import MicrosandboxSandbox


sandbox = await Sandbox.create(
    "deepagents-session",
    image="python:3.13-slim",
    ephemeral=True,
)
try:
    backend = await MicrosandboxSandbox.create(sandbox)
    agent = create_deep_agent(backend=backend)
    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Create a small Python package and run pytest.",
                }
            ]
        }
    )
finally:
    await sandbox.stop()
```

The adapter does not own the sandbox lifecycle. The application that creates a
sandbox must also stop it and choose the appropriate persistence or removal
policy. In the example above, `ephemeral=True` removes sandbox state when the
sandbox stops.

Both synchronous and asynchronous Deep Agents backend methods are available.
Async calls use the Microsandbox SDK directly. Sync calls use a compatibility
bridge that is safe to call from a thread that already has a running asyncio
event loop.

## Development

Install the locked development environment:

```bash
uv sync --all-groups
```

Run the local checks:

```bash
make check
```

Integration tests start a real ephemeral microVM and require working local
virtualization:

```bash
uv run msb doctor
make integration_test
```

Use `make integration_smoke` for a faster command, timeout, and file-transfer
subset while iterating locally.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete development and release
workflow.

## License

MIT
