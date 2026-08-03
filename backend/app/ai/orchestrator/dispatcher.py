from app.ai.core.base_agent import BaseAgent
from app.ai.registry import registry


class Dispatcher:

    def dispatch(self, agent_id: str) -> BaseAgent:

        return registry.get(agent_id)