import sys
from pathlib import Path
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dengue_common import get_sql_engine

print("\n3. CONEXION SQLALCHEMY")

engine = get_sql_engine()

try:
    with engine.connect() as conn:

        query = text("""
            SELECT
                @@SERVERNAME AS servidor,
                DB_NAME() AS base_datos,
                CONNECTIONPROPERTY('net_transport') AS transporte,
                CONNECTIONPROPERTY('local_net_address') AS direccion_local,
                CONNECTIONPROPERTY('local_tcp_port') AS puerto_tcp,
                CONNECTIONPROPERTY('client_net_address') AS cliente
        """)

        row = conn.execute(query).mappings().one()

        for key, value in row.items():
            print(f"{key}: {value}")

        print("\n4. VERIFICACION TABLA GEOGRAFICA")

        result = conn.execute(text("""
            SELECT
                COUNT(*) AS registros,
                COUNT(latitud) AS con_latitud,
                COUNT(longitud) AS con_longitud
            FROM dbo.dim_distrito_geo
        """)).mappings().one()

        print(dict(result))

        print("\nCONEXION Y TABLA GEOGRAFICA CORRECTAS")

finally:
    engine.dispose()