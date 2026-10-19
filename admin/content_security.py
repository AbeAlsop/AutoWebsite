"""Browser isolation for untrusted generated documents, including SVG files."""

from fastapi.staticfiles import StaticFiles


# Deliberately omit allow-same-origin: scripts run with an opaque origin and
# cannot read admin pages, cookies, storage, or register service workers.
GENERATED_CONTENT_CSP = (
    "sandbox allow-scripts; connect-src 'none'; form-action 'none'; "
    "frame-src 'none'; object-src 'none'; base-uri 'none'"
)


class SandboxedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Content-Security-Policy"] = GENERATED_CONTENT_CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
