from app.ai.core.base_result import BaseResult


class WaitingFiscalYearState:

    async def execute(self, context):

        context.variables["year"] = context.user_message

        context.state = "RUNNING"

        return BaseResult(

            success=True,

            message=(
                f"Perfecto.\n"
                f"Voy a preparar la exógena del año "
                f"{context.variables['year']} "
                f"para la empresa "
                f"{context.variables['nit']}."
            )

        )