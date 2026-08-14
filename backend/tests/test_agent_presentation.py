"""Presentación comprensible de hallazgos en las conversaciones de agentes."""

from types import SimpleNamespace

from app.ai.agents.presentation import priority_actions


def test_priority_actions_uses_messages_and_actions_not_internal_codes():
    findings = (
        SimpleNamespace(
            code="INTERNAL_CODE_MUST_NOT_BE_SHOWN",
            severity=SimpleNamespace(value="warning"),
            message="Hay datos pendientes de revisión",
            recommendation="Completa la información antes de continuar",
        ),
        SimpleNamespace(
            code="SECOND_INTERNAL_CODE",
            severity=SimpleNamespace(value="critical"),
            message="Hay una inconsistencia que requiere atención",
            recommendation="Revisa el soporte con una persona autorizada",
        ),
    )

    response = priority_actions(findings)

    assert response == (
        "Revisa primero lo siguiente: Hay datos pendientes de revisión. Qué hacer: "
        "Completa la información antes de continuar; Hay una inconsistencia que requiere "
        "atención. Qué hacer: Revisa el soporte con una persona autorizada."
    )
    assert "INTERNAL_CODE" not in response


def test_priority_actions_explains_when_no_priority_requires_attention():
    response = priority_actions(
        (
            SimpleNamespace(
                severity=SimpleNamespace(value="info"),
                message="Información disponible",
                recommendation="No requiere acción",
            ),
        )
    )

    assert response == "No hay alertas que requieran atención prioritaria en este momento."
