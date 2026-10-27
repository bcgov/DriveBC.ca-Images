import logging
from PIL import Image
from io import BytesIO
from unittest.mock import AsyncMock, Mock, patch
import pytest
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect

import app.main as main


def test_health(client):
    
    response = client.get("/api/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok"
    }
    assert response.headers["X-Request-ID"]

def test_index(client):

    response = client.get("/api/images")

    assert response.status_code == 200
    assert "reachable" in response.text


def test_root_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "reachable" in response.text



def test_empty_image():

    valid, error = main.validate_jpg_image(b"")

    assert valid is False
    assert error == "No image data received"

def test_invalid_image():

    valid, error = main.validate_jpg_image(b"abcdefg")

    assert valid is False
    assert error == "Invalid or corrupt image data"



@patch("app.main.MAX_FILE_SIZE", 10)
def test_large_image():

    valid, error = main.validate_jpg_image(b"a" * 20)

    assert valid is False
    assert error == "Image exceeds maximum size limit"



def create_jpeg():

    image = Image.new("RGB", (20, 20))

    bio = BytesIO()
    image.save(bio, format="JPEG")

    return bio.getvalue()


def test_valid_jpeg():

    data = create_jpeg()

    valid, error = main.validate_jpg_image(data)

    assert valid is True
    assert error is None


@patch("app.main.Image.open", side_effect=OSError("cannot read"))
def test_unreadable_image(mock_open):
    valid, error = main.validate_jpg_image(b"image bytes")

    assert valid is False
    assert error == "Cannot read image data"
    mock_open.assert_called_once()


def test_non_jpeg_image_is_rejected():
    image = Image.new("RGB", (2, 2))
    data = BytesIO()
    image.save(data, format="PNG")

    valid, error = main.validate_jpg_image(data.getvalue())

    assert valid is False
    assert error == "Unsupported image format, only JPEG is allowed"

def jpeg():

    img = Image.new("RGB", (10, 10))

    bio = BytesIO()
    img.save(bio, format="JPEG")

    return bio.getvalue()


@patch("app.main.send_to_rabbitmq")
def test_upload_success(mock_send, client):

    response = client.post(
        "/api/images",
        content=jpeg(),
        headers={
            "content-length": "500"
        },
    )

    assert response.status_code == 200
    assert response.text == "Image received and processed successfully"

    mock_send.assert_called_once()

@patch("app.main.send_to_rabbitmq")
def test_rabbitmq_failure(mock_send, client):

    mock_send.side_effect = Exception("RabbitMQ down")

    response = client.post(
        "/api/images",
        content=jpeg(),
        headers={
            "content-length": "500"
        },
    )

    assert response.status_code == 500

def test_empty_body(client):

    response = client.post(
        "/api/images",
        content=b"",
        headers={
            "content-length": "0"
        },
    )

    assert response.status_code == 400
    assert "No image data" in response.text

def test_invalid_jpeg(client):

    response = client.post(
        "/api/images",
        content=b"hello world",
        headers={
            "content-length": "11"
        },
    )

    assert response.status_code == 400

@patch("app.main.MAX_FILE_SIZE", 100)
def test_content_length_too_large(client):

    response = client.post(
        "/api/images",
        content=b"abc",
        headers={
            "content-length": "1000"
        },
    )

    assert response.status_code == 413


class StreamRequest:
    def __init__(self, chunks, headers=None, error=None):
        self.headers = Headers(headers or {})
        self.chunks = chunks
        self.error = error

    async def stream(self):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error


@pytest.mark.asyncio
@patch("app.main.MAX_FILE_SIZE", 5)
@patch("app.main.record_processing_failure")
async def test_stream_exceeding_size_is_rejected(mock_record_failure):
    request = StreamRequest([b"123", b"456"])

    response = await main.receive_image(request, {"ID": "CAM001"})

    assert response.status_code == 413
    mock_record_failure.assert_called_once()


@pytest.mark.asyncio
@patch("app.main.send_to_rabbitmq", new_callable=AsyncMock)
async def test_client_disconnect_processes_valid_partial_image(mock_send):
    request = StreamRequest([jpeg()], error=ClientDisconnect())

    response = await main.receive_image(request, {"ID": "CAM001"})

    assert response.status_code == 200
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.main.send_to_rabbitmq", new_callable=AsyncMock)
async def test_upload_without_content_length_and_timestamp(mock_send):
    request = StreamRequest([jpeg()])

    response = await main.receive_image(request, {"ID": "CAM001"})

    assert response.status_code == 200
    assert mock_send.await_args.kwargs["camera_id"] == "CAM001"
    assert mock_send.await_args.kwargs["timestamp"]


@pytest.mark.asyncio
@patch("app.main.send_to_rabbitmq", new_callable=AsyncMock)
async def test_upload_invalid_timestamp_falls_back_to_current_time(mock_send):
    request = StreamRequest([jpeg()], {"timestamp": "not-a-timestamp"})

    response = await main.receive_image(request, {"ID": "CAM001"})

    assert response.status_code == 200
    assert mock_send.await_args.kwargs["timestamp"] != "not-a-timestamp"


@patch("app.main.send_to_rabbitmq")
def test_invalid_timestamp(mock_send, client):

    response = client.post(
        "/api/images",
        content=jpeg(),
        headers={
            "content-length": "500",
            "timestamp": "bad-value"
        },
    )

    assert response.status_code == 200

@patch("app.main.send_to_rabbitmq")
def test_valid_timestamp(mock_send, client):

    response = client.post(
        "/api/images",
        content=jpeg(),
        headers={
            "content-length": "500",
            "timestamp": "20260101T010101Z"
        },
    )

    assert response.status_code == 200

@patch.dict("os.environ", {}, clear=True)
def test_default_max_file_size():

    assert main._get_max_file_size() == 5 * 1024 * 1024


@patch.dict("os.environ", {"MAX_FILE_SIZE_BYTES": "100"})
def test_env_max_file_size():

    assert main._get_max_file_size() == 100


@patch.dict("os.environ", {"MAX_FILE_SIZE_BYTES": "abc"})
def test_invalid_env():

    assert main._get_max_file_size() == 5 * 1024 * 1024


@patch("app.main.send_to_rabbitmq", new_callable=AsyncMock)
def test_debug_post_middleware_logs_request_details(mock_send, monkeypatch, client):
    monkeypatch.setattr(main.logger, "isEnabledFor", lambda level: level == logging.DEBUG)
    debug = Mock()
    monkeypatch.setattr(main.logger, "debug", debug)

    response = client.post("/api/images", content=jpeg())

    assert response.status_code == 200
    assert debug.call_count == 2
    assert "Incoming POST request" in debug.call_args_list[0].args[0]
    assert "POST Request Headers" in debug.call_args_list[1].args[0]