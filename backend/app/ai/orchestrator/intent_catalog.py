from dataclasses import dataclass


@dataclass
class IntentDefinition:

    domain: str
    action: str
    keywords: list[str]


INTENTS = [

    IntentDefinition(
        domain="accounting",
        action="accounting_health",
        keywords=[
            "salud contable",
            "diagnostico contable",
            "diagnóstico contable",
            "revision contable",
            "revisión contable",
        ]
    ),

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
