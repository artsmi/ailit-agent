from __future__ import annotations

from agent_core.runtime.registry import AgentRegistration, AgentRegistry


def test_registry_register_list_filter() -> None:
    reg = AgentRegistry()
    a1 = AgentRegistration(
        agent_type="AgentDummy",
        agent_instance_id="dummy-1",
        chat_id="chat-a",
        capabilities=("echo",),
        service_handlers=("dummy.echo",),
        topic_subscriptions=("agent.trace",),
        action_handlers=("dummy.action",),
    )
    a2 = AgentRegistration(
        agent_type="AgentDummy",
        agent_instance_id="dummy-2",
        chat_id="chat-b",
    )
    reg.register(a1)
    reg.register(a2)
    assert len(reg.list_agents()) == 2
    assert len(reg.list_agents(chat_id="chat-a")) == 1
    desc = reg.describe(chat_id="chat-a")
    assert desc["agents"][0]["agent_instance_id"] == "dummy-1"
