import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.rabbitmq import send_to_rabbitmq
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_send_to_rabbitmq_success():

    exchange = AsyncMock()

    request = MagicMock()
    request.app.state.rabbitmq_exchange = exchange
    request.app.state.rabbitmq_channel_lock = None

    with patch("app.rabbitmq.aio_pika.Message") as mock_message:

        await send_to_rabbitmq(
            request=request,
            image_bytes=b"image",
            filename="cam.jpg",
            camera_id="CAM001",
            timestamp="2026-01-01T12:30:45+00:00"
        )

        exchange.publish.assert_awaited_once()

        mock_message.assert_called_once()

@pytest.mark.asyncio
async def test_send_to_rabbitmq_with_lock():

    exchange = AsyncMock()

    lock = AsyncMock()
    lock.__aenter__.return_value = None
    lock.__aexit__.return_value = None

    request = MagicMock()
    request.app.state.rabbitmq_exchange = exchange
    request.app.state.rabbitmq_channel_lock = lock

    with patch("app.rabbitmq.aio_pika.Message"):

        await send_to_rabbitmq(
            request=request,
            image_bytes=b"abc",
            filename="cam.jpg",
            camera_id="CAM001",
            timestamp="2026-01-01T12:30:45+00:00"
        )

        exchange.publish.assert_awaited_once()

@pytest.mark.asyncio
async def test_publish_failure():

    exchange = AsyncMock()
    exchange.publish.side_effect = RuntimeError("RabbitMQ down")

    request = MagicMock()
    request.app.state.rabbitmq_exchange = exchange
    request.app.state.rabbitmq_channel_lock = None

    with patch("app.rabbitmq.aio_pika.Message"):

        with pytest.raises(RuntimeError):

            await send_to_rabbitmq(
                request=request,
                image_bytes=b"abc",
                filename="cam.jpg",
                camera_id="CAM001",
                timestamp="2026-01-01T12:30:45+00:00"
            )

@pytest.mark.asyncio
async def test_invalid_timestamp():

    request = MagicMock()

    with pytest.raises(ValueError):

        await send_to_rabbitmq(
            request=request,
            image_bytes=b"",
            filename="cam.jpg",
            camera_id="CAM001",
            timestamp="not-a-date"
        )

@pytest.mark.asyncio
async def test_message_headers():

    exchange = AsyncMock()

    request = MagicMock()
    request.app.state.rabbitmq_exchange = exchange
    request.app.state.rabbitmq_channel_lock = None

    with patch("app.rabbitmq.aio_pika.Message") as message:

        await send_to_rabbitmq(
            request=request,
            image_bytes=b"abc",
            filename="camera.jpg",
            camera_id="CAM123",
            timestamp="2026-01-01T12:30:45+00:00"
        )

        _, kwargs = message.call_args

        assert kwargs["body"] == b"abc"

        headers = kwargs["headers"]

        assert headers["camera_id"] == "CAM123"
        assert headers["filename"] == "camera.jpg"
        assert headers["timestamp"] == "20260101123045000"

        assert "processed_timestamp" in headers

@pytest.mark.asyncio
async def test_logger_called_on_exception():

    exchange = AsyncMock()
    exchange.publish.side_effect = RuntimeError("boom")

    request = MagicMock()
    request.app.state.rabbitmq_exchange = exchange
    request.app.state.rabbitmq_channel_lock = None

    with patch("app.rabbitmq.logger") as logger:

        with patch("app.rabbitmq.aio_pika.Message"):

            with pytest.raises(RuntimeError):

                await send_to_rabbitmq(
                    request,
                    b"abc",
                    "cam.jpg",
                    "CAM001",
                    "2026-01-01T12:30:45+00:00"
                )

        logger.error.assert_called_once()