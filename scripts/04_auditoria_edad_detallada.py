from pathlib import Path
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"

SALIDA = BASE / "reports/auditoria_edad_detallada"

SALIDA.mkdir(parents=True, exist_ok=True)

columnas = [
    "edad", "tipo_edad", "ano", "semana",
    "ubigeo", "departamento", "provincia",
    "distrito", "localidad", "localcod",
    "sexo", "diagnostic", "tipo_dx", "enfermedad"
]

resumen = []
anomalias = []
conteo_anual = []

total_mayores_120 = 0
total_negativos = 0
total_edad_cero = 0

print("INICIANDO AUDITORIA DETALLADA DE EDADES")

for i, chunk in enumerate(pd.read_csv(
    ARCHIVO,
    usecols=columnas,
    chunksize=200_000,
    encoding="utf-8-sig",
    dtype={"ubigeo": "string", "localcod": "string"},
    low_memory=False
), start=1):

    chunk["edad"] = pd.to_numeric(
        chunk["edad"], errors="coerce"
    )

    chunk["tipo_edad"] = (
        chunk["tipo_edad"]
        .astype("string")
        .str.strip()
        .str.upper()
    )

    # Detectar edades extremas expresadas en años
    condicion = (
        (chunk["tipo_edad"] == "A")
        & (chunk["edad"] > 120)
    )

    extremos = chunk[condicion].copy()

    if not extremos.empty:

        total_mayores_120 += len(extremos)

        anomalias.append(extremos)

        anual = (
            extremos.groupby(
                ["ano", "departamento", "distrito"]
            )
            .size()
            .reset_index(name="registros")
        )

        conteo_anual.append(anual)

    # Valores negativos
    total_negativos += int(
        (chunk["edad"] < 0).sum()
    )

    # Edades iguales a cero
    total_edad_cero += int(
        (chunk["edad"] == 0).sum()
    )

    # Estadisticas por tipo de edad
    for tipo, grupo in chunk.groupby("tipo_edad"):

        edades = grupo["edad"].dropna()

        resumen.append({
            "tipo_edad": tipo,
            "registros": len(edades),
            "minimo": edades.min(),
            "mediana": edades.median(),
            "percentil_95": edades.quantile(0.95),
            "percentil_99": edades.quantile(0.99),
            "maximo": edades.max()
        })

    print(f"Bloque {i} revisado")

# ===================================
# CONSOLIDAR RESULTADOS
# ===================================

df_resumen = (
    pd.DataFrame(resumen)
    .groupby("tipo_edad")
    .agg(
        registros=("registros", "sum"),
        minimo=("minimo", "min"),
        maximo=("maximo", "max")
    )
    .reset_index()
)

df_resumen.to_csv(
    SALIDA / "18_resumen_edades.csv",
    index=False,
    encoding="utf-8-sig"
)

if anomalias:

    df_anomalias = pd.concat(
        anomalias, ignore_index=True
    )

else:
    df_anomalias = pd.DataFrame(columns=columnas)

df_anomalias.to_csv(
    SALIDA / "19_edades_mayores_120.csv",
    index=False,
    encoding="utf-8-sig"
)

if conteo_anual:

    df_anual = pd.concat(
        conteo_anual, ignore_index=True
    )

    df_anual.to_csv(
        SALIDA / "20_anomalias_por_territorio.csv",
        index=False,
        encoding="utf-8-sig"
    )

print("\n===================================")
print("RESULTADOS DE LA AUDITORIA")
print("===================================")

print("Edades A superiores a 120:", total_mayores_120)
print("Edades negativas:", total_negativos)
print("Edades iguales a cero:", total_edad_cero)

print("\nREGISTROS EXTREMOS:")
print(df_anomalias.head(20).to_string(index=False))

print("\nArchivos guardados en:")
print(SALIDA)
