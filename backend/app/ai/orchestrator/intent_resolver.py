class IntentResolver:

    def resolve(self, message: str) -> str:

        message = message.lower()

        if "hola" in message:
            return "dian"

        if "exogena" in message:
            return "dian"

        if "exógena" in message:
            return "dian"

        return "dian"