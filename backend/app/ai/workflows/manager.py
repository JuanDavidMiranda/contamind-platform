from app.ai.workflows.chat.workflow import ChatWorkflow
from app.ai.workflows.accounting_health.workflow import AccountingHealthWorkflow
from app.ai.workflows.receivables.workflow import ReceivablesWorkflow
from app.ai.workflows.exogena.workflow import ExogenaWorkflow


class WorkflowManager:

    def __init__(self):

        self._workflows = {
            "exogena": ExogenaWorkflow(),
            "accounting_health": AccountingHealthWorkflow(),
            "receivables": ReceivablesWorkflow(),
            "chat": ChatWorkflow(),
        }

    def register(self, workflow):

        self._workflows[workflow.id] = workflow

    def get(self, workflow_id):

        if workflow_id not in self._workflows:
            raise ValueError(
                f"Workflow '{workflow_id}' no registrado."
            )

        return self._workflows[workflow_id]

    def list(self):

        return list(self._workflows.keys())


workflow_manager = WorkflowManager()
