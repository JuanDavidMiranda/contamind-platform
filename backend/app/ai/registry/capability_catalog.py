from app.ai.registry import registry


class CapabilityCatalog:

    def resolve(self, message: str):

        message = message.lower()

        for agent_id in registry.list():

            agent = registry.get(agent_id)

            for capability in agent.capabilities:

                for keyword in capability.keywords:

                    if keyword in message:

                        return agent.id

        return "dian"