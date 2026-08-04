from app.ai.workflows.core.base_workflow import BaseWorkflow

from app.ai.workflows.exogena.states.start import StartState
from app.ai.workflows.exogena.states.waiting_nit import WaitingNitState
from app.ai.workflows.exogena.states.waiting_fisical_year import WaitingFiscalYearState


class ExogenaWorkflow(BaseWorkflow):

    id = "exogena"

    name = "Exógena"

    description = "Workflow para la generación de información exógena."

    async def execute(
        self,
        execution,
        context
    ):

        states = {

            "START": StartState(),

            "WAITING_NIT": WaitingNitState(),

            "WAITING_FISCAL_YEAR": WaitingFiscalYearState()

        }

        state = states[context.state]

        return await state.execute(context)