import re

from app.ai.extractor.entities import ExtractedEntities


class EntityExtractor:

    def extract(
        self,
        message: str
    ) -> ExtractedEntities:

        entities = ExtractedEntities()

        # --------------------
        # NIT
        # --------------------

        nit = re.search(
            r"\b\d{8,12}\b",
            message
        )

        if nit:

            entities.nit = nit.group()

        # --------------------
        # Año gravable
        # --------------------

        year = re.search(
            r"\b20\d{2}\b",
            message
        )

        if year:

            entities.fiscal_year = int(
                year.group()
            )

        return entities