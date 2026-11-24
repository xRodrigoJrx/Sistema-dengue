from pathlib import Path
import pandas as pd
from dengue_common import get_sql_engine

ROOT = Path(__file__).resolve().parents[1]

DATASET = (
    ROOT / "data" / "processed" / "dataset_maestro" /
    "dataset_maestro_dengue_2000_2025.csv.gz"
)

CHUNK = 10000

GEO_COLS = [
    "ubigeo",
    "nombre_departamento_geografico",
    "nombre_provincia_geografico",
    "nombre_distrito_geografico",
    "departamento",
    "provincia",
    "distrito"
]

FACT_COLS = [
    "ubigeo", "ano", "semana",
    "fecha_inicio", "fecha_fin",
    "casos_dengue_reportados",
    "registro_minsa",
    "poblacion_proyectada",
    "tmean", "tmax", "tmin", "humr", "ptot",
    "clima_recuperado",
    "clima_grupo",
    "clima_metodo_extraccion"
]


def normalizar_ubigeo(s):
    return (
        s.astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )


def nombre_valido(preferido, alternativo):
    for valor in (preferido, alternativo):
        if pd.notna(valor) and str(valor).strip():
            return str(valor).strip()[:100]
    return None


def valor_sql(v):
    if pd.isna(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def main():

    print("=" * 60)
    print("CARGA HISTORICA DENGUE 2000-2025")
    print("=" * 60)

    if not DATASET.exists():
        raise FileNotFoundError(DATASET)

    print("\n1. LEYENDO DISTRITOS...")

    distritos = {}

    for chunk in pd.read_csv(
        DATASET,
        compression="gzip",
        usecols=GEO_COLS,
        dtype={"ubigeo": "string"},
        chunksize=100000
    ):

        chunk["ubigeo"] = normalizar_ubigeo(chunk["ubigeo"])

        for row in chunk.itertuples(index=False, name=None):

            ub, dep_g, prov_g, dist_g, dep, prov, dist = row

            if pd.isna(ub):
                continue

            distritos[str(ub)] = (
                str(ub),
                nombre_valido(dep_g, dep),
                nombre_valido(prov_g, prov),
                nombre_valido(dist_g, dist)
            )

    dim_rows = [distritos[k] for k in sorted(distritos)]

    print("Distritos identificados:", len(dim_rows))

    print("\n2. CONECTANDO A SQL SERVER...")

    engine = get_sql_engine()
    raw = engine.raw_connection()
    cursor = raw.cursor()

    try:

        cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.dim_distrito"
        )
        dim_existentes = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.fact_semanal_dengue"
        )
        fact_existentes = cursor.fetchone()[0]

        if dim_existentes > 0 or fact_existentes > 0:
            raise RuntimeError(
                "Las tablas historicas ya contienen registros. "
                "Se cancela para evitar duplicados."
            )

        print("Conexion correcta.")
        print("\n3. INICIANDO TRANSACCION...")

        cursor.execute("SET XACT_ABORT ON")
        cursor.execute("BEGIN TRANSACTION")

        cursor.fast_executemany = True

        sql_dim = """
            INSERT INTO dbo.dim_distrito
            (ubigeo, departamento, provincia, distrito)
            VALUES (?, ?, ?, ?)
        """

        cursor.executemany(sql_dim, dim_rows)

        print("Distritos insertados:", len(dim_rows))

        print("\n4. CARGANDO REGISTROS HISTORICOS...")

        sql_fact = """
            INSERT INTO dbo.fact_semanal_dengue (
                ubigeo, ano, semana,
                fecha_inicio, fecha_fin,
                casos_reportados, registro_minsa,
                poblacion_proyectada,
                tmean, tmax, tmin, humr, ptot,
                clima_recuperado, clima_grupo,
                clima_metodo_extraccion
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        insertados = 0

        for chunk in pd.read_csv(
            DATASET,
            compression="gzip",
            usecols=FACT_COLS,
            dtype={"ubigeo": "string"},
            chunksize=CHUNK
        ):

            chunk["ubigeo"] = normalizar_ubigeo(
                chunk["ubigeo"]
            )

            for col in [
                "ano", "semana",
                "casos_dengue_reportados",
                "registro_minsa",
                "clima_recuperado"
            ]:
                chunk[col] = pd.to_numeric(
                    chunk[col], errors="coerce"
                ).astype("Int64")

            for col in [
                "fecha_inicio", "fecha_fin"
            ]:
                chunk[col] = pd.to_datetime(
                    chunk[col], errors="coerce"
                ).dt.date

            for col in [
                "poblacion_proyectada",
                "tmean", "tmax", "tmin", "humr", "ptot"
            ]:
                chunk[col] = pd.to_numeric(
                    chunk[col], errors="coerce"
                )

            obligatorias = [
                "ubigeo", "ano", "semana",
                "fecha_inicio", "casos_dengue_reportados"
            ]

            if chunk[obligatorias].isna().any().any():
                raise ValueError(
                    "Se encontraron campos obligatorios vacios."
                )

            rows = [
                tuple(valor_sql(v) for v in row)
                for row in chunk[FACT_COLS].itertuples(
                    index=False, name=None
                )
            ]

            cursor.executemany(sql_fact, rows)

            insertados += len(rows)

            print(
                f"Registros procesados: {insertados:,}"
            )

        print("\n5. CONFIRMANDO TRANSACCION...")

        raw.commit()

        cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.fact_semanal_dengue"
        )
        total_fact = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT_BIG(*) FROM dbo.dim_distrito"
        )
        total_dim = cursor.fetchone()[0]

        print("\n" + "=" * 60)
        print("CARGA HISTORICA COMPLETADA")
        print("=" * 60)
        print("Distritos SQL:", f"{total_dim:,}")
        print("Registros SQL:", f"{total_fact:,}")
        print("Registros insertados:", f"{insertados:,}")
        print("Periodo: 2000-2025")
        print("Transaccion confirmada.")

    except Exception:
        raw.rollback()
        print("\nERROR: TRANSACCION REVERTIDA.")
        raise

    finally:
        cursor.close()
        raw.close()
        engine.dispose()


if __name__ == "__main__":
    main()

