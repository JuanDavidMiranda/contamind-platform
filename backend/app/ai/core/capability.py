from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:

    name: str

    description: str

    keywords: list[str]