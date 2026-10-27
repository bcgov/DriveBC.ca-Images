import asyncio
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

import app.main as main


REQUIRED_ENV = {
    "CLUSTER": "GOLD",
    "RABBITMQ_GOLD_URL": "amqp://gold",
    "RABBITMQ_GOLDDR_URL": "amqp://golddr",
    "RABBITMQ_EXCHANGE_NAME": "images",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", REQUIRED_ENV)
async def test_lifespan_rejects_missing_configuration_before_connecting(missing):
    environment = {key: value for key, value in REQUIRED_ENV.items() if key != missing}
    app = FastAPI()

    with patch.dict(os.environ, environment, clear=True):
        with patch("app.main.aio_pika.connect_robust", new_callable=AsyncMock) as connect:
            with pytest.raises(ValueError, match=f"Missing environment variable: {missing}"):
                async with main.lifespan(app):
                    pass

    connect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cluster", "expected_url"),
    [
        ("GOLD", "amqp://gold"),
        ("GOLDDR", "amqp://golddr"),
        ("UNKNOWN", "amqp://gold"),
    ],
)
async def test_lifespan_connects_and_closes_resources(monkeypatch, cluster, expected_url, caplog):
    monkeypatch.setenv("CLUSTER", cluster)
    monkeypatch.setenv("RABBITMQ_GOLD_URL", "amqp://gold")
    monkeypatch.setenv("RABBITMQ_GOLDDR_URL", "amqp://golddr")
    monkeypatch.setenv("RABBITMQ_EXCHANGE_NAME", "images")

    connection = MagicMock(close=AsyncMock())
    connection.channel = AsyncMock()
    channel = MagicMock(close=AsyncMock())
    channel.declare_exchange = AsyncMock()
    exchange = object()
    connection.channel.return_value = channel
    channel.declare_exchange.return_value = exchange
    updater_started = asyncio.Event()
    updater_stopped = asyncio.Event()

    async def wait_for_cancellation():
        updater_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            updater_stopped.set()

    monkeypatch.setattr(main, "update_credentials_periodically", wait_for_cancellation)
    app = FastAPI()
    with patch(
        "app.main.aio_pika.connect_robust",
        new_callable=AsyncMock,
        return_value=connection,
    ) as connect:
        with caplog.at_level(logging.WARNING, logger="app.main"):
            async with main.lifespan(app):
                assert app.state.rabbitmq_connection is connection
                assert app.state.rabbitmq_channel is channel
                assert app.state.rabbitmq_exchange is exchange
                assert app.state.rabbitmq_channel_lock.locked() is False
                await updater_started.wait()

    connect.assert_awaited_once()
    assert connect.await_args.args[0] == expected_url
    assert channel.declare_exchange.await_args.kwargs["name"] == "images"
    assert channel.declare_exchange.await_args.kwargs["durable"] is True
    channel.close.assert_awaited_once()
    connection.close.assert_awaited_once()
    assert updater_stopped.is_set()
    if cluster == "UNKNOWN":
        assert "Unknown CLUSTER value" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_closes_connection_when_channel_setup_fails(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    connection = MagicMock(close=AsyncMock())
    connection.channel = AsyncMock(side_effect=RuntimeError("channel unavailable"))
    app = FastAPI()
    with patch("app.main.aio_pika.connect_robust", new_callable=AsyncMock, return_value=connection):
        with patch("app.main.update_credentials_periodically") as update_task:
            with patch("app.main.logging.exception") as log_exception:
                with pytest.raises(RuntimeError, match="channel unavailable"):
                    async with main.lifespan(app):
                        pass

    connection.close.assert_awaited_once()
    update_task.assert_not_called()
    log_exception.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_closes_channel_and_connection_when_exchange_setup_fails(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    connection = MagicMock(close=AsyncMock())
    channel = MagicMock(close=AsyncMock())
    connection.channel = AsyncMock(return_value=channel)
    channel.declare_exchange = AsyncMock(side_effect=RuntimeError("exchange unavailable"))
    app = FastAPI()
    with patch("app.main.aio_pika.connect_robust", new_callable=AsyncMock, return_value=connection):
        with patch("app.main.update_credentials_periodically") as update_task:
            with pytest.raises(RuntimeError, match="exchange unavailable"):
                async with main.lifespan(app):
                    pass

    channel.close.assert_awaited_once()
    connection.close.assert_awaited_once()
    update_task.assert_not_called()
