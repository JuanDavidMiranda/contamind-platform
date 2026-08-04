from dataclasses import dataclass


@dataclass
class ExtractedEntities:

    nit: str | None = None

    fiscal_year: int | None = None

    company_name: str | None = None

    email: str | None = None