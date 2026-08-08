from __future__ import annotations


def test_model_switch_error_never_leaks_internal_translation_key(monkeypatch):
    from honeyos.agent.i18n import reset_language_cache, t

    monkeypatch.setenv("HONEYOS_LANGUAGE", "zh")
    reset_language_cache()
    try:
        rendered = t("gateway.model.error_prefix", error="找不到这个模型")
    finally:
        reset_language_cache()

    assert rendered != "gateway.model.error_prefix"
    assert "找不到这个模型" in rendered
