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
