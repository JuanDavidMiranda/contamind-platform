__all__ = ["ElectronicInvoicingAgent"]


def __getattr__(name: str):
    """Evita cargar el agente cuando un servicio solo necesita sus esquemas."""

    if name == "ElectronicInvoicingAgent":
        from app.ai.agents.electronic_invoicing.agent import ElectronicInvoicingAgent

        return ElectronicInvoicingAgent
    raise AttributeError(name)
