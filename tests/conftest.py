import importlib.util

import pytest


def pytest_collection_modifyitems(config, items):
    """silero_vad/torch 未インストール時に integration マークのテストを自動スキップ。"""
    missing = [
        pkg
        for pkg in ("silero_vad", "torch")
        if importlib.util.find_spec(pkg) is None
    ]
    if not missing:
        return
    reason = f"integration テストには未インストールのパッケージが必要: {', '.join(missing)}"
    skip_mark = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_mark)
