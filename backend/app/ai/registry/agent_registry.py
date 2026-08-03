from app.ai.core.base_agent import BaseAgent
from app.ai.registry.exceptions import AgentNotFoundException


class AgentRegistry:

    def __init__(self):

        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent):

        self._agents[agent.id] = agent

    def unregister(self, agent_id: str):

        self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> BaseAgent:

        agent = self._agents.get(agent_id)

        if not agent:
            raise AgentNotFoundException(agent_id)

        return agent

    def exists(self, agent_id: str) -> bool:

        return agent_id in self._agents

    def list(self) -> list[str]:

        return list(self._agents.keys())