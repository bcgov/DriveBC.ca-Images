import pytest
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient

from app.main import app
from app.auth import authenticate_request


@asynccontextmanager
async def test_lifespan(app):
    # Do nothing on startup
    yield
    # Do nothing on shutdown


app.router.lifespan_context = test_lifespan


def fake_auth():
    return {"ID": "CAM001"}


app.dependency_overrides[authenticate_request] = fake_auth


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client