from app.ai.core.base_result import BaseResult


class WaitingNitState:

    async def execute(self, context):

        context.variables["nit"] = context.user_message

        context.state = "WAITING_FISCAL_YEAR"

        return BaseResult(

            success=True,

            message="Excelente. ¿Cuál es el año gravable?"

        )