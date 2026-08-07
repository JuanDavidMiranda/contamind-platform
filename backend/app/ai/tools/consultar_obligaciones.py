from app.ai.tools.base_tool import BaseTool

from app.ai.core.base_result import BaseResult


class ConsultarObligacionesTool(BaseTool):

    name = "Consultar obligaciones"

    description = "Consulta obligaciones tributarias. (MOCK)"

    is_mock = True


    async def execute(self, context):

        return BaseResult(

            success=True,

            message="Consulta de obligaciones simulada (MOCK)."

        )