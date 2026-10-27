import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import app.auth


SCRIPT = Path(app.auth.__file__).with_name("print_cache.py")


def run_print_cache(monkeypatch, arguments, cache):
    monkeypatch.setattr(sys, "argv", ["app.print_cache", *arguments])
    with patch("app.auth.get_data_from_db") as load_data:
        with patch.dict(app.auth.CREDENTIAL_CACHE, cache, clear=True):
            with patch("builtins.print") as print_output:
                runpy.run_path(str(SCRIPT), run_name="__main__")
    load_data.assert_called_once_with()
    return print_output.call_args_list


def test_print_cache_outputs_all_records(monkeypatch):
    record = {"ID": "CAM001"}

    output = run_print_cache(monkeypatch, [], {"CAM001": record})

    assert output[0].args == (record,)


def test_print_cache_outputs_requested_record(monkeypatch):
    record = {"ID": "CAM001"}

    output = run_print_cache(monkeypatch, ["CAM001"], {"CAM001": record})

    assert output[0].args == (record,)


def test_print_cache_reports_missing_record(monkeypatch):
    output = run_print_cache(monkeypatch, ["CAM404"], {})

    assert output[0].args == ("No entry found for ID: CAM404",)
