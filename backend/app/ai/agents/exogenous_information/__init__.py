"""Agente de preparación de información exógena."""

__all__ = ["ExogenousInformationAgent"]


def __getattr__(name: str):
    if name == "ExogenousInformationAgent":
        from app.ai.agents.exogenous_information.agent import ExogenousInformationAgent

        return ExogenousInformationAgent
    raise AttributeError(name)
