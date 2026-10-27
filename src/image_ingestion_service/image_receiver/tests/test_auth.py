import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPBasicCredentials

import app.auth as auth

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"

@patch.dict("os.environ", {"TEST_ENV": '{"A":"B"}'})
def test_load_mapping_valid_json():
    assert auth.load_mapping_from_env("TEST_ENV") == {"A": "B"}



def test_normalize_ip():
    assert auth.normalize_and_validate_ip("192.0.2.1") == "192.0.2.1"



def test_match_cidr():

    assert auth.check_ip_match(
        "192.0.2.15",
        "192.0.2.0/24"
    )



def test_verify_credentials():

    creds = HTTPBasicCredentials(
        username=TEST_USERNAME,
        password=TEST_PASSWORD
    )

    expected = {
        "username":TEST_USERNAME,
        "password":TEST_PASSWORD
    }

    assert auth.verify_credentials(creds, expected)


def make_request(headers=None, client_ip="192.0.2.1"):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/images",
        "raw_path": b"/api/images",
        "query_string": b"",
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in (headers or {}).items()
        ],
        "client": (client_ip, 12345) if client_ip else None,
        "server": ("testserver", 80),
    })


def valid_credentials(username=TEST_USERNAME, password=TEST_PASSWORD):
    return HTTPBasicCredentials(username=username, password=password)


def camera_record(**overrides):
    return {
        "ID": "CAM001",
        "Cam_LocationsRegion": "North",
        "Cam_MaintenancePublic_IP": "192.0.2.1",
        **overrides,
    }


def upload_request(filename="CAM001.jpg", **headers):
    return make_request({
        "content-disposition": f'form-data; name="image"; filename="{filename}"',
        **headers,
    })


def test_load_mapping_missing_and_non_object(monkeypatch):
    monkeypatch.delenv("MAPPING_TEST", raising=False)
    default = {"fallback": True}

    assert auth.load_mapping_from_env("MAPPING_TEST", default) == default

    monkeypatch.setenv("MAPPING_TEST", '["not", "an", "object"]')
    assert auth.load_mapping_from_env("MAPPING_TEST", default) == default


def test_load_mapping_double_encoded_json(monkeypatch):
    monkeypatch.setenv("MAPPING_TEST", '"{\\"camera\\": \\"user\\"}"')

    assert auth.load_mapping_from_env("MAPPING_TEST") == {"camera": "user"}


def test_load_mapping_invalid_json_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("MAPPING_TEST", "{")

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert auth.load_mapping_from_env("MAPPING_TEST") == {}

    assert "JSON decoding failed for MAPPING_TEST" in caplog.text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        (" 192.0.2.1:8080 ", "192.0.2.1"),
        ("192.0.2.8/24", "192.0.2.0/24"),
        ("invalid", ""),
        ("2001:db8::1", ""),
    ],
)
def test_normalize_and_validate_ip(value, expected):
    assert auth.normalize_and_validate_ip(value) == expected


def test_ip_match_exact_and_mismatch():
    assert auth.check_ip_match("192.0.2.1", "192.0.2.1")
    assert not auth.check_ip_match("192.0.2.2", "192.0.2.1")


def test_ip_match_invalid_client_and_expected_ip(caplog):
    with caplog.at_level(logging.WARNING, logger="app.auth"):
        assert not auth.check_ip_match("not-an-ip", "192.0.2.1")
        assert not auth.check_ip_match("192.0.2.1", "not-an-ip")

    assert "Invalid client IP" in caplog.text
    assert "Invalid expected IP or CIDR" in caplog.text


def test_get_client_ip_and_proto_from_forwarded_headers():
    request = upload_request(
        forwarded="for=192.0.2.8;proto=HTTPS, for=192.0.2.9;proto=http"
    )

    assert auth.get_client_ip(request) == "192.0.2.8"
    assert auth.get_client_proto(request) == "https"


def test_get_client_ip_forwarded_without_for_and_missing_client():
    request = make_request({"forwarded": "192.0.2.12;proto=http"}, client_ip=None)
    no_client = make_request(client_ip=None)

    assert auth.get_client_ip(request) == "192.0.2.12"
    assert auth.get_client_ip(no_client) == "unknown"
    assert auth.get_client_proto(no_client) == "unknown"


def test_get_client_proto_from_later_forwarded_entry():
    request = make_request({"forwarded": "for=192.0.2.1, for=192.0.2.2;proto=HTTPS"})

    assert auth.get_client_proto(request) == "https"


def test_get_camera_record_and_validate_invalid_id():
    with pytest.raises(HTTPException) as error:
        auth.get_camera_record_and_validate("bad-id", {})

    assert error.value.status_code == 401
    assert error.value.detail == "Unauthorized"


def test_get_camera_record_and_validate_unknown_numeric_id():
    with pytest.raises(HTTPException) as error:
        auth.get_camera_record_and_validate("123", {})

    assert error.value.status_code == 401


def test_verify_ip_or_raise_success_without_restriction():
    auth.verify_ip_or_raise("192.0.2.1", "", "CAM001")


def test_verify_ip_or_raise_mismatch():
    with pytest.raises(HTTPException) as error:
        auth.verify_ip_or_raise("192.0.2.2", "192.0.2.1", "CAM001")

    assert error.value.status_code == 401
    assert error.value.headers == {"WWW-Authenticate": "Basic"}


def test_verify_credentials_rejects_mismatch():
    expected = {"username": TEST_USERNAME, "password": TEST_PASSWORD}

    assert not auth.verify_credentials(valid_credentials(password="wrong"), expected)
    assert not auth.verify_credentials(valid_credentials(username="wrong"), expected)


def test_verify_creds_or_raise_missing_and_invalid_credentials():
    missing_credentials = valid_credentials()
    invalid_credentials = HTTPBasicCredentials(username="wrong", password=TEST_PASSWORD)
    expected_credentials = {"username": TEST_USERNAME, "password": TEST_PASSWORD}

    with pytest.raises(HTTPException) as missing:
        auth.verify_creds_or_raise(missing_credentials, None, "CAM001")
    with pytest.raises(HTTPException) as invalid:
        auth.verify_creds_or_raise(invalid_credentials, expected_credentials, "CAM001")

    assert missing.value.status_code == invalid.value.status_code == 401


@pytest.mark.asyncio
async def test_get_cached_credentials_returns_independent_copy(monkeypatch):
    cache = {"CAM001": camera_record()}
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", cache)

    result = await auth.get_cached_credentials()
    result.clear()

    assert "CAM001" in cache


def test_get_data_from_db_populates_and_replaces_cache(monkeypatch):
    cache = {"old": {"ID": "old"}}
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", cache)
    monkeypatch.setattr(auth, "get_all_from_db", lambda: [camera_record()])

    auth.get_data_from_db()

    assert cache == {"CAM001": camera_record()}


def test_get_data_from_db_empty_keeps_existing_cache(monkeypatch):
    cache = {"CAM001": camera_record()}
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", cache)
    monkeypatch.setattr(auth, "get_all_from_db", lambda: [])

    auth.get_data_from_db()

    assert cache == {"CAM001": camera_record()}


def test_get_data_from_db_logs_database_exception(monkeypatch, caplog):
    monkeypatch.setattr(auth, "get_all_from_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))

    with caplog.at_level(logging.ERROR, logger="app.auth"):
        auth.get_data_from_db()

    assert "Error initializing camera details" in caplog.text


@pytest.mark.asyncio
async def test_update_credentials_periodically_replaces_cache_and_sleeps(monkeypatch):
    cache = {"old": {"ID": "old"}}
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", cache)
    monkeypatch.setattr(auth, "get_all_from_db", lambda: [camera_record()])
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(auth.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await auth.update_credentials_periodically()

    assert cache == {"CAM001": camera_record()}
    sleep.assert_awaited_once_with(30)


@pytest.mark.asyncio
async def test_update_credentials_periodically_keeps_cache_on_empty_result(monkeypatch):
    cache = {"CAM001": camera_record()}
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", cache)
    monkeypatch.setattr(auth, "get_all_from_db", lambda: [])
    monkeypatch.setattr(auth.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

    with pytest.raises(asyncio.CancelledError):
        await auth.update_credentials_periodically()

    assert cache == {"CAM001": camera_record()}


@pytest.mark.asyncio
async def test_update_credentials_periodically_logs_database_exception(monkeypatch, caplog):
    monkeypatch.setattr(auth, "get_all_from_db", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(auth.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))

    with caplog.at_level(logging.ERROR, logger="app.auth"):
        with pytest.raises(asyncio.CancelledError):
            await auth.update_credentials_periodically()

    assert "Error updating camera details: db down" in caplog.text


@pytest.mark.asyncio
async def test_authenticate_request_falls_back_to_database(monkeypatch):
    cache = {}
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", cache)
    monkeypatch.setattr(auth, "get_data_from_db", lambda: cache.update({"CAM001": camera_record()}))
    monkeypatch.setattr(auth, "LOCATION_USER_PASS_MAPPING", {
        "North": {"username": TEST_USERNAME, "password": TEST_PASSWORD}
    })
    monkeypatch.setattr(auth, "SCRIPTED_IP_MAPPING", {})

    result = await auth.authenticate_request(upload_request(), valid_credentials())

    assert result["ID"] == "CAM001"
    assert result["ip_address"] == "192.0.2.1"
    assert result["is_scripted"] is False


@pytest.mark.asyncio
async def test_authenticate_request_unavailable_database_data(monkeypatch):
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", {})
    monkeypatch.setattr(auth, "get_data_from_db", lambda: None)
    request = upload_request()
    credentials = valid_credentials()

    with pytest.raises(HTTPException) as error:
        await auth.authenticate_request(request, credentials)

    assert error.value.status_code == 500
    assert error.value.detail == "Camera data unavailable."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected_detail"),
    [
        ({}, "Missing or malformed Content-Disposition header"),
        ({"content-disposition": "form-data; name=image"}, "Missing or malformed Content-Disposition header"),
        ({"content-disposition": 'form-data; filename="!!!.jpg"'}, "Invalid filename format"),
    ],
)
async def test_authenticate_request_rejects_malformed_filename(
    monkeypatch, headers, expected_detail
):
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", {"CAM001": camera_record()})
    request = make_request(headers)
    credentials = valid_credentials()

    with pytest.raises(HTTPException) as error:
        await auth.authenticate_request(request, credentials)

    assert error.value.status_code == 400
    assert error.value.detail == expected_detail


@pytest.mark.asyncio
async def test_authenticate_request_regular_camera_without_ip_restriction(monkeypatch):
    record = camera_record(Cam_MaintenancePublic_IP=None, Cam_LocationsRegion=" North ")
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", {"CAM001": record})
    monkeypatch.setattr(auth, "LOCATION_USER_PASS_MAPPING", {
        "North": {"username": TEST_USERNAME, "password": TEST_PASSWORD}
    })
    monkeypatch.setattr(auth, "SCRIPTED_IP_MAPPING", {})

    result = await auth.authenticate_request(upload_request(), valid_credentials())

    assert result["ID"] == "CAM001"
    assert result["is_scripted"] is False


@pytest.mark.asyncio
async def test_authenticate_request_scripted_ip_with_string_mapping(monkeypatch):
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", {"CAM001": camera_record()})
    monkeypatch.setattr(auth, "SCRIPTED_IP_MAPPING", {"Automation": "192.0.2.0/24"})
    monkeypatch.setattr(auth, "LOCATION_USER_PASS_MAPPING", {
        "Automation": {"username": TEST_USERNAME, "password": TEST_PASSWORD}
    })

    result = await auth.authenticate_request(upload_request(), valid_credentials())

    assert result["is_scripted"] is True


@pytest.mark.asyncio
async def test_authenticate_request_scripted_ip_with_list_and_fallback(monkeypatch):
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", {"CAM001": camera_record()})
    monkeypatch.setattr(auth, "SCRIPTED_IP_MAPPING", {
        "Automation": ["invalid", "192.0.2.0/24"]
    })
    monkeypatch.setattr(auth, "LOCATION_USER_PASS_MAPPING", {
        "Automation": {"username": TEST_USERNAME, "password": TEST_PASSWORD}
    })

    result = await auth.authenticate_request(upload_request(), valid_credentials())

    assert result["is_scripted"] is True


@pytest.mark.asyncio
async def test_authenticate_request_scripted_ip_mismatch_uses_regular_auth(monkeypatch):
    monkeypatch.setattr(auth, "CREDENTIAL_CACHE", {"CAM001": camera_record()})
    monkeypatch.setattr(auth, "SCRIPTED_IP_MAPPING", {"Automation": "198.51.100.0/24"})
    monkeypatch.setattr(auth, "LOCATION_USER_PASS_MAPPING", {
        "North": {"username": TEST_USERNAME, "password": TEST_PASSWORD}
    })

    result = await auth.authenticate_request(upload_request(), valid_credentials())

    assert result["is_scripted"] is False