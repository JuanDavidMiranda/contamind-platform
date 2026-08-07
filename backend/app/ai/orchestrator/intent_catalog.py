from dataclasses import dataclass


@dataclass
class IntentDefinition:

    domain: str
    action: str
    keywords: list[str]


INTENTS = [

    IntentDefinition(
        domain="dian",
        action="exogena",
        keywords=[
            "exogena",
            "exógena",
            "medios magnéticos"
        ]
    )

]
