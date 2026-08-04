from app.ai.tools import registry

from app.ai.tools.implementations.consultar_obligaciones import (
    ConsultarObligacionesTool,
)


def bootstrap():

    registry.register(
        ConsultarObligacionesTool()
    )