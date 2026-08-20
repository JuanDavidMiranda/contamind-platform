from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDefinition:
    code: str
    http_status: int
    message: str
    recoverable: bool


ERROR_CATALOG: dict[str, ErrorDefinition] = {
    "VALIDATION_ERROR": ErrorDefinition(
        code="VALIDATION_ERROR",
        http_status=422,
        message="Datos de entrada inválidos.",
        recoverable=True,
    ),
    "AUTH_MISSING_TOKEN": ErrorDefinition(
        code="AUTH_MISSING_TOKEN",
        http_status=401,
        message="Token de acceso requerido.",
        recoverable=True,
    ),
    "AUTH_INVALID_TOKEN": ErrorDefinition(
        code="AUTH_INVALID_TOKEN",
        http_status=401,
        message="Token inválido.",
        recoverable=True,
    ),
    "AUTH_EXPIRED_TOKEN": ErrorDefinition(
        code="AUTH_EXPIRED_TOKEN",
        http_status=401,
        message="Token vencido.",
        recoverable=True,
    ),
    "AUTH_INVALID_CREDENTIALS": ErrorDefinition(
        code="AUTH_INVALID_CREDENTIALS",
        http_status=401,
        message="Correo o contraseña inválidos.",
        recoverable=True,
    ),
    "AUTH_PASSWORD_CHANGE_REQUIRED": ErrorDefinition(
        code="AUTH_PASSWORD_CHANGE_REQUIRED",
        http_status=403,
        message="Debes cambiar la contraseña temporal antes de continuar.",
        recoverable=True,
    ),
    "FORBIDDEN": ErrorDefinition(
        code="FORBIDDEN",
        http_status=403,
        message="Acceso denegado.",
        recoverable=False,
    ),
    "NOT_FOUND": ErrorDefinition(
        code="NOT_FOUND",
        http_status=404,
        message="Recurso no encontrado.",
        recoverable=True,
    ),
    "CONFLICT": ErrorDefinition(
        code="CONFLICT",
        http_status=409,
        message="El recurso ya existe o está en conflicto.",
        recoverable=True,
    ),
    "DEPENDENCY_DISABLED": ErrorDefinition(
        code="DEPENDENCY_DISABLED",
        http_status=503,
        message="La funcionalidad solicitada está deshabilitada.",
        recoverable=True,
    ),
    "SERVICE_UNAVAILABLE": ErrorDefinition(
        code="SERVICE_UNAVAILABLE",
        http_status=503,
        message="El servicio no está disponible temporalmente.",
        recoverable=True,
    ),
    "PROVIDER_AUTH_FAILED": ErrorDefinition(
        code="PROVIDER_AUTH_FAILED",
        http_status=401,
        message="No fue posible autenticar con el proveedor.",
        recoverable=True,
    ),
    "PROVIDER_RATE_LIMITED": ErrorDefinition(
        code="PROVIDER_RATE_LIMITED",
        http_status=429,
        message="El proveedor alcanzó su límite de solicitudes.",
        recoverable=True,
    ),
    "PROVIDER_UNREACHABLE": ErrorDefinition(
        code="PROVIDER_UNREACHABLE",
        http_status=503,
        message="No fue posible comunicarse con el proveedor.",
        recoverable=True,
    ),
    "PROVIDER_ERROR": ErrorDefinition(
        code="PROVIDER_ERROR",
        http_status=502,
        message="El proveedor respondió con un error.",
        recoverable=True,
    ),
    "INTERNAL_ERROR": ErrorDefinition(
        code="INTERNAL_ERROR",
        http_status=500,
        message="Ocurrió un error interno del servidor.",
        recoverable=False,
    ),
}


def get_error_definition(code: str) -> ErrorDefinition:
    return ERROR_CATALOG.get(code, ERROR_CATALOG["INTERNAL_ERROR"])
