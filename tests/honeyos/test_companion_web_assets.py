from pathlib import Path


ASSETS = Path(__file__).parents[2] / "honeyos" / "companion" / "web_assets"


def test_topic_pool_drawer_has_accessible_controls_and_relationship_copy():
    page = (ASSETS / "index.html").read_text(encoding="utf-8")

    assert "data-topic-pool-trigger" in page
    assert 'aria-label="关闭最近看到的内容"' in page
    assert "最近看到的" in page
    assert "想聊这个" not in page  # actions are rendered from live topic data


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
