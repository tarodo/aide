from fastapi.testclient import TestClient

from backend.core import errors
from backend.core.exceptions import AppException
from backend.main import app


@app.get("/__test_app_exception", include_in_schema=False)
async def _test_app_exception_route():
    raise AppException(errors.USER_NOT_FOUND)


@app.get("/__test_unhandled_exception", include_in_schema=False)
async def _test_unhandled_exception_route():
    raise RuntimeError("This is a deliberate unhandled test exception")


def test_root(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_app_exception_handler(client: TestClient):
    response = client.get("/__test_app_exception")
    status_code, detail = errors.ERROR_MAP[errors.USER_NOT_FOUND]
    assert response.status_code == status_code
    assert response.json() == {"error_code": errors.USER_NOT_FOUND, "detail": detail}


def test_unhandled_exception_handler(client: TestClient):
    with TestClient(app, raise_server_exceptions=False) as raw_client:
        response = raw_client.get("/__test_unhandled_exception")
    assert response.status_code == 500
    assert response.json() == {
        "error_code": "INTERNAL_SERVER_ERROR",
        "detail": "An unexpected internal error occurred.",
    }
