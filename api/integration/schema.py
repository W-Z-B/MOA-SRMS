"""OpenAPI description of the service-key scheme, so integration endpoints show how they are called."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ServiceKeyScheme(OpenApiAuthenticationExtension):
    target_class = "integration.auth.ServiceKeyAuthentication"
    name = "ServiceKey"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "`Api-Key <key>`, issued by create_service_client with the scopes named.",
        }
