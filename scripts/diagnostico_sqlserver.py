import sys
from pathlib import Path
from urllib.parse import quote_plus

import pyodbc
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
config = dotenv_values(ROOT / ".env", encoding="utf-8-sig")

print("=" * 55)
print("DIAGNOSTICO DE CONEXION SQL SERVER")
print("=" * 55)

print("\n1. CONFIGURACION .ENV")

server = (config.get("SQL_SERVER") or "").strip()
database = (config.get("SQL_DATABASE") or "dengue_analytics").strip()
configured_driver = (config.get("SQL_DRIVER") or "").strip()
auth = (config.get("SQL_AUTH") or "windows").strip().lower()

print("Servidor:", repr(server))
print("Base de datos:", repr(database))
print("Driver configurado:", repr(configured_driver))
print("Autenticacion:", repr(auth))

print("\n2. CONTROLADORES ODBC DETECTADOS")

drivers = pyodbc.drivers()
for driver in drivers:
    print("-", repr(driver))

if configured_driver in drivers:
    driver = configured_driver
elif "ODBC Driver 18 for SQL Server" in drivers:
    driver = "ODBC Driver 18 for SQL Server"
elif "ODBC Driver 17 for SQL Server" in drivers:
    driver = "ODBC Driver 17 for SQL Server"
else:
    raise RuntimeError("No se detecto un controlador SQL Server compatible.")

print("\nDriver seleccionado:", driver)

if not server:
    raise RuntimeError("SQL_SERVER esta vacio en .env")

parts = [
    f"DRIVER={{{driver}}}",
    f"SERVER={server}",
    "DATABASE=master",
    "Encrypt=yes",
    "TrustServerCertificate=yes",
    "Connection Timeout=10"
]

if auth == "windows":
    parts.append("Trusted_Connection=yes")
else:
    parts.append(f"UID={config.get('SQL_USER', '')}")
    parts.append(f"PWD={config.get('SQL_PASSWORD', '')}")

connection_string = ";".join(parts) + ";"

print("\n3. PRUEBA DIRECTA CON PYODBC")

try:
    with pyodbc.connect(connection_string, timeout=10) as conn:
        row = conn.cursor().execute(
            "SELECT @@SERVERNAME, DB_NAME()"
        ).fetchone()

        print("CONEXION PYODBC EXITOSA")
        print("Servidor:", row[0])
        print("Base:", row[1])

except Exception as exc:
    print("ERROR PYODBC:")
    print(repr(exc))
    sys.exit(1)

print("\n4. COMPROBACION DE BASE DE DATOS")

with pyodbc.connect(connection_string) as conn:
    exists = conn.cursor().execute(
        "SELECT DB_ID(?)", database
    ).fetchone()[0]

print("Base existente:", bool(exists))

if not exists:
    print("La base todavia no existe. Ejecuta schema.sql en SSMS.")
    sys.exit(0)

print("\n5. PRUEBA CON SQLALCHEMY")

parts[2] = f"DATABASE={database}"
connection_string = ";".join(parts) + ";"

try:
    url = URL.create(
        "mssql+pyodbc",
        query={"odbc_connect": quote_plus(connection_string)}
    )

    engine = create_engine(url, pool_pre_ping=True)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT @@SERVERNAME, DB_NAME()")
        ).fetchone()

        print("CONEXION SQLALCHEMY EXITOSA")
        print("Servidor:", row[0])
        print("Base:", row[1])

    engine.dispose()

except Exception as exc:
    print("ERROR SQLALCHEMY:")
    print(repr(exc))
    sys.exit(1)

print("\n" + "=" * 55)
print("DIAGNOSTICO FINALIZADO")
print("=" * 55)
