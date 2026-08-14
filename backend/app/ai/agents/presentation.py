"""Texto de presentación para hallazgos verificables de los agentes."""

from collections.abc import Iterable
from typing import Protocol


class FindingForPresentation(Protocol):
    message: str
    recommendation: str


def priority_actions(
    findings: Iterable[FindingForPresentation],
    *,
    severity_values: frozenset[str] = frozenset({"critical", "warning"}),
    maximum: int = 3,
) -> str:
    """Convierte hallazgos técnicos en prioridades y acciones comprensibles."""

    priorities = [
        finding
        for finding in findings
        if getattr(getattr(finding, "severity", None), "value", None)
        in severity_values
    ][:maximum]
    if not priorities:
        return "No hay alertas que requieran atención prioritaria en este momento."

    actions = [
        f"{finding.message.rstrip('.')}. Qué hacer: {finding.recommendation.rstrip('.')}"
        for finding in priorities
    ]
    return "Revisa primero lo siguiente: " + "; ".join(actions) + "."
