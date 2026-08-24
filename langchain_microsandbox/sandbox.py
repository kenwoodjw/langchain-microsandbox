"""Microsandbox backend implementation."""

from __future__ import annotations

import asyncio
import shlex
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from fnmatch import fnmatchcase
from functools import cache
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, TypeVar, cast
from uuid import uuid4

from deepagents.backends.protocol import (
    FILE_NOT_FOUND,
    INVALID_PATH,
    IS_DIRECTORY,
    PERMISSION_DENIED,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileOperationError,
    FileUploadResponse,
    GlobResult,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox
from microsandbox import (
    ExecTimeoutError,
    FilesystemError,
    FsEntryKind,
    PathNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine
    from concurrent.futures import Future

    from microsandbox import ExecOutput, FsEntry, Sandbox

_ResultT = TypeVar("_ResultT")
_TIMEOUT_EXIT_CODE = 124
_MAX_GLOB_ENTRIES = 10_000


class MicrosandboxSandbox(BaseSandbox):
    """Microsandbox implementation conforming to `SandboxBackendProtocol`.

    The adapter wraps an existing sandbox. The calling application remains
    responsible for stopping it and choosing its persistence or removal policy.
    """

    def __init__(
        self,
        *,
        sandbox: Sandbox,
        sandbox_id: str,
        timeout: int,
    ) -> None:
        """Initialize an adapter after asynchronous construction.

        Use [`create`][langchain_microsandbox.MicrosandboxSandbox.create] so the
        asynchronous Microsandbox name is cached for the synchronous `id`
        property.

        Args:
            sandbox: Existing Microsandbox instance to wrap.
            sandbox_id: Name resolved from the Microsandbox instance.
            timeout: Default command timeout in seconds.
        """
        self._sandbox = sandbox
        self._id = sandbox_id
        self._default_timeout = timeout

    @classmethod
    async def create(
        cls,
        sandbox: Sandbox,
        *,
        timeout: int = 30 * 60,  # noqa: ASYNC109  # provider execution default
    ) -> MicrosandboxSandbox:
        """Create an adapter around an existing Microsandbox instance.

        Args:
            sandbox: Existing Microsandbox instance to wrap.
            timeout: Default command timeout in seconds used when execution is
                called without an explicit `timeout`.

        Returns:
            An initialized adapter with the sandbox name cached as its `id`.

        Raises:
            ValueError: If `timeout` is negative.
        """
        if timeout < 0:
            msg = f"timeout must be non-negative, got {timeout}"
            raise ValueError(msg)
        # v0.6.12 exposes an awaitable property at runtime even though its stub
        # declares an async method; accept both forms across the supported range.
        name: object = sandbox.name
        if callable(name):
            name_factory = cast("Callable[[], Awaitable[str]]", name)
            sandbox_id = await name_factory()
        else:
            sandbox_id = await cast("Awaitable[str]", name)
        return cls(
            sandbox=sandbox,
            sandbox_id=sandbox_id,
            timeout=timeout,
        )

    @property
    def id(self) -> str:
        """Return the cached Microsandbox name."""
        return self._id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command through the synchronous backend interface.

        Args:
            command: Shell command string to execute.
            timeout: Maximum execution time in seconds. If `None`, use the
                adapter's default timeout.

        Returns:
            The command output and exit status.
        """
        return _run_sync(lambda: self.aexecute(command, timeout=timeout))

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int | None = None,  # noqa: ASYNC109  # forwarded to Microsandbox
    ) -> ExecuteResponse:
        """Execute a shell command through Microsandbox's native async API.

        Args:
            command: Shell command string to execute.
            timeout: Maximum execution time in seconds. If `None`, use the
                adapter's default timeout.

        Returns:
            The command output and exit status. Provider timeouts use shell exit
            code 124, matching the other Deep Agents sandbox integrations.
        """
        effective_timeout = timeout if timeout is not None else self._default_timeout
        try:
            output = await self._sandbox.shell(
                command,
                timeout=float(effective_timeout),
            )
        except ExecTimeoutError:
            msg = f"Command timed out after {effective_timeout} seconds"
            return ExecuteResponse(
                output=msg,
                exit_code=_TIMEOUT_EXIT_CODE,
                truncated=False,
            )
        return _map_execute_output(output)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Create a UTF-8 file without overwriting an existing path.

        Args:
            file_path: Absolute path for the file.
            content: UTF-8 text content to write.

        Returns:
            The created path, or an error if the path already exists or cannot be
            written.
        """
        return _run_sync(lambda: self.awrite(file_path, content))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """Create a UTF-8 file through Microsandbox's async filesystem API.

        Args:
            file_path: Absolute path for the file.
            content: UTF-8 text content to write.

        Returns:
            The created path, or an error if the path already exists or cannot be
            written.
        """
        if not file_path.startswith("/"):
            return WriteResult(error=f"Invalid path: '{file_path}'")

        try:
            error = await self._atomic_write(file_path, content.encode("utf-8"))
        except Exception as exc:
            operation_error = _map_file_error(exc)
            if operation_error is None:
                raise
            error = operation_error
        if error is not None:
            return WriteResult(error=f"Failed to write file '{file_path}': {error}")
        return WriteResult(path=file_path)

    async def _atomic_write(self, path: str, content: bytes) -> str | None:
        parent = str(PurePosixPath(path).parent)
        if parent != "/":
            await self._sandbox.fs.mkdir(parent)
        temp = str(PurePosixPath(parent) / f".microsandbox-{uuid4().hex}.tmp")
        await self._sandbox.fs.write(temp, content)
        command = f"ln -- {shlex.quote(temp)} {shlex.quote(path)}"
        try:
            output = await self._sandbox.shell(
                command,
                timeout=float(self._default_timeout),
            )
        finally:
            with suppress(PathNotFoundError):
                await self._sandbox.fs.remove(temp)
        if output.exit_code == 0:
            return None
        detail = output.stderr_text.strip() or output.stdout_text.strip()
        if "file exists" in detail.lower():
            return "already exists"
        return detail or f"atomic publish exited with code {output.exit_code}"

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Return relative file and directory matches for a glob pattern.

        Args:
            pattern: Glob pattern, relative to `path`.
            path: Absolute directory to search. Defaults to the sandbox root.

        Returns:
            Matching paths relative to the search directory.
        """
        return _run_sync(lambda: self.aglob(pattern, path=path))

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Search files and directories through Microsandbox's filesystem API.

        Args:
            pattern: Glob pattern, relative to `path`.
            path: Absolute directory to search. Defaults to the sandbox root.

        Returns:
            Matching paths relative to the search directory.
        """
        search_path = path or "/"
        if not search_path.startswith("/"):
            return GlobResult(error=f"Path '{search_path}': {INVALID_PATH}")
        if ".." in pattern.replace("\\", "/").split("/"):
            return GlobResult(error=f"Path '{search_path}': invalid_pattern")

        try:
            entries, truncated = await self._list_entries(search_path)
        except Exception as exc:
            error = _map_file_error(exc)
            if error is None:
                raise
            return GlobResult(error=f"Path '{search_path}': {error}")

        matches: list[FileInfo] = []
        root = PurePosixPath(search_path)
        for entry in entries:
            try:
                relative = PurePosixPath(entry.path).relative_to(root).as_posix()
            except ValueError:
                continue
            is_dir = entry.kind == FsEntryKind.DIRECTORY
            if _glob_matches(relative, pattern, is_dir=is_dir):
                matches.append({"path": relative, "is_dir": is_dir})
        matches.sort(key=lambda item: item["path"])
        return GlobResult(matches=matches, truncated=truncated)

    async def _list_entries(self, root: str) -> tuple[list[FsEntry], bool]:
        pending = [root]
        entries: list[FsEntry] = []
        while pending:
            current = pending.pop()
            for entry in await self._sandbox.fs.list(current):
                entries.append(entry)
                if len(entries) >= _MAX_GLOB_ENTRIES:
                    return entries, True
                if entry.kind == FsEntryKind.DIRECTORY:
                    pending.append(entry.path)
        return entries, False

    def upload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]:
        """Upload files through the synchronous backend interface.

        Args:
            files: Absolute sandbox paths paired with file contents.

        Returns:
            One response per input file, in input order.
        """
        return _run_sync(lambda: self.aupload_files(files))

    async def aupload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]:
        """Upload files through Microsandbox's native async filesystem API.

        Args:
            files: Absolute sandbox paths paired with file contents.

        Returns:
            One response per input file, in input order.
        """
        return [await self._aupload_file(path, content) for path, content in files]

    async def _aupload_file(self, path: str, content: bytes) -> FileUploadResponse:
        if not path.startswith("/"):
            return FileUploadResponse(path=path, error=INVALID_PATH)

        try:
            parent = str(PurePosixPath(path).parent)
            if parent != "/":
                await self._sandbox.fs.mkdir(parent)
            await self._sandbox.fs.write(path, content)
        except Exception as exc:
            error = _map_file_error(exc)
            if error is None:
                raise
            return FileUploadResponse(path=path, error=error)
        return FileUploadResponse(path=path, error=None)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files through the synchronous backend interface.

        Args:
            paths: Absolute sandbox paths to download.

        Returns:
            One response per input path, in input order.
        """
        return _run_sync(lambda: self.adownload_files(paths))

    async def adownload_files(
        self,
        paths: list[str],
    ) -> list[FileDownloadResponse]:
        """Download files through Microsandbox's native async filesystem API.

        Args:
            paths: Absolute sandbox paths to download.

        Returns:
            One response per input path, in input order.
        """
        return [await self._adownload_file(path) for path in paths]

    async def _adownload_file(self, path: str) -> FileDownloadResponse:
        if not path.startswith("/"):
            return FileDownloadResponse(path=path, content=None, error=INVALID_PATH)

        try:
            content = await self._sandbox.fs.read(path)
        except Exception as exc:
            error = _map_file_error(exc)
            if error is None:
                raise
            return FileDownloadResponse(
                path=path,
                content=None,
                error=error,
            )
        return FileDownloadResponse(path=path, content=content, error=None)


def _map_execute_output(output: ExecOutput) -> ExecuteResponse:
    """Convert Microsandbox's command result into the Deep Agents response."""
    combined = output.stdout_text
    stderr = output.stderr_text.strip()
    if stderr:
        combined += f"\n<stderr>{stderr}</stderr>"
    return ExecuteResponse(
        output=combined,
        exit_code=output.exit_code,
        truncated=False,
    )


