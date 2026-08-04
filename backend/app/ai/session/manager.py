from app.ai.core.context import Context


class SessionManager:

    def __init__(self):

        self.sessions: dict[str, Context] = {}

    def get(self, conversation_id: str) -> Context:

        if conversation_id not in self.sessions:

            self.sessions[conversation_id] = Context(
                conversation_id=conversation_id
            )

        return self.sessions[conversation_id]

    def save(self, context: Context):

        self.sessions[context.conversation_id] = context

    def delete(self, conversation_id: str):

        self.sessions.pop(conversation_id, None)