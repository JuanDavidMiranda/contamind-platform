class AgentNotFoundException(Exception):

    def __init__(self, agent_id: str):
        super().__init__(
            f"Agent '{agent_id}' is not registered."
        )