def _map_file_error(exc: Exception) -> FileOperationError | None:
    """Normalize filesystem failures that callers can plausibly fix or retry."""
    if isinstance(exc, PermissionError):
        return PERMISSION_DENIED
    if isinstance(exc, IsADirectoryError):
        return IS_DIRECTORY
    if isinstance(exc, (FileNotFoundError, PathNotFoundError)):
        return FILE_NOT_FOUND

    if not isinstance(exc, FilesystemError):
        return None

    message = str(exc)
    normalized = message.lower()
    substring_errors: tuple[tuple[tuple[str, ...], FileOperationError], ...] = (
        (("permission denied", "access denied", "forbidden"), PERMISSION_DENIED),
        (("is a directory",), IS_DIRECTORY),
        (("invalid path",), INVALID_PATH),
        (("no such file", "not found"), FILE_NOT_FOUND),
    )
    for needles, error in substring_errors:
        if any(needle in normalized for needle in needles):
            return error
    return None


def _glob_matches(path: str, pattern: str, *, is_dir: bool) -> bool:
    """Match a relative POSIX path using the sandbox glob contract."""
    normalized = pattern.lstrip("/")
    if normalized.endswith("/") and not is_dir:
        return False
    pattern_parts = tuple(part for part in normalized.split("/") if part)
    path_parts = tuple(part for part in path.split("/") if part)
    if "/" not in normalized:
        return bool(path_parts) and _segment_matches(path_parts[-1], normalized)
    return _parts_match(path_parts, pattern_parts)


def _segment_matches(name: str, pattern: str) -> bool:
    if name.startswith(".") and not pattern.startswith("."):
        return False
    if pattern.startswith("[^"):
        pattern = "[!" + pattern[2:]
    return fnmatchcase(name, pattern)


def _parts_match(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    @cache
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern):
            return path_index == len(path)
        segment = pattern[pattern_index]
        if segment == "**":
            if match(path_index, pattern_index + 1):
                return True
            return (
                path_index < len(path)
                and not path[path_index].startswith(".")
                and match(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path)
            and _segment_matches(path[path_index], segment)
            and match(path_index + 1, pattern_index + 1)
        )

    return match(0, 0)


def _run_sync(factory: Callable[[], Coroutine[object, object, _ResultT]]) -> _ResultT:
    """Run an async provider call from synchronous code.

    When the current thread already owns a running event loop, both coroutine
    creation and execution happen in a worker thread. This avoids nesting
    `asyncio.run()` in the caller's loop while keeping the bridge stateless.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    def run() -> _ResultT:
        return asyncio.run(factory())

    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="microsandbox-sync",
    ) as executor:
        future: Future[_ResultT] = executor.submit(run)
        return future.result()
