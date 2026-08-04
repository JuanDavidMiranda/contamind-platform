from dataclasses import dataclass


@dataclass
class Task:

    id: str

    agent: str

    objective: str

    completed: bool = False