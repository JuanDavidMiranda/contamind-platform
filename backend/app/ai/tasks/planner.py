from app.ai.tasks.tasks import Task


class TaskPlanner:

    def create_exogena_tasks(self):

        return [

            Task(

                id="1",

                agent="dian",

                objective="Consultar obligaciones DIAN"

            )

        ]