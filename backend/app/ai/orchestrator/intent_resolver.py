class IntentResolver:

    def resolve(self, message: str):

        text = message.lower()

        if "exogena" in text:
            return "EXOGENA"

        if "exógena" in text:
            return "EXOGENA"

        return "GENERAL"