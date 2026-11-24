from pathlib import Path
import sqlite3
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"
SALIDA = BASE / "reports/auditoria_concentracion"

SALIDA.mkdir(parents=True, exist_ok=True)

DB = SALIDA / "concentracion.sqlite"

if DB.exists():
    DB.unlink()

con = sqlite3.connect(DB)

con.execute("""
CREATE TABLE hashes (
    hash TEXT PRIMARY KEY,
    frecuencia INTEGER,
    ano TEXT,
    departamento TEXT,
    provincia TEXT,
    distrito TEXT,
    ubigeo TEXT,
    semana TEXT,
    diagnostic TEXT,
    tipo_dx TEXT
)
""")

columnas = [
    "departamento", "provincia", "distrito",
    "localidad", "enfermedad", "ano", "semana",
    "diagnostic", "tipo_dx", "diresa", "ubigeo",
    "localcod", "edad", "tipo_edad", "sexo"
]

total = 0

print("INICIANDO AUDITORIA DE CONCENTRACION")

try:

    for i, chunk in enumerate(pd.read_csv(
        ARCHIVO,
        chunksize=100_000,
        encoding="utf-8-sig",
        dtype="string",
        low_memory=False
    ), start=1):

        chunk.columns = (
            chunk.columns.str.strip().str.lower()
        )

        total += len(chunk)

        chunk["_hash"] = (
            pd.util.hash_pandas_object(
                chunk[columnas],
                index=False
            )
            .astype("uint64")
            .astype(str)
        )

        agrupado = (
            chunk.groupby("_hash", sort=False)
            .agg(
                frecuencia=("_hash", "size"),
                ano=("ano", "first"),
                departamento=("departamento", "first"),
                provincia=("provincia", "first"),
                distrito=("distrito", "first"),
                ubigeo=("ubigeo", "first"),
                semana=("semana", "first"),
                diagnostic=("diagnostic", "first"),
                tipo_dx=("tipo_dx", "first")
            )
            .reset_index()
        )

        registros = list(
            agrupado.itertuples(index=False, name=None)
        )

        con.executemany("""
            INSERT INTO hashes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hash)
            DO UPDATE SET
                frecuencia = frecuencia + excluded.frecuencia
        """, registros)

        con.commit()

        print(f"Bloque {i} | {total:,} registros")

    # =================================
    # RESULTADOS GENERALES
    # =================================

    general = con.execute("""
        SELECT
            COUNT(*),
            SUM(frecuencia),
            SUM(frecuencia - 1),
            MAX(frecuencia)
        FROM hashes
        WHERE frecuencia > 1
    """).fetchone()

    grupos = int(general[0])
    registros = int(general[1])
    adicionales = int(general[2])
    maximo = int(general[3])

    # =================================
    # DISTRIBUCION POR DIMENSION
    # =================================

    dimensiones = [
        ("ano", "30_duplicados_por_anio.csv"),
        ("departamento", "31_duplicados_por_departamento.csv"),
        ("diagnostic", "32_duplicados_por_diagnostico.csv"),
        ("tipo_dx", "33_duplicados_por_tipo.csv")
    ]

    for campo, nombre in dimensiones:

        consulta = f"""
            SELECT
                COALESCE({campo}, 'SIN DATO') AS categoria,
                COUNT(*) AS grupos,
                SUM(frecuencia) AS registros_en_grupos,
                SUM(frecuencia - 1) AS repeticiones_adicionales
            FROM hashes
            WHERE frecuencia > 1
            GROUP BY {campo}
            ORDER BY repeticiones_adicionales DESC
        """

        resultado = pd.read_sql_query(consulta, con)

        resultado.to_csv(
            SALIDA / nombre,
            index=False,
            encoding="utf-8-sig"
        )

    # =================================
    # TOP 100 GRUPOS MAS REPETIDOS
    # =================================

    top = pd.read_sql_query("""
        SELECT
            frecuencia,
            ano,
            departamento,
            provincia,
            distrito,
            ubigeo,
            semana,
            diagnostic,
            tipo_dx
        FROM hashes
        WHERE frecuencia > 1
        ORDER BY frecuencia DESC
        LIMIT 100
    """, con)

    top.to_csv(
        SALIDA / "34_top_100_repeticiones.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # =================================
    # FRECUENCIAS
    # =================================

    frecuencia = pd.read_sql_query("""
        SELECT
            frecuencia,
            COUNT(*) AS cantidad_grupos,
            SUM(frecuencia - 1) AS repeticiones_adicionales
        FROM hashes
        WHERE frecuencia > 1
        GROUP BY frecuencia
        ORDER BY frecuencia
    """, con)

    frecuencia.to_csv(
        SALIDA / "35_distribucion_frecuencias.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # =================================
    # INFORME FINAL
    # =================================

    resumen = f"""
AUDITORIA DE CONCENTRACION DE DUPLICADOS
==================================================

Registros originales procesados: {total:,}

Grupos repetidos: {grupos:,}
Registros dentro de grupos repetidos: {registros:,}
Repeticiones adicionales: {adicionales:,}

Frecuencia maxima: {maximo}

Comparacion con auditoria anterior:
149,433 repeticiones adicionales.

Diferencia:
{adicionales - 149433:,}

Archivos generados:
30_duplicados_por_anio.csv
31_duplicados_por_departamento.csv
32_duplicados_por_diagnostico.csv
33_duplicados_por_tipo.csv
34_top_100_repeticiones.csv
35_distribucion_frecuencias.csv

No se eliminaron registros.
"""

    (SALIDA / "resumen_concentracion.txt").write_text(
        resumen,
        encoding="utf-8"
    )

    print(resumen)

except Exception as e:
    print("ERROR:", e)
    raise

finally:
    con.close()

print("Auditoria finalizada.")
print("Resultados:", SALIDA)
