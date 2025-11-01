from fastapi.testclient import TestClient
from aide.main import app
import os

print(os.getcwd())

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
