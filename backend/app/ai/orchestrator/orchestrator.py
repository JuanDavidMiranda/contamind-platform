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
    ):

        context.user_message = message

        if context.workflow and context.state != "START":
            workflow_id = context.workflow
        else:
            workflow_id = self.intent_resolver.resolve(message)
            context.workflow = workflow_id

        workflow = workflow_manager.get(workflow_id)

        context.entities = self.extractor.extract(message)

        execution = WorkflowExecution(
            workflow_id=workflow.id
        )

        return await workflow.execute(
            execution,
            context,
        )
