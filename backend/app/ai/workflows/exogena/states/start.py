from app.ai.core.base_result import BaseResult


class StartState:

    async def execute(self, context):

        context.state = "WAITING_NIT"

        return BaseResult(

            success=True,

            message="Perfecto. ¿Cuál es el NIT de la empresa?"

        )