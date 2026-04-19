"""L.1: файловый mailbox команд (два агента, tmp_path, конкуренция)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ailit.teams.mailbox import TeamRootSelector, TeamSession


def test_two_agents_exchange_in_project_scope(tmp_path: Path) -> None:
    """Alice пишет Bob; Bob читает inbox; ответ обратно."""
    teams_parent = TeamRootSelector.for_project(tmp_path)
    team = TeamSession(teams_parent, "crew1")
    team.send("alice", "bob", "ping")
    bob_msgs = team.inbox("bob")
    assert len(bob_msgs) == 1
    assert bob_msgs[0].from_agent == "alice"
    assert bob_msgs[0].to_agent == "bob"
    assert bob_msgs[0].text == "ping"
    assert bob_msgs[0].read is False
    team.send("bob", "alice", "pong")
    alice_msgs = team.inbox("alice")
    assert len(alice_msgs) == 1
    assert alice_msgs[0].text == "pong"
    raw = (team.team_dir / "inboxes" / "bob.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["messages"][0]["from"] == "alice"


def test_global_state_teams_root_respects_env(tmp_path: Path) -> None:
    """Глобальный корень ``teams`` под выданным ``AILIT_STATE_DIR``."""
    state = tmp_path / "st"
    state.mkdir(parents=True, exist_ok=True)
    root = TeamRootSelector.for_global_state({"AILIT_STATE_DIR": str(state)})
    assert root == (state / "teams").resolve()
    team = TeamSession(root, "g1")
    team.send("a", "b", "hi")
    assert (root / "g1" / "inboxes" / "b.json").is_file()


def test_concurrent_appends_to_same_inbox(tmp_path: Path) -> None:
    """Несколько потоков дописывают в один inbox без порчи JSON."""
    team = TeamSession(TeamRootSelector.for_project(tmp_path), "c1")
    barrier = threading.Barrier(4)

    def worker(name: str) -> None:
        barrier.wait()
        for i in range(8):
            team.send(name, "hub", f"{name}-{i}")

    threads = [
        threading.Thread(target=worker, args=(f"t{k}",), daemon=True)
        for k in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    hub = team.inbox("hub")
    assert len(hub) == 32
    texts = {m.text for m in hub}
    assert len(texts) == 32


def test_mark_all_read(tmp_path: Path) -> None:
    """Пометка прочитанным."""
    team = TeamSession(TeamRootSelector.for_project(tmp_path), "r1")
    team.send("x", "y", "one")
    assert team.inbox("y")[0].read is False
    n = team.mark_all_read("y")
    assert n == 1
    assert team.inbox("y")[0].read is True
