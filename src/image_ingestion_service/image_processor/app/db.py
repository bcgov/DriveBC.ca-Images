import os
import pprint
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
import asyncpg

db_pool = None

# Connection settings
DB_SERVER = os.getenv("DB_SERVER", "sql-server-db")
DB_NAME = os.getenv("DB_NAME", "camera-db")
DB_USER = os.getenv("DB_USER", "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "YourStrong@Passw0rd")
DB_DRIVER = "ODBC Driver 17 for SQL Server"  # Make sure this driver is installed on the container

# Build connection URL
connection_url = URL.create(
    "mssql+pyodbc",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_SERVER,
    port=1433,
    database=DB_NAME,
    query={"driver": DB_DRIVER}
)

# Create SQLAlchemy engine
engine = create_engine(connection_url)

def get_all_from_db():
    cams_sql = """
        SELECT [ID], [Cam_LocationsGeo_Latitude], [Cam_LocationsGeo_Longitude], [Cam_ControlDisabled]
        FROM [WEBCAM_DEV].[dbo].[Cams]
    """

    cams_live_sql = """
        SELECT ID, Cam_InternetName, Cam_ControlDisabled, Cam_ControlShort_Message, Cam_ControlLong_Message
        FROM [WEBCAM_DEV].[dbo].[Cams_Live]
    """

    with engine.connect() as connection:
        try:
            # Query from Cams
            result_cams = connection.execute(text(cams_sql))
            cams_rows = {row.ID: dict(row._mapping) for row in result_cams}

            # Query from Cams_Live
            result_live = connection.execute(text(cams_live_sql))
            live_rows = {row.ID: dict(row._mapping) for row in result_live}

            # Merge based on ID
            merged_rows = []
            for cam_id, cam_data in cams_rows.items():
                live_data = live_rows.get(cam_id, {})
                merged_row = {**cam_data, **live_data}
                merged_rows.append(merged_row)

            # # Pretty-print merged rows for inspection
            # print("Merged Camera Rows:")
            # pprint.pprint(merged_rows)

            return merged_rows

        except Exception as e:
            print(f"Failed to connect to the database: {e}")
            return []



async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=os.getenv("POSTGRES_DSN"))
    return db_pool