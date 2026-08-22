# Contributing

## Set up the environment

Install [`uv`](https://docs.astral.sh/uv/) and sync the locked environment:

```bash
uv sync --all-groups
```

Do not use `pip`, Poetry, or Conda to modify this project's environment or lock
file.

## Run checks

```bash
make check
```

Unit tests do not use the network or start a microVM. Integration tests require
a platform supported by Microsandbox and start an ephemeral sandbox:

```bash
uv run msb doctor
make integration_smoke
```

The manual `Integration` GitHub Actions workflow runs this smoke suite on a
self-hosted Apple Silicon Mac or KVM-enabled Linux host. GitHub-hosted runners
do not expose the nested virtualization required to start a microVM.

`make integration_test` runs the complete upstream `langchain-tests` sandbox
conformance suite as a non-blocking compatibility canary. Contract changes in
that independently versioned suite may require coordination with Deep Agents
before the whole canary is green.

Every feature or bug fix should include deterministic tests. Preserve the
public `MicrosandboxSandbox` interface unless a breaking release is explicitly
planned.

## Releases

1. Update `version` in `pyproject.toml` and `__version__` in
   `langchain_microsandbox/_version.py`.
2. Add the release to `CHANGELOG.md`.
3. Run all checks and integration smoke tests.
4. Create a GitHub release whose tag exactly matches `v<version>`.
5. The release workflow builds the distributions and publishes them to PyPI
   through Trusted Publishing.

Publishing is protected by the `pypi` GitHub environment and does not use a
long-lived PyPI API token.
