import os
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

# Query function
def get_all_from_db():
    sql_statement = "SELECT [ID], [Cam_LocationsGeo_Latitude], [Cam_LocationsGeo_Longitude] FROM [WEBCAM_DEV].[dbo].[Cams]"
    with engine.connect() as connection:
        try:
            result = connection.execute(text(sql_statement))
            rows = [dict(row._mapping) for row in result]
            return rows
        except Exception as e:
            print(f"Failed to connect to the database: {e}")
                 

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(dsn=os.getenv("POSTGRES_DSN"))
    return db_pool