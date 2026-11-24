from pathlib import Path
import duckdb
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"
SALIDA = BASE / "reports/auditoria_duplicados"

SALIDA.mkdir(parents=True, exist_ok=True)

DESTINO = SALIDA / "24_grupos_duplicados.csv"

# Rutas compatibles con SQL
src = str(ARCHIVO).replace("\\", "/").replace("'", "''")
dst = str(DESTINO).replace("\\", "/").replace("'", "''")

columnas = [
    "departamento", "provincia", "distrito",
    "localidad", "enfermedad", "ano", "semana",
    "diagnostic", "tipo_dx", "diresa", "ubigeo",
    "localcod", "edad", "tipo_edad", "sexo"
]

seleccion = ", ".join(columnas)
agrupacion = ", ".join(columnas)

print("INICIANDO AUDITORIA CON DUCKDB")
print("Buscando combinaciones exactamente repetidas...\n")

con = duckdb.connect()

consulta = f"""
COPY (
    SELECT
        {seleccion},
        COUNT(*) AS frecuencia
    FROM read_csv(
        '{src}',
        header = true,
        all_varchar = true,
        strict_mode = false
    )
    GROUP BY {agrupacion}
    HAVING COUNT(*) > 1
)
TO '{dst}'
(HEADER, DELIMITER ',');
"""

con.execute(consulta)

print("Grupos de duplicados identificados.")

# Leer resultados
df = pd.read_csv(
    DESTINO,
    dtype="string"
)

df["frecuencia"] = pd.to_numeric(
    df["frecuencia"], errors="coerce"
)

# Calculos
grupos = len(df)

registros_repetidos = int(
    df["frecuencia"].sum()
)

duplicados_adicionales = int(
    (df["frecuencia"] - 1).sum()
)

max_frecuencia = int(
    df["frecuencia"].max()
)

# Frecuencia de repeticion
frecuencias = (
    df["frecuencia"]
    .value_counts()
    .sort_index()
    .rename_axis("veces_repetida")
    .reset_index(name="cantidad_grupos")
)

frecuencias.to_csv(
    SALIDA / "25_frecuencia_repeticiones.csv",
    index=False,
    encoding="utf-8-sig"
)

# Concentracion por ano
for columna, nombre in [
    ("ano", "26_duplicados_por_anio.csv"),
    ("departamento", "27_duplicados_por_departamento.csv"),
    ("diagnostic", "28_duplicados_por_diagnostico.csv"),
    ("tipo_dx", "29_duplicados_por_tipo.csv")
]:

    resultado = (
        df.groupby(columna, dropna=False)
        .agg(
            grupos=("frecuencia", "size"),
            registros=("frecuencia", "sum")
        )
        .reset_index()
    )

    resultado["repeticiones_adicionales"] = (
        resultado["registros"] - resultado["grupos"]
    )

    resultado.to_csv(
        SALIDA / nombre,
        index=False,
        encoding="utf-8-sig"
    )

# Resumen
resumen = [
    "SEXTA AUDITORIA - DUPLICADOS EXACTOS",
    "=" * 50,
    f"Grupos con filas repetidas: {grupos:,}",
    f"Registros dentro de esos grupos: {registros_repetidos:,}",
    f"Repeticiones adicionales: {duplicados_adicionales:,}",
    f"Frecuencia maxima de una combinacion: {max_frecuencia}",
    "",
    "COMPARACION CON AUDITORIA ANTERIOR:",
    "Repeticiones anteriores: 149433",
    f"Repeticiones DuckDB: {duplicados_adicionales}",
    f"Diferencia: {duplicados_adicionales - 149433}",
    "",
    "IMPORTANTE: No se eliminaron registros."
]

(SALIDA / "resumen_duplicados.txt").write_text(
    "\n".join(resumen),
    encoding="utf-8"
)

print("\n" + "=" * 50)
print("RESULTADOS")
print("=" * 50)
print("Grupos repetidos:", grupos)
print("Registros dentro de grupos:", registros_repetidos)
print("Repeticiones adicionales:", duplicados_adicionales)
print("Frecuencia maxima:", max_frecuencia)
print("\nResultados guardados en:", SALIDA)

con.close()

