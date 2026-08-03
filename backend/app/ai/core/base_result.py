from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseResult:

    success: bool

    message: str

    data: dict[str, Any] = field(default_factory=dict)

    errors: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)