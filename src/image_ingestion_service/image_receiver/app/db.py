import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
import requests


# Connection settings
DB_SERVER = os.getenv("DB_SERVER")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_DRIVER = "ODBC Driver 18 for SQL Server"  # Make sure this driver is installed on the container

logger = logging.getLogger(__name__)

RIDE_IMAGE_INGESTION_URL = os.environ["RIDE_IMAGE_INGESTION_URL"]  + '/api/imageingestion/cameras/'

# Build connection URL
connection_url = URL.create(
    "mssql+pyodbc",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_SERVER,
    port=1433,
    database=DB_NAME,
    query={
        "driver": DB_DRIVER,
        "TrustServerCertificate": "yes",
        "Encrypt": "yes",
    }
)

# Create SQLAlchemy engine
engine = create_engine(connection_url)

# Query function
def get_all_from_db():
    sql_statement = """
        SELECT [ID], [Cam_InternetFTP_Folder], [Cam_InternetFTP_Filename],
               [Cam_LocationsRegion], [Cam_MaintenancePublic_IP]
        FROM [Cams]
    """
    with engine.connect() as connection:
        try:
            result = connection.execute(text(sql_statement))
            rows = [dict(row._mapping) for row in result]
            return rows
        except Exception as e:
            logger.error(f"Failed to connect to the database: {e}")

def get_all_from_api():
    RIDE_SERVICE_TOKEN = os.environ["RIDE_SERVICE_TOKEN"]
    headers = {"X-Internal-Token": RIDE_SERVICE_TOKEN}
    try:
        response = requests.get(RIDE_IMAGE_INGESTION_URL, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch cameras from RIDE API: {e}")

def get_all():
    CAMERA_SOURCE = os.environ["CAMERA_SOURCE"]
    if CAMERA_SOURCE == "api":
        return get_all_from_api()
    return get_all_from_db()