from dataclasses import dataclass


@dataclass
class Intent:

    domain: str

    action: str

    confidence: float