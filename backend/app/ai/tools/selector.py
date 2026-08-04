from app.ai.tools.registry import registry


class ToolSelector:

    def select(self, task):

        objective = task.objective.lower()

        if "rut" in objective:
            return registry.get("Consultar RUT")

        if "obligaciones" in objective:
            return registry.get("Consultar obligaciones")

        raise Exception(
            f"No existe herramienta para '{task.objective}'"
        )