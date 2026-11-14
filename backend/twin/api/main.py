"""ASGI entry point: `uvicorn twin.api.main:app`."""

from twin.api.app import create_app

app = create_app()
