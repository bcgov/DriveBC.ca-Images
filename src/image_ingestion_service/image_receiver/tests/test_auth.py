from unittest.mock import patch
from app.auth import load_mapping_from_env
from fastapi.security import HTTPBasicCredentials
from app.auth import normalize_and_validate_ip
from app.auth import check_ip_match
from app.auth import verify_credentials

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"

@patch.dict("os.environ", {"TEST_ENV": '{"A":"B"}'})
def test_load_mapping_valid_json():
    assert load_mapping_from_env("TEST_ENV") == {"A": "B"}



def test_normalize_ip():
    assert normalize_and_validate_ip("192.0.2.1") == "192.0.2.1"



def test_match_cidr():

    assert check_ip_match(
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

    assert verify_credentials(creds, expected)