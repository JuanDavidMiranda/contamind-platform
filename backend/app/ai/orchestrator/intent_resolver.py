from app.ai.orchestrator.intent_catalog import INTENTS


class IntentResolver:

    def resolve(self, message: str) -> str:

        text = message.lower()

        for definition in INTENTS:

            for keyword in definition.keywords:

                if keyword in text:
                    return definition.action

        return "chat"