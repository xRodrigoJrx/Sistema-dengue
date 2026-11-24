import sys
from pathlib import Path
from sqlalchemy import text

PROJECT = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")
sys.path.insert(0, str(PROJECT))

from scripts.dengue_common import get_sql_engine

engine = get_sql_engine()

try:
    with engine.connect() as conn:

        print("\n===== RESUMEN GEOGRAFICO =====")

        sql = text("""
            SELECT
                COUNT(*) AS registros,
                COUNT(DISTINCT LTRIM(RTRIM(
                    CAST(ubigeo AS VARCHAR(6))
                ))) AS ubigeos_unicos,
                SUM(CASE
                    WHEN ubigeo IS NULL
                    OR LTRIM(RTRIM(CAST(ubigeo AS VARCHAR(6)))) = ''
                    THEN 1 ELSE 0
                END) AS ubigeos_vacios,
                SUM(CASE WHEN latitud IS NULL THEN 1 ELSE 0 END)
                    AS latitudes_nulas,
                SUM(CASE WHEN longitud IS NULL THEN 1 ELSE 0 END)
                    AS longitudes_nulas,
                MIN(latitud) AS latitud_minima,
                MAX(latitud) AS latitud_maxima,
                MIN(longitud) AS longitud_minima,
                MAX(longitud) AS longitud_maxima
            FROM dbo.dim_distrito_geo
        """)

        print(dict(conn.execute(sql).mappings().one()))

        print("\n===== PRIMEROS 10 DISTRITOS =====")

        sample = text("""
            SELECT TOP 10
                ubigeo,
                departamento,
                provincia,
                distrito,
                latitud,
                longitud
            FROM dbo.dim_distrito_geo
            ORDER BY ubigeo
        """)

        for row in conn.execute(sample).mappings():
            print(dict(row))

finally:
    engine.dispose()
