from __future__ import annotations

from pathlib import Path

from honeyos.cli import service


def test_service_lifecycle_never_addresses_an_existing_other_agent(tmp_path: Path) -> None:
    sentinel = tmp_path / ".other-agent" / "marker"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"do-not-touch")
    identity = service.ServiceIdentity.default(tmp_path / ".honeyos")
    calls: list[tuple[str, ...]] = []

    def record(argv, **_kwargs):
        calls.append(tuple(argv))
        return 0

    service.start_service(identity, runner=record)
    service.stop_service(identity, runner=record)

    assert sentinel.read_bytes() == b"do-not-touch"
    assert calls
    expected_service = (
        identity.macos_label
        if service.platform.system() == "Darwin"
        else identity.linux_unit
    )
    assert all(expected_service in " ".join(call) for call in calls)
