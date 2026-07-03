from unittest.mock import MagicMock, patch
from app.db import get_all_from_db

def test_get_all_from_db_success():

    fake_rows = [
        MagicMock(_mapping={
            "ID": "CAM001",
            "Cam_InternetFTP_Folder": "/folder1",
            "Cam_InternetFTP_Filename": "cam1.jpg",
            "Cam_LocationsRegion": "North",
            "Cam_MaintenancePublic_IP": "192.0.2.1"
        }),
        MagicMock(_mapping={
            "ID": "CAM002",
            "Cam_InternetFTP_Folder": "/folder2",
            "Cam_InternetFTP_Filename": "cam2.jpg",
            "Cam_LocationsRegion": "South",
            "Cam_MaintenancePublic_IP": "192.0.2.2"
        })
    ]

    mock_connection = MagicMock()
    mock_connection.execute.return_value = fake_rows

    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_connection
    mock_context.__exit__.return_value = None

    with patch("app.db.engine.connect", return_value=mock_context):
        rows = get_all_from_db()

    assert len(rows) == 2
    assert rows[0]["ID"] == "CAM001"
    assert rows[1]["ID"] == "CAM002"


def test_get_all_from_db_empty():

    mock_connection = MagicMock()
    mock_connection.execute.return_value = []

    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_connection
    mock_context.__exit__.return_value = None

    with patch("app.db.engine.connect", return_value=mock_context):
        rows = get_all_from_db()

    assert rows == []

def test_get_all_from_db_exception():

    mock_connection = MagicMock()
    mock_connection.execute.side_effect = Exception("DB failure")

    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_connection
    mock_context.__exit__.return_value = None

    with patch("app.db.engine.connect", return_value=mock_context):
        with patch("app.db.logger") as mock_logger:
            result = get_all_from_db()

    mock_logger.error.assert_called_once()
    assert result is None

from unittest.mock import ANY

def test_execute_called_once():

    mock_connection = MagicMock()
    mock_connection.execute.return_value = []

    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_connection
    mock_context.__exit__.return_value = None

    with patch("app.db.engine.connect", return_value=mock_context):
        get_all_from_db()

    mock_connection.execute.assert_called_once_with(ANY)

