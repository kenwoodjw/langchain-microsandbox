# Changelog

## 0.0.2 - 2026-08-24

- Match the current sandbox standard contract by refusing to overwrite files.
- Return relative `glob` matches and include matching directories.
- Propagate unknown Microsandbox filesystem errors instead of normalizing them
  into retryable operation results.
- Run the complete `SandboxIntegrationTests` suite on self-hosted microVM
  runners.

## 0.0.1 - 2026-08-23

- Add `MicrosandboxSandbox`, a current Deep Agents `BaseSandbox` adapter for
  existing `microsandbox.Sandbox` instances.
- Support native async and event-loop-safe synchronous command execution.
- Support native file upload and download with ordered per-file results.
- Normalize command timeouts and file operation errors.
