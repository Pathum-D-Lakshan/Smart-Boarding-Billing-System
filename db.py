import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"), interpolate=False)


def get_db_connection():
    """Open a connection using this project's MySQL settings."""
    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        connection_timeout=5,
    )