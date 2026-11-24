import sys
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dengue_common import get_sql_engine

CLIMA_DIR = ROOT / "data" / "processed" / "clima_integrado"
REPORT_DIR = ROOT / "reports" / "powerbi"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

VARIABLES = ["tmean", "tmax", "tmin", "humr", "ptot"]

engine = get_sql_engine()
resultados = []

print("=" * 65)
print("VALIDACION DE CORRESPONDENCIA DENGUE + CLIMA")
print("=" * 65)

try:
    with engine.connect() as conn:

        # 1. Comprobar tabla SQL
        print("\n1. ESTADO DE TABLA SQL")

        sql = text("""
            SELECT
                COUNT_BIG(*) AS registros,
                COUNT(tmean) AS tmean,
                COUNT(tmax) AS tmax,
                COUNT(tmin) AS tmin,
                COUNT(humr) AS humr,
                COUNT(ptot) AS ptot
            FROM dbo.fact_semanal_dengue
        """)

        print(dict(conn.execute(sql).mappings().one()))

        # 2. Comprobar vista histórica
        print("\n2. ESTADO DE VISTA HISTORICA")

        sql = text("""
            SELECT
                COUNT_BIG(*) AS registros,
                COUNT(tmean) AS tmean,
                COUNT(tmax) AS tmax,
                COUNT(tmin) AS tmin,
                COUNT(humr) AS humr,
                COUNT(ptot) AS ptot
            FROM dbo.vw_historico_dengue
        """)

        print(dict(conn.execute(sql).mappings().one()))

        # 3. Examinar los archivos integrados
        files = sorted(CLIMA_DIR.glob("clima_dengue_peru_*.csv"))

        print("\n3. ARCHIVOS ENCONTRADOS:", len(files))

        for file in files:

            match = re.search(r"_(\d{4})\.csv$", file.name)

            if not match:
                continue

            year = int(match.group(1))

            print(f"\nProcesando {year}...")

            df = pd.read_csv(
                file,
                usecols=["ubigeo", "ano", "semana"] + VARIABLES,
                dtype={"ubigeo": "string"}
            )

            df["ubigeo"] = df["ubigeo"].str.strip()
            df["ano"] = pd.to_numeric(df["ano"], errors="coerce")
            df["semana"] = pd.to_numeric(df["semana"], errors="coerce")

            keys = ["ubigeo", "ano", "semana"]

            duplicates = int(df.duplicated(keys).sum())

            climate_keys = set(
                map(tuple, df[keys].drop_duplicates().values.tolist())
            )

            # Consultar claves del mismo año en SQL
            query = text("""
                SELECT
                    LTRIM(RTRIM(ubigeo)) AS ubigeo,
                    ano,
                    semana
                FROM dbo.fact_semanal_dengue
                WHERE ano = :year
            """)

            sql_df = pd.read_sql_query(
                query,
                conn,
                params={"year": year}
            )

            sql_keys = set(
                map(tuple, sql_df[keys].values.tolist())
            )

            missing_sql = climate_keys - sql_keys
            missing_climate = sql_keys - climate_keys

            nulls = {
                col: int(pd.to_numeric(
                    df[col], errors="coerce"
                ).isna().sum())
                for col in VARIABLES
            }

            row = {
                "anio": year,
                "filas_clima": len(df),
                "filas_sql": len(sql_df),
                "ubigeos": df["ubigeo"].nunique(),
                "claves_clima": len(climate_keys),
                "claves_sql": len(sql_keys),
                "duplicados_clima": duplicates,
                "faltan_en_sql": len(missing_sql),
                "faltan_en_clima": len(missing_climate),
                "nulos_tmean": nulls["tmean"],
                "nulos_tmax": nulls["tmax"],
                "nulos_tmin": nulls["tmin"],
                "nulos_humr": nulls["humr"],
                "nulos_ptot": nulls["ptot"],
                "estado": (
                    "COINCIDENCIA EXACTA"
                    if (
                        climate_keys == sql_keys
                        and duplicates == 0
                        and not any(nulls.values())
                    )
                    else "REVISAR DIFERENCIAS"
                )
            }

            resultados.append(row)

            print(
                f"Clima: {len(df):,} | "
                f"SQL: {len(sql_df):,} | "
                f"Faltan SQL: {len(missing_sql)} | "
                f"Faltan clima: {len(missing_climate)} | "
                f"Duplicados: {duplicates}"
            )

            if missing_sql:
                print("Ejemplo de claves que faltan en SQL:",
                      list(missing_sql)[:3])

            if missing_climate:
                print("Ejemplo de claves que faltan en clima:",
                      list(missing_climate)[:3])

    # 4. Guardar resultados
    report = pd.DataFrame(resultados)

    csv_path = REPORT_DIR / "31_correspondencia_clima_sql.csv"
    txt_path = REPORT_DIR / "31_correspondencia_clima_sql.txt"

    report.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("CORRESPONDENCIA CLIMA Y SQL SERVER\n\n")
        f.write(report.to_string(index=False))

        if len(report):
            f.write("\n\nRESUMEN\n")
            f.write(
                f"Años con coincidencia exacta: "
                f"{(report['estado'] == 'COINCIDENCIA EXACTA').sum()}\n"
            )
            f.write(f"Años analizados: {len(report)}\n")

    print("\n" + "=" * 65)
    print("DIAGNOSTICO COMPLETADO")
    print("Reporte CSV:", csv_path)
    print("Reporte TXT:", txt_path)

    if len(report) == 26 and (
        report["estado"] == "COINCIDENCIA EXACTA"
    ).all():
        print("\nTODOS LOS AÑOS COINCIDEN.")
        print("LISTO PARA PLANIFICAR LA INTEGRACION CLIMATICA.")
    else:
        print("\nSE DETECTARON DIFERENCIAS.")
        print("NO SE MODIFICARON DATOS SQL.")

finally:
    engine.dispose()