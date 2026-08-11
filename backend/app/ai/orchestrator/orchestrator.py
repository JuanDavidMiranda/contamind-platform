from app.ai.core.context import Context
from app.ai.extractor.extractor import EntityExtractor
from app.ai.orchestrator.intent_resolver import IntentResolver
from app.ai.workflows.core.execution import WorkflowExecution
from app.ai.workflows.manager import workflow_manager


class Orchestrator:

    def __init__(self):
        self.intent_resolver = IntentResolver()
        self.extractor = EntityExtractor()

    async def handle_message(
        self,
        message: str,
        context: Context,
        *,
        forced_workflow: str | None = None,
    ):
        context.user_message = message

        if forced_workflow is not None:
            # Los endpoints de agente son explícitos. No dependen de palabras
            # clave ni heredan el estado de otro workflow accidentalmente.
            workflow_id = forced_workflow
            context.workflow = workflow_id
            context.state = "START"
        elif context.workflow and context.state != "START":
            workflow_id = context.workflow
        else:
            workflow_id = self.intent_resolver.resolve(message)
            if workflow_id == "accounting_health" and context.company_id is None:
                # El chat legado es anónimo; nunca debe activar flujos con datos.
                workflow_id = "chat"
            context.workflow = workflow_id

        workflow = workflow_manager.get(workflow_id)

        # El agente no usa entidades; evitamos retener identificadores extraídos
        # de una pregunta que puede contener datos sensibles.
        context.entities = (
            {} if workflow_id == "accounting_health" else self.extractor.extract(message)
        )

        execution = WorkflowExecution(
            workflow_id=workflow.id
        )

        return await workflow.execute(
            execution,
            context,
        )
