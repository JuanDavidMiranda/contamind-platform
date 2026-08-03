from app.ai.workflows.exogena.workflow import ExogenaWorkflow


class WorkflowManager:

    def __init__(self):

        self.workflows = {

            "exogena": ExogenaWorkflow()

        }

    def get(self, workflow_id):

        return self.workflows[workflow_id]