from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
import pyodbc

config = dotenv_values(".env", encoding="utf-8-sig")

server = config["SQL_SERVER"]
database = config["SQL_DATABASE"]
driver = config["SQL_DRIVER"]

connection_string = (
    f"DRIVER={{{driver}}};"
    f"SERVER={server};"
    f"DATABASE={database};"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

# IMPORTANTE: no utilizar quote_plus aquí.
url = URL.create(
    "mssql+pyodbc",
    query={"odbc_connect": connection_string}
)

engine = create_engine(url, pool_pre_ping=True)

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                @@SERVERNAME AS servidor,
                DB_NAME() AS base_datos,
                GETDATE() AS fecha_conexion
        """))

        for row in result:
            print("CONEXION EXITOSA")
            print("Servidor:", row.servidor)
            print("Base de datos:", row.base_datos)
            print("Fecha:", row.fecha_conexion)

finally:
    engine.dispose()
