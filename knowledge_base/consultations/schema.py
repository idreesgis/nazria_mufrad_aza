"""OpenAPI: the app key header on every operation (except /health/), so generated Android clients send it."""


def add_app_key_header(result, generator, request, public):
    result.setdefault("components", {}).setdefault("securitySchemes", {})
    for path, ops in result.get("paths", {}).items():
        if path.endswith("/health/"):
            continue
        for op in ops.values():
            params = op.setdefault("parameters", [])
            if not any(p.get("name") == "X-Api-Key" for p in params):
                params.insert(0, {"in": "header", "name": "X-Api-Key", "required": True, "schema": {"type": "string"},
                                  "description": "App key (python manage.py create_api_client NAME)"})
    return result
