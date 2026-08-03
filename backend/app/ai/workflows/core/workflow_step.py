from dataclasses import dataclass


@dataclass
class WorkflowStep:

    order: int

    name: str

    agent: str

    description: str