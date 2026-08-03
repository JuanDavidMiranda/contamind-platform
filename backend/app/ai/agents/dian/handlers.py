from app.ai.core.base_result import BaseResult


class DianHandler:

    def handle(self, message: str) -> BaseResult:

        text = message.lower().strip()

        if text in ["hola", "buenas", "buenos días", "buenas tardes"]:
            return BaseResult(
                success=True,
                message=(
                    "¡Hola! 👋 Soy el agente DIAN de ContaMind AI.\n"
                    "Puedo ayudarte con procesos relacionados con la DIAN, "
                    "como exógena, RUT, facturación electrónica y validaciones."
                )
            )

        if "exogena" in text or "exógena" in text:
            return BaseResult(
                success=True,
                message=(
                    "La funcionalidad para descargar y validar la información exógena "
                    "estará disponible próximamente."
                )
            )

        if "rut" in text:
            return BaseResult(
                success=True,
                message=(
                    "En el futuro podré consultar y validar información del RUT."
                )
            )

        return BaseResult(
            success=True,
            message=(
                "No entendí tu solicitud. "
                "¿Puedes reformularla?"
            )
        )