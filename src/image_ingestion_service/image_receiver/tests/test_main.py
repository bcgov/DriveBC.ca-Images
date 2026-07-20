from app.main import validate_jpg_image
from PIL import Image
from io import BytesIO
from unittest.mock import patch
from app.main import _get_max_file_size


def test_health(client):
    
    response = client.get("/api/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok"
    }

def test_index(client):

    response = client.get("/api/images")

    assert response.status_code == 200
    assert "reachable" in response.text




def test_empty_image():

    valid, error = validate_jpg_image(b"")

    assert valid is False
    assert error == "No image data received"

def test_invalid_image():

    valid, error = validate_jpg_image(b"abcdefg")

    assert valid is False
    assert error == "Invalid or corrupt image data"



@patch("app.main.MAX_FILE_SIZE", 10)
def test_large_image():

    valid, error = validate_jpg_image(b"a" * 20)

    assert valid is False
    assert error == "Image exceeds maximum size limit"



def create_jpeg():

    image = Image.new("RGB", (20, 20))

    bio = BytesIO()
    image.save(bio, format="JPEG")

    return bio.getvalue()


def test_valid_jpeg():

    data = create_jpeg()

    valid, error = validate_jpg_image(data)

    assert valid is True
    assert error is None

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

    assert _get_max_file_size() == 5 * 1024 * 1024


@patch.dict("os.environ", {"MAX_FILE_SIZE_BYTES": "100"})
def test_env_max_file_size():

    assert _get_max_file_size() == 100


@patch.dict("os.environ", {"MAX_FILE_SIZE_BYTES": "abc"})
def test_invalid_env():

    assert _get_max_file_size() == 5 * 1024 * 1024