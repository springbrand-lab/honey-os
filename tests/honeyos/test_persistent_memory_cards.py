from __future__ import annotations

from honeyos.companion.persistent_memory import (
    forget_persistent_memory,
    list_persistent_memories,
)


def test_existing_memory_file_is_exposed_as_long_term_cards(tmp_path):
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text(
        "用户喜欢晚上散步。\n§\n我们一起完成过第一次发布。",
        encoding="utf-8",
    )

    cards = list_persistent_memories(tmp_path)

    assert [card.content for card in cards] == [
        "用户喜欢晚上散步。",
        "我们一起完成过第一次发布。",
    ]
    assert all(card.id.startswith("persistent_") for card in cards)
    assert all(card.kind == "long_term_memory" for card in cards)
    assert all(card.evidence == "persistent_memory" for card in cards)
    assert cards[0].id != cards[1].id


def test_forgetting_persistent_card_removes_only_matching_memory(tmp_path):
    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()
    memory_path = memory_dir / "MEMORY.md"
    memory_path.write_text(
        "用户喜欢晚上散步。\n§\n我们一起完成过第一次发布。",
        encoding="utf-8",
    )
    first, second = list_persistent_memories(tmp_path)

    assert forget_persistent_memory(tmp_path, first.id) is True

    assert memory_path.read_text(encoding="utf-8") == second.content
    assert [card.id for card in list_persistent_memories(tmp_path)] == [second.id]
    assert forget_persistent_memory(tmp_path, first.id) is False


def test_empty_or_missing_memory_file_returns_no_cards(tmp_path):
    assert list_persistent_memories(tmp_path) == ()

    memory_dir = tmp_path / "memories"
    memory_dir.mkdir()
    (memory_dir / "MEMORY.md").write_text("", encoding="utf-8")

    assert list_persistent_memories(tmp_path) == ()
