from app.ai.core.context import Context
from app.ai.core.base_result import BaseResult
from app.ai.orchestrator.intent_resolver import IntentResolver
from app.ai.orchestrator.workflow_resolver import WorkflowResolver
from app.ai.workflows import workflow_registry


class Orchestrator:

    def __init__(self):

        self.intent_resolver = IntentResolver()
        self.workflow_resolver = WorkflowResolver()

    async def handle_message(
        self,
        message: str,
        context: Context
    ) -> BaseResult:

        # 1. Obtener la intención del usuario
        intent = self.intent_resolver.resolve(message)

        # 2. Resolver qué workflow ejecutar
        workflow_id = self.workflow_resolver.resolve(intent)

        # 3. Obtener el workflow registrado
        workflow = workflow_registry.get(workflow_id)

        # 4. Ejecutar el workflow
        return await workflow.execute(context)