from app.ai.workflows.core.base_workflow import BaseWorkflow


class WorkflowRegistry:

    def __init__(self):

        self._workflows: dict[str, BaseWorkflow] = {}

    def register(self, workflow: BaseWorkflow):

        self._workflows[workflow.id] = workflow

    def get(self, workflow_id: str):

        return self._workflows[workflow_id]

    def list(self):

        return list(self._workflows.keys())