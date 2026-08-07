from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from h2os_cli.channels import setup_feishu


def test_feishu_setup_uses_h2os_home_and_enforces_private_pairing(
    monkeypatch, tmp_path
):
    saved = {}
    values = {"FEISHU_APP_ID": "cli_test", "FEISHU_APP_SECRET": "secret"}

    def interactive_setup(*, private_only=False):
        assert os.environ["HERMES_HOME"] == str(tmp_path.resolve())
        assert private_only is True

    monkeypatch.setitem(
        sys.modules,
        "plugins.platforms.feishu.adapter",
        SimpleNamespace(
            check_feishu_requirements=lambda: True,
            interactive_setup=interactive_setup,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.config",
        SimpleNamespace(
            get_env_value=lambda key: values.get(key, ""),
            save_env_value=lambda key, value: saved.__setitem__(key, value),
        ),
    )

    assert setup_feishu(tmp_path) == 0
    assert saved == {
        "FEISHU_ALLOW_ALL_USERS": "false",
        "FEISHU_ALLOWED_USERS": "",
        "FEISHU_GROUP_POLICY": "disabled",
    }


def test_feishu_setup_rejects_incomplete_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.setitem(
        sys.modules,
        "plugins.platforms.feishu.adapter",
        SimpleNamespace(
            check_feishu_requirements=lambda: True,
            interactive_setup=lambda **_kwargs: None,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "hermes_cli.config",
        SimpleNamespace(
            get_env_value=lambda _key: "",
            save_env_value=lambda _key, _value: None,
        ),
    )

    assert setup_feishu(tmp_path) == 1
    assert "没有完成" in capsys.readouterr().err
