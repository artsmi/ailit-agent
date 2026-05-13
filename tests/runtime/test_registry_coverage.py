"""Unit tests for runtime/registry.py — coverage.

Covers:
- AgentRegistry.register() / remove() / list_agents() / describe()
- AgentRegistry.list_agents() empty / with agents
- AgentRegistry.list_agents() filtered by chat_id
- AgentRegistry.remove() existing agent
- AgentRegistry.remove() non-existing agent (no error)
- AgentRegistry.describe()
"""

from __future__ import annotations

from ailit_runtime.registry import AgentRegistration, AgentRegistry


class TestAgentRegistry:
    def test_register_and_list(self) -> None:
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

    def test_list_agents_empty(self) -> None:
        reg = AgentRegistry()
        assert reg.list_agents() == ()

    def test_list_agents_filter_by_chat_id(self) -> None:
        reg = AgentRegistry()
        a1 = AgentRegistration(
            agent_type="AgentDummy",
            agent_instance_id="dummy-1",
            chat_id="chat-a",
        )
        a2 = AgentRegistration(
            agent_type="AgentDummy",
            agent_instance_id="dummy-2",
            chat_id="chat-b",
        )
        reg.register(a1)
        reg.register(a2)
        agents = reg.list_agents(chat_id="chat-a")
        assert len(agents) == 1
        assert agents[0].agent_instance_id == "dummy-1"

    def test_remove_existing(self) -> None:
        reg = AgentRegistry()
        a1 = AgentRegistration(
            agent_type="AgentDummy",
            agent_instance_id="dummy-1",
            chat_id="chat-a",
        )
        reg.register(a1)
        assert len(reg.list_agents()) == 1
        reg.remove(chat_id="chat-a", agent_instance_id="dummy-1")
        assert reg.list_agents() == ()

    def test_remove_non_existing(self) -> None:
        reg = AgentRegistry()
        # remove() should not raise for non-existing agent
        reg.remove(chat_id="chat-x", agent_instance_id="nonexistent")
        assert reg.list_agents() == ()

    def test_describe(self) -> None:
        reg = AgentRegistry()
        a1 = AgentRegistration(
            agent_type="AgentDummy",
            agent_instance_id="dummy-1",
            chat_id="chat-a",
        )
        reg.register(a1)
        desc = reg.describe(chat_id="chat-a")
        assert desc["agents"][0]["agent_instance_id"] == "dummy-1"

    def test_describe_empty(self) -> None:
        reg = AgentRegistry()
        desc = reg.describe()
        assert desc["agents"] == []
