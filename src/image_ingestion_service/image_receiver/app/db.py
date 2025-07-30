import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


# Connection settings
DB_SERVER = os.getenv("DB_SERVER", "sql-server-db")
DB_NAME = os.getenv("DB_NAME", "camera-db")
DB_USER = os.getenv("DB_USER", "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "YourStrong@Passw0rd")
DB_DRIVER = "ODBC Driver 17 for SQL Server"  # Make sure this driver is installed on the container

logger = logging.getLogger(__name__)

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

# Query function
def get_all_from_db():
    sql_statement = f"""
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
                 