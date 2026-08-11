from pathlib import Path


ASSETS = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"


def test_topic_pool_drawer_has_accessible_controls_and_relationship_copy():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")

    assert "data-topic-pool-trigger" in page
    assert 'aria-label="关闭最近看到的内容"' in page
    assert "最近看到的" in page
    assert "想聊这个" not in page  # actions are rendered from live topic data


def test_companion_product_shell_exposes_user_facing_memory_and_relationship_pages():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")

    assert 'data-view="chat"' in page
    assert 'data-view="memories"' in page
    assert 'data-view="relationship"' in page
    assert 'data-view="history"' in page
    assert 'data-view="settings"' in page
    assert "它记得的事" in page
    assert "双方明确说过的" in page
    assert "记忆保存在本地" in page


def test_topic_pool_script_uses_safe_dom_and_separate_visible_chat_copy():
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/companion/topics"' in script
    assert "textContent" in script
    assert "topic.source_url" in script
    assert "displayText" in script
    assert '"/api/companion/proactive/claim"' in script
    assert "hideUser" in script
    assert "proactiveDeliveryId" in script
    assert ".innerHTML" not in script


def test_topic_pool_styles_include_drawer_cards_and_mobile_layout():
    styles = (ASSETS / "styles.css").read_text(encoding="utf-8")

    assert ".topic-pool-drawer" in styles
    assert ".topic-card" in styles
    assert ".topic-pool-trigger" in styles
    assert "@media (max-width: 720px)" in styles


def test_busy_web_chat_queues_followups_instead_of_dropping_them():
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert "pendingMessages" in script
    assert "processMessageQueue" in script
    assert "这句我也看见了，等我把上一句弄完。" in script
    assert "if (!text || sending) return" not in script
    assert "elements.send.disabled = true" not in script


def test_companion_product_shell_uses_real_memory_profile_and_history_apis():
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert '"/api/companion/profile"' in script
    assert '"/api/companion/new"' in script
    assert '"/api/companion/memories/"' in script
    assert '"/messages"' in script
    assert "companionData.memories" in script
    assert ".innerHTML" not in script


def test_companion_memory_page_names_and_filters_durable_memories():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert 'data-memory-filter="long_term_memory"' in page
    assert 'long_term_memory: "长期记忆"' in script
    assert 'persistent_memory: "来自长期记忆"' in script
    assert 'persistent_user: "来自对你的了解"' in script


def test_companion_shell_uses_one_icon_language_and_stable_avatar_surfaces():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert (ASSETS / "icons.svg").is_file()
    assert 'class="app-icon"' in page
    assert 'href="./icons.svg#chat"' in page
    assert 'data-avatar-surface="companion"' in page
    assert 'data-avatar-surface="user"' in page
    assert "function avatarLabel(" in script
    assert "function setAvatarLabel(" in script


def test_companion_messages_expose_polished_actions_and_activity_disclosure():
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert 'actions.className = "message-actions"' in script
    assert 'wrapper.className = "activity-card"' in script
    assert 'details.className = "activity-steps"' in script
    assert 'summaryButton.className = "activity-summary"' in script


def test_companion_component_styles_cover_tokens_accessibility_and_responsiveness():
    styles = (ASSETS / "styles.css").read_text(encoding="utf-8")

    assert "--radius-control:" in styles
    assert ".app-icon" in styles
    assert ".message-actions" in styles
    assert ".activity-card" in styles
    assert ".composer:focus-within" in styles
    assert ":focus-visible" in styles
    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert "@media (max-width: 720px)" in styles


def test_settings_page_edits_model_and_connects_both_im_channels_by_qr():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")

    assert 'id="model-settings-form"' in page
    assert 'id="model-provider"' in page
    assert 'value="openai-api"' in page
    assert 'value="openrouter"' in page
    assert 'value="deepseek"' in page
    assert 'value="custom"' in page
    assert 'name="base_url"' in page
    assert 'name="model"' in page
    assert 'list="model-options"' in page
    assert 'id="model-options"' in page
    assert 'id="model-discover"' in page
    assert 'name="api_key"' in page
    assert 'type="password"' in page
    assert 'data-channel-link="weixin"' in page
    assert 'data-channel-link="feishu"' in page
    assert page.count("扫码连接") >= 2
    assert 'id="channel-link-dialog"' in page
    assert 'id="channel-link-qr"' in page
    assert "App Secret" not in page
    assert "仍保留在管理后台" not in page


def test_settings_script_saves_model_without_refilling_key_and_polls_qr_link():
    script = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/companion/settings"' in script
    assert '"/api/companion/settings/models"' in script
    assert '"/api/companion/settings/model"' in script
    assert "provider: elements.modelProvider.value" in script
    assert "renderModelOptions" in script
    assert '"/api/companion/channels/" + encodeURIComponent(platform) + "/link"' in script
    assert '"/api/companion/channels/link/" + encodeURIComponent(linkId)' in script
    assert 'elements.modelApiKey.value = ""' in script
    assert "qr_image" in script
    assert "restart_required" in script
    assert ".innerHTML" not in script


def test_settings_styles_cover_editable_cards_qr_dialog_and_mobile_layout():
    styles = (ASSETS / "styles.css").read_text(encoding="utf-8")

    assert ".model-settings-form" in styles
    assert ".channel-settings-grid" in styles
    assert ".channel-link-dialog" in styles
    assert ".channel-link-qr" in styles
    assert "@media (max-width: 720px)" in styles


def test_theme_can_follow_system_or_be_overridden_and_persisted():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    bootstrap = (ASSETS / "file-open.js").read_text(encoding="utf-8")
    script = (ASSETS / "app.js").read_text(encoding="utf-8")
    styles = (ASSETS / "styles.css").read_text(encoding="utf-8")

    assert 'id="theme-select"' in page
    assert 'value="system"' in page
    assert 'value="light"' in page
    assert 'value="dark"' in page
    assert 'window.matchMedia("(prefers-color-scheme: dark)")' in bootstrap
    assert 'window.localStorage.setItem(storageKey, value)' in bootstrap
    assert 'document.documentElement.dataset.theme = resolved' in bootstrap
    assert 'window.HoneyOSTheme.set(elements.themeSelect.value)' in script
    assert ':root[data-theme="dark"]' in styles
    assert ".settings-list { width: min(100%,780px); margin: 0 auto; padding: 22px 0 44px; display: block; }" in styles


def test_history_layout_uses_shared_radii_and_theme_surfaces():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    script = (ASSETS / "app.js").read_text(encoding="utf-8")
    styles = (ASSETS / "styles.css").read_text(encoding="utf-8")

    assert "在这里查看完整记录" in page
    assert "grid-template-columns: minmax(230px,.7fr) minmax(0,1.3fr)" in styles
    assert "border-radius: var(--radius-control)" in styles
    assert ".history-message.assistant { background: var(--surface-muted); }" in styles
    assert ".history-message.user { background: var(--user-message); }" in styles
    assert "message.content.trim().length > 0" in script
    assert "bubble.textContent = message.content.trim()" in script
