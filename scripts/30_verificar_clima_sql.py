import sys
from pathlib import Path
from sqlalchemy import text

# Incorporar la raiz del proyecto al sistema de importacion
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dengue_common import get_sql_engine

print("=" * 55)
print("VERIFICACION DE INTEGRACION CLIMATICA SQL SERVER")
print("=" * 55)

engine = get_sql_engine()

tables = [
    "dbo.fact_semanal_dengue",
    "dbo.vw_historico_dengue"
]

columns = """
    COUNT(*) AS registros,
    COUNT(tmean) AS con_temperatura,
    COUNT(tmax) AS con_tmax,
    COUNT(tmin) AS con_tmin,
    COUNT(humr) AS con_humedad,
    COUNT(ptot) AS con_precipitacion,
    MIN(fecha_inicio) AS fecha_minima,
    MAX(fecha_inicio) AS fecha_maxima
"""

try:
    with engine.connect() as conn:

        for table in tables:
            print("\n==========", table, "==========")

            query = text(
                f"SELECT {columns} FROM {table}"
            )

            row = conn.execute(query).mappings().one()
            print(dict(row))

            sample_query = text(f"""
                SELECT TOP 5
                    ubigeo,
                    departamento,
                    distrito,
                    fecha_inicio,
                    casos_reportados,
                    tmean,
                    tmax,
                    tmin,
                    humr,
                    ptot
                FROM {table}
                WHERE tmean IS NOT NULL
                   OR tmax IS NOT NULL
                   OR tmin IS NOT NULL
                   OR humr IS NOT NULL
                   OR ptot IS NOT NULL
                ORDER BY fecha_inicio DESC
            """)

            samples = conn.execute(sample_query).mappings().all()

            print("\nMUESTRA DE REGISTROS CLIMATICOS:")

            if samples:
                for item in samples:
                    print(dict(item))
            else:
                print("NO SE ENCONTRARON REGISTROS CON CLIMA.")

finally:
    engine.dispose()

print("\n" + "=" * 55)
print("VERIFICACION FINALIZADA")
print("=" * 55)