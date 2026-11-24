from pathlib import Path
import sqlite3
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"

SALIDA = BASE / "reports/auditoria_duplicados_pandas"
SALIDA.mkdir(parents=True, exist_ok=True)

DB = SALIDA / "duplicados.sqlite"

# Reiniciar solamente la base temporal de auditoria
if DB.exists():
    DB.unlink()

con = sqlite3.connect(DB)

con.execute("""
CREATE TABLE hashes (
    hash TEXT PRIMARY KEY,
    frecuencia INTEGER NOT NULL
)
""")

total = 0
bloque = 100_000

print("=" * 55)
print("AUDITORIA DE DUPLICADOS CON PANDAS + SQLITE")
print("=" * 55)

try:

    for i, chunk in enumerate(pd.read_csv(
        ARCHIVO,
        chunksize=bloque,
        encoding="utf-8-sig",
        dtype="string",
        low_memory=False,
        engine="c"
    ), start=1):

        chunk.columns = (
            chunk.columns.str.strip().str.lower()
        )

        if len(chunk.columns) != 15:
            raise ValueError(
                f"Se esperaban 15 columnas y se encontraron "
                f"{len(chunk.columns)}"
            )

        total += len(chunk)

        # Huella de cada fila considerando sus 15 columnas
        hashes = (
            pd.util.hash_pandas_object(
                chunk,
                index=False
            )
            .astype("uint64")
            .astype(str)
        )

        # Agrupar coincidencias dentro del bloque
        frecuencias = hashes.value_counts(sort=False)

        registros = [
            (str(h), int(c))
            for h, c in frecuencias.items()
        ]

        # Acumular coincidencias entre bloques
        con.executemany("""
            INSERT INTO hashes (hash, frecuencia)
            VALUES (?, ?)
            ON CONFLICT(hash)
            DO UPDATE SET
                frecuencia = frecuencia + excluded.frecuencia
        """, registros)

        con.commit()

        print(
            f"Bloque {i} | "
            f"Registros procesados: {total:,}"
        )

    # ==================================
    # RESULTADOS
    # ==================================

    filas = con.execute("""
        SELECT
            COUNT(*),
            SUM(frecuencia),
            SUM(CASE WHEN frecuencia > 1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN frecuencia > 1
                THEN frecuencia ELSE 0 END),
            MAX(frecuencia)
        FROM hashes
    """).fetchone()

    filas_unicas = int(filas[0])
    registros_contabilizados = int(filas[1])
    grupos_repetidos = int(filas[2])
    registros_repetidos = int(filas[3])
    frecuencia_maxima = int(filas[4])

    adicionales = registros_contabilizados - filas_unicas

    # Distribucion de frecuencias
    distribucion = con.execute("""
        SELECT frecuencia, COUNT(*)
        FROM hashes
        WHERE frecuencia > 1
        GROUP BY frecuencia
        ORDER BY frecuencia
    """).fetchall()

    pd.DataFrame(
        distribucion,
        columns=["frecuencia", "cantidad_grupos"]
    ).to_csv(
        SALIDA / "24_frecuencia_duplicados.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # Exportar hashes de grupos repetidos
    grupos = pd.read_sql_query("""
        SELECT hash, frecuencia
        FROM hashes
        WHERE frecuencia > 1
        ORDER BY frecuencia DESC
    """, con)

    grupos.to_csv(
        SALIDA / "25_grupos_hash.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # Informe
    resumen = f"""
AUDITORIA DE DUPLICADOS - PANDAS + SQLITE
==================================================

Registros procesados: {total:,}
Registros contabilizados: {registros_contabilizados:,}

Filas unicas por hash: {filas_unicas:,}
Grupos con coincidencias: {grupos_repetidos:,}

Registros dentro de grupos repetidos: {registros_repetidos:,}
Repeticiones adicionales: {adicionales:,}

Frecuencia maxima de una fila: {frecuencia_maxima}

Resultado anterior:
149,433 repeticiones adicionales

Diferencia respecto al resultado anterior:
{adicionales - 149433:,}

IMPORTANTE:
Las coincidencias se determinan mediante huellas
de las 15 columnas originales.

No se han eliminado registros.
"""

    (SALIDA / "resumen_duplicados_pandas.txt").write_text(
        resumen,
        encoding="utf-8"
    )

    print(resumen)
    print("Auditoria finalizada correctamente.")

except Exception as e:
    print("\nERROR:", str(e))
    raise

finally:
    con.close()

print("Resultados guardados en:", SALIDA)
