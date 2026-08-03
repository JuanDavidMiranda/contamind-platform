class WorkflowResolver:

    def resolve(self, intent: str) -> str:

        mapping = {

            "EXOGENA": "exogena"

        }

        return mapping[intent]