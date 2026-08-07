from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


def test_public_identity_is_honeyos() -> None:
    spec = importlib.util.find_spec("honeyos")
    assert spec is not None, "the standalone honeyos package must exist"

    honeyos = importlib.import_module("honeyos")
    assert honeyos.PRODUCT_NAME == "HoneyOS"
    assert honeyos.RUNTIME_ID.startswith("honeyos-companion-")
    assert Path(honeyos.default_home()).name == ".honeyos"

