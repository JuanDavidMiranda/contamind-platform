from app.shared.error_catalog import ERROR_CATALOG, get_error_definition

REQUIRED_CODES = {
    "VALIDATION_ERROR",
    "AUTH_MISSING_TOKEN",
    "AUTH_INVALID_TOKEN",
    "AUTH_EXPIRED_TOKEN",
    "AUTH_INVALID_CREDENTIALS",
    "FORBIDDEN",
    "NOT_FOUND",
    "CONFLICT",
    "DEPENDENCY_DISABLED",
    "SERVICE_UNAVAILABLE",
    "INTERNAL_ERROR",
}


def test_catalog_is_not_empty():
    assert ERROR_CATALOG


def test_catalog_contains_required_codes():
    assert REQUIRED_CODES <= set(ERROR_CATALOG)


def test_every_entry_is_consistent():
    for code, definition in ERROR_CATALOG.items():
        assert definition.code == code
        assert 400 <= definition.http_status < 600
        assert definition.message
        assert isinstance(definition.recoverable, bool)


def test_recoverable_flag_classifies_errors():
    for definition in ERROR_CATALOG.values():
        if definition.code == "INTERNAL_ERROR":
            assert definition.recoverable is False


def test_unknown_code_falls_back_to_internal():
    definition = get_error_definition("CODIGO_INEXISTENTE")
    assert definition.code == "INTERNAL_ERROR"
    assert definition.http_status == 500
    assert definition.recoverable is False
