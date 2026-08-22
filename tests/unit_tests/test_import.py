from __future__ import annotations

from importlib.metadata import version

import langchain_microsandbox


def test_import_microsandbox() -> None:
    assert langchain_microsandbox is not None
    assert langchain_microsandbox.__version__ == version("langchain-microsandbox")
