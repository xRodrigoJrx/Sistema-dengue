import sys
import re
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dengue_common import get_sql_engine

CLIMA_DIR = ROOT / "data" / "processed" / "clima_integrado"

KEYS = ["ubigeo", "ano", "semana"]

VARIABLES = ["tmean", "tmax", "tmin", "humr", "ptot"]

COLUMNS = KEYS + VARIABLES

STAGE = "dbo.stg_clima_dengue_load"

EXPECTED_YEARS = set(range(2000, 2026))

engine = get_sql_engine()


def validate_file(file, conn, year):

    df = pd.read_csv(
        file,
        usecols=COLUMNS,
        dtype={"ubigeo": "string"}
    )

    df["ubigeo"] = df["ubigeo"].str.strip()

    if not df["ubigeo"].str.fullmatch(r"\d{6}").all():
        raise ValueError(f"UBIGEO invalido en {file.name}")

    for col in ["ano", "semana"] + VARIABLES:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df[["ano", "semana"] + VARIABLES].isna().any().any():
        raise ValueError(f"Hay valores nulos en {file.name}")

    if not df["ano"].eq(year).all():
        raise ValueError(f"El año no coincide en {file.name}")

    df["ano"] = df["ano"].astype("int64")
    df["semana"] = df["semana"].astype("int64")

    if df.duplicated(KEYS).any():
        raise ValueError(f"Claves duplicadas en {file.name}")

    if not (df["semana"].between(1, 53)).all():
        raise ValueError(f"Semana invalida en {file.name}")

    climate_keys = set(
        zip(df.ubigeo, df.ano, df.semana)
    )

    sql_df = pd.read_sql_query(
        text("""
            SELECT
                LTRIM(RTRIM(ubigeo)) AS ubigeo,
                ano,
                semana
            FROM dbo.fact_semanal_dengue
            WHERE ano = :year
        """),
        conn,
        params={"year": year}
    )

    sql_keys = set(
        zip(
            sql_df.ubigeo.astype(str).str.strip(),
            sql_df.ano.astype(int),
            sql_df.semana.astype(int)
        )
    )

    if climate_keys != sql_keys:
        raise ValueError(
            f"Las claves no coinciden para {year}"
        )

    return len(df)


