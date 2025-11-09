from datetime import timedelta

import pytest
from jose import JWTError, jwt

from backend.core.security import create_access_token, decode_access_token
from backend.core.settings import settings


def test_create_and_decode_access_token():
    """
    Test that a token can be created and then successfully decoded.
    """
    user_id = "test-user-id-string"
    data = {"user_id": user_id}
    token = create_access_token(data)

    payload = decode_access_token(token)

    assert payload["user_id"] == user_id
    assert "exp" in payload


def test_decode_expired_token_raises_error():
    """
    Test that decoding an expired token raises a JWTError.
    """
    user_id = "test-user-id-string"
    # Create a token that expired 1 second ago
    data = {"user_id": user_id}
    token = create_access_token(data, expires_delta=timedelta(seconds=-1))

    with pytest.raises(JWTError):
        decode_access_token(token)


def test_decode_invalid_token_string_raises_error():
    """
    Test that decoding a malformed token string raises a JWTError.
    """
    with pytest.raises(JWTError):
        decode_access_token("this.is.not.a.valid.token")


def test_decode_token_with_wrong_secret_raises_error():
    """
    Test that decoding a token signed with a different secret key raises a JWTError.
    """
    user_id = "test-user-id-string"
    data = {"user_id": user_id}
    token = create_access_token(data)

    with pytest.raises(JWTError):
        jwt.decode(token, "a-different-secret", algorithms=[settings.JWT_ALGORITHM])
