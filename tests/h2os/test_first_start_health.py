from __future__ import annotations

from h2os_cli.config import initialize_home
from h2os_cli.health import first_start_report
from h2os_cli.setup import ModelChoice, configure_model


def test_first_start_report_checks_required_state_and_keeps_optional_tools_optional(tmp_path):
    initialize_home(tmp_path)
    configure_model(
        tmp_path,
        ModelChoice(
            provider="custom",
            model="test-model",
            base_url="https://api.example.com/v1",
            key_env="H2OS_MODEL_API_KEY",
        ),
        "do-not-print-this-key",
    )
    with (tmp_path / ".env").open("a", encoding="utf-8") as handle:
        handle.write(
            "WEIXIN_ACCOUNT_ID=account\n"
            "WEIXIN_TOKEN=token\n"
            "WEIXIN_ALLOWED_USERS=owner\n"
        )

    report = first_start_report(tmp_path, command_lookup=lambda _name: None)
    rendered = report.render()

    assert report.ready is True
    assert "do-not-print-this-key" not in rendered
    assert "模型与 API Key" in rendered
    assert "微信已绑定" in rendered
    assert "至少一个 IM 已连接" in rendered
    assert "Docker 未安装" in rendered
    assert "Computer Use 未安装" in rendered


def test_first_start_report_fails_when_weixin_credentials_are_missing(tmp_path):
    initialize_home(tmp_path)
    configure_model(
        tmp_path,
        ModelChoice(
            provider="custom",
            model="test-model",
            base_url="https://api.example.com/v1",
            key_env="H2OS_MODEL_API_KEY",
        ),
        "key",
    )

    report = first_start_report(tmp_path, command_lookup=lambda _name: "/bin/tool")

    assert report.ready is False
    assert "微信和飞书均未连接" in report.render()


def test_first_start_report_accepts_feishu_as_the_only_im(tmp_path):
    initialize_home(tmp_path)
    configure_model(
        tmp_path,
        ModelChoice(
            provider="custom",
            model="test-model",
            base_url="https://api.example.com/v1",
            key_env="H2OS_MODEL_API_KEY",
        ),
        "key",
    )
    with (tmp_path / ".env").open("a", encoding="utf-8") as handle:
        handle.write("FEISHU_APP_ID=cli_test\nFEISHU_APP_SECRET=secret\n")

    report = first_start_report(tmp_path, command_lookup=lambda _name: None)

    assert report.ready is True
    assert "飞书已连接" in report.render()


def test_first_start_report_rejects_empty_credentials(tmp_path):
    initialize_home(tmp_path)
    config = __import__("yaml").safe_load((tmp_path / "config.yaml").read_text())
    config["model"] = {
        "default": "test-model",
        "provider": "h2os-model",
        "base_url": "https://api.example.com/v1",
    }
    config["providers"] = {
        "h2os-model": {"key_env": "H2OS_MODEL_API_KEY"}
    }
    (tmp_path / "config.yaml").write_text(
        __import__("yaml").safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "H2OS_MODEL_API_KEY=\n"
        "WEIXIN_ACCOUNT_ID=account\n"
        "WEIXIN_TOKEN=token\n"
        "WEIXIN_ALLOWED_USERS=\n",
        encoding="utf-8",
    )

    report = first_start_report(tmp_path, command_lookup=lambda _name: None)

    assert report.ready is False
    assert "模型或 API Key 尚未配置" in report.render()
    assert "微信和飞书均未连接" in report.render()