def main():

    print("=" * 65)
    print("INTEGRACION CLIMATICA DENGUE 2000-2025")
    print("=" * 65)

    files = {}

    for file in CLIMA_DIR.glob("clima_dengue_peru_*.csv"):
        match = re.search(r"_(\d{4})\.csv$", file.name)

        if match:
            year = int(match.group(1))
            files[year] = file

    if set(files) != EXPECTED_YEARS:
        raise RuntimeError(
            "No se encontraron exactamente los 26 archivos esperados."
        )

    total_expected = 0

    try:

        with engine.begin() as conn:

            # 1. Comprobar estado original de SQL

            print("\n1. COMPROBANDO TABLA HISTORICA")

            current = conn.execute(text("""
                SELECT
                    COUNT_BIG(*) AS registros,
                    COUNT(tmean) AS tmean,
                    COUNT(tmax) AS tmax,
                    COUNT(tmin) AS tmin,
                    COUNT(humr) AS humr,
                    COUNT(ptot) AS ptot
                FROM dbo.fact_semanal_dengue
            """)).mappings().one()

            print(dict(current))

            if current["registros"] != 2566087:
                raise RuntimeError(
                    "El total historico no coincide con el esperado."
                )

            if any(current[v] != 0 for v in VARIABLES):
                raise RuntimeError(
                    "Las columnas climaticas ya contienen datos. "
                    "Se cancela para evitar sobrescribirlos."
                )

            # 2. Validar nuevamente los 26 archivos

            print("\n2. VALIDANDO LOS ARCHIVOS CLIMATICOS")

            for year in sorted(files):

                count = validate_file(
                    files[year],
                    conn,
                    year
                )

                total_expected += count

                print(
                    f"{year}: {count:,} registros | "
                    "COINCIDENCIA EXACTA"
                )

            if total_expected != current["registros"]:
                raise RuntimeError(
                    "El total de archivos no coincide con SQL."
                )

            # 3. Crear tabla de carga

            print("\n3. CREANDO TABLA DE CARGA")

            exists = conn.execute(
                text("SELECT OBJECT_ID(:name, 'U')"),
                {"name": STAGE}
            ).scalar_one()

            if exists is not None:
                raise RuntimeError(
                    "Ya existe una tabla de carga anterior. "
                    "No se modificara automaticamente."
                )

            conn.exec_driver_sql("""
                CREATE TABLE dbo.stg_clima_dengue_load (
                    ubigeo CHAR(6) NOT NULL,
                    ano SMALLINT NOT NULL,
                    semana SMALLINT NOT NULL,
                    tmean FLOAT NOT NULL,
                    tmax FLOAT NOT NULL,
                    tmin FLOAT NOT NULL,
                    humr FLOAT NOT NULL,
                    ptot FLOAT NOT NULL,
                    CONSTRAINT PK_stg_clima_dengue
                    PRIMARY KEY CLUSTERED (ubigeo, ano, semana)
                )
            """)

            # 4. Cargar archivos por bloques

            print("\n4. CARGANDO INFORMACION CLIMATICA")

            raw = conn.connection.driver_connection
            cursor = raw.cursor()
            cursor.fast_executemany = True

            insert_sql = """
                INSERT INTO dbo.stg_clima_dengue_load
                (ubigeo, ano, semana, tmean, tmax, tmin, humr, ptot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """

            processed = 0
            last_report = 0

            try:

                for year in sorted(files):

                    file = files[year]

                    for chunk in pd.read_csv(
                        file,
                        usecols=COLUMNS,
                        dtype={"ubigeo": "string"},
                        chunksize=25000
                    ):

                        chunk["ubigeo"] = (
                            chunk["ubigeo"].str.strip()
                        )

                        for col in ["ano", "semana"] + VARIABLES:
                            chunk[col] = pd.to_numeric(
                                chunk[col],
                                errors="raise"
                            )

                        if chunk[COLUMNS].isna().any().any():
                            raise ValueError(
                                f"Valores nulos en {file.name}"
                            )

                        rows = [
                            (
                                str(r[0]),
                                int(r[1]),
                                int(r[2]),
                                float(r[3]),
                                float(r[4]),
                                float(r[5]),
                                float(r[6]),
                                float(r[7])
                            )
                            for r in chunk[COLUMNS].itertuples(
                                index=False,
                                name=None
                            )
                        ]

                        cursor.executemany(
                            insert_sql,
                            rows
                        )

                        processed += len(rows)

                        if processed - last_report >= 100000:
                            print(
                                f"Registros cargados: {processed:,}"
                            )
                            last_report = processed

            finally:
                cursor.close()

            print(f"Total cargado: {processed:,}")

            # 5. Verificar tabla de carga

            print("\n5. VALIDANDO TABLA DE CARGA")

            stage_count = conn.execute(text("""
                SELECT COUNT_BIG(*)
                FROM dbo.stg_clima_dengue_load
            """)).scalar_one()

            if stage_count != total_expected:
                raise RuntimeError(
                    "El total de la tabla de carga no coincide."
                )

            unmatched = conn.execute(text("""
                SELECT COUNT_BIG(*)
                FROM dbo.stg_clima_dengue_load s
                LEFT JOIN dbo.fact_semanal_dengue f
                    ON f.ubigeo = s.ubigeo
                   AND f.ano = s.ano
                   AND f.semana = s.semana
                WHERE f.ubigeo IS NULL
            """)).scalar_one()

            if unmatched != 0:
                raise RuntimeError(
                    f"Hay {unmatched} registros sin correspondencia."
                )

            # 6. Actualizar tabla historica

            print("\n6. INTEGRANDO VARIABLES CLIMATICAS")

            conn.exec_driver_sql("""
                UPDATE f
                SET
                    f.tmean = s.tmean,
                    f.tmax = s.tmax,
                    f.tmin = s.tmin,
                    f.humr = s.humr,
                    f.ptot = s.ptot
                FROM dbo.fact_semanal_dengue f
                INNER JOIN dbo.stg_clima_dengue_load s
                    ON f.ubigeo = s.ubigeo
                   AND f.ano = s.ano
                   AND f.semana = s.semana
            """)

            # 7. Validacion posterior

            print("\n7. VERIFICANDO RESULTADOS")

            after = conn.execute(text("""
                SELECT
                    COUNT_BIG(*) AS registros,
                    COUNT(tmean) AS tmean,
                    COUNT(tmax) AS tmax,
                    COUNT(tmin) AS tmin,
                    COUNT(humr) AS humr,
                    COUNT(ptot) AS ptot
                FROM dbo.fact_semanal_dengue
            """)).mappings().one()

            print(dict(after))

            for variable in VARIABLES:

                if after[variable] != total_expected:
                    raise RuntimeError(
                        f"Integracion incompleta: {variable}"
                    )

            if after["registros"] != total_expected:
                raise RuntimeError(
                    "Cambio inesperado en el total historico."
                )

            # Comprobar vista para Power BI

            view = conn.execute(text("""
                SELECT
                    COUNT_BIG(*) AS registros,
                    COUNT(tmean) AS tmean,
                    COUNT(tmax) AS tmax,
                    COUNT(tmin) AS tmin,
                    COUNT(humr) AS humr,
                    COUNT(ptot) AS ptot
                FROM dbo.vw_historico_dengue
            """)).mappings().one()

            print("\nESTADO DE LA VISTA HISTORICA:")
            print(dict(view))

            if any(view[v] != total_expected for v in VARIABLES):
                raise RuntimeError(
                    "La vista historica no refleja el clima completo."
                )

            # 8. Eliminar tabla auxiliar

            conn.exec_driver_sql("""
                DROP TABLE dbo.stg_clima_dengue_load
            """)

            print("\nTABLA AUXILIAR ELIMINADA.")

        # La transaccion se confirma al salir del bloque.

        print("\n" + "=" * 65)
        print("INTEGRACION CLIMATICA COMPLETADA")
        print("=" * 65)
        print(f"Registros historicos: {total_expected:,}")
        print("Temperatura media: 100%")
        print("Temperatura maxima: 100%")
        print("Temperatura minima: 100%")
        print("Humedad relativa: 100%")
        print("Precipitacion: 100%")
        print("Vista Power BI: VALIDADA")
        print("Transaccion SQL: CONFIRMADA")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()