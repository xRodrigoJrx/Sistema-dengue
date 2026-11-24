from pathlib import Path
import re
import sys
import pyodbc
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
config = dotenv_values(ROOT / ".env", encoding="utf-8-sig")

server = config.get("SQL_SERVER")
driver = config.get("SQL_DRIVER")
database = config.get("SQL_DATABASE", "dengue_analytics")

if not server or not driver:
    raise ValueError("Falta SQL_SERVER o SQL_DRIVER en el archivo .env")

schema_path = ROOT / "sql" / "schema.sql"

if not schema_path.exists():
    raise FileNotFoundError(f"No existe: {schema_path}")

sql_script = schema_path.read_text(encoding="utf-8-sig")

# Separar el script por instrucciones GO de SQL Server.
batches = re.split(
    r"(?im)^\s*GO\s*;?\s*(?:--.*)?$",
    sql_script
)

connection_string = (
    f"DRIVER={{{driver}}};"
    f"SERVER={server};"
    "DATABASE=master;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
)

print("=" * 55)
print("IMPLEMENTACION DEL ESQUEMA DENGUE")
print("=" * 55)
print("Servidor:", server)
print("Base de datos:", database)

with pyodbc.connect(connection_string, autocommit=True) as conn:
    cursor = conn.cursor()

    ejecutados = 0

    for batch in batches:
        if batch.strip():
            cursor.execute(batch)
            ejecutados += 1
            print(f"Bloque SQL {ejecutados}: OK")

    cursor.execute(f"USE [{database}]")

    print("\nTABLAS CREADAS:")

    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)

    tablas = [row[0] for row in cursor.fetchall()]

    for tabla in tablas:
        print(" -", tabla)

    print("\nVISTAS CREADAS:")

    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.VIEWS
        ORDER BY TABLE_NAME
    """)

    vistas = [row[0] for row in cursor.fetchall()]

    for vista in vistas:
        print(" -", vista)

    tablas_esperadas = {
        "dim_distrito",
        "fact_semanal_dengue",
        "fact_pronosticos",
        "fact_metricas_modelo"
    }

    vistas_esperadas = {
        "vw_resumen_nacional_pronostico",
        "vw_ranking_distritos_pronostico",
        "vw_historico_dengue"
    }

    faltantes = (
        tablas_esperadas - set(tablas)
    ) | (
        vistas_esperadas - set(vistas)
    )

    if faltantes:
        print("\nFALTAN OBJETOS:")
        for objeto in sorted(faltantes):
            print(" -", objeto)
        sys.exit(1)

    print("\n" + "=" * 55)
    print("ESQUEMA SQL IMPLEMENTADO CORRECTAMENTE")
    print("4 TABLAS Y 3 VISTAS VERIFICADAS")
    print("=" * 55)

