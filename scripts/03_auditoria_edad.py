from pathlib import Path
from collections import Counter
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"
SALIDA = BASE / "reports/auditoria_edad"

SALIDA.mkdir(parents=True, exist_ok=True)

columnas = [
    "edad", "tipo_edad", "ano", "semana",
    "ubigeo", "departamento", "provincia",
    "distrito", "sexo", "diagnostic", "tipo_dx"
]

edades_por_tipo = {}
top_edad = pd.DataFrame()
semana53 = Counter()
cobertura = Counter()

print("INICIANDO TERCERA AUDITORIA")
print("Analizando edades y semanas epidemiologicas...\n")

for i, chunk in enumerate(pd.read_csv(
    ARCHIVO,
    usecols=columnas,
    chunksize=200_000,
    encoding="utf-8-sig",
    dtype={"ubigeo": "string"},
    low_memory=False
), start=1):

    chunk.columns = (
        chunk.columns.str.strip().str.lower()
    )

    chunk["edad_num"] = pd.to_numeric(
        chunk["edad"], errors="coerce"
    )

    chunk["tipo_edad"] = (
        chunk["tipo_edad"]
        .fillna("SIN DATO")
        .astype(str).str.strip()
    )

    chunk["ano"] = pd.to_numeric(
        chunk["ano"], errors="coerce"
    )

    chunk["semana"] = pd.to_numeric(
        chunk["semana"], errors="coerce"
    )

    # Distribucion de edad por categoria
    for tipo, grupo in chunk.groupby("tipo_edad"):

        edades = grupo["edad_num"].dropna()

        if tipo not in edades_por_tipo:
            edades_por_tipo[tipo] = []

        edades_por_tipo[tipo].append(edades)

    # 100 edades mas altas
    columnas_top = [
        "edad", "edad_num", "tipo_edad",
        "ano", "semana", "ubigeo",
        "departamento", "provincia",
        "distrito", "sexo", "diagnostic", "tipo_dx"
    ]

    candidatos = chunk.nlargest(
        100, "edad_num"
    )[columnas_top]

    top_edad = pd.concat(
        [top_edad, candidatos],
        ignore_index=True
    ).nlargest(100, "edad_num")

    # Semanas epidemiologicas 53
    semana53.update(
        chunk.loc[
            chunk["semana"] == 53
        ].groupby("ano").size().to_dict()
    )

    # Cobertura semanal
    cobertura.update(
        chunk.groupby(
            ["ano", "semana"]
        ).size().to_dict()
    )

    print(f"Bloque {i} procesado")

# =================================
# RESUMEN DE EDADES POR TIPO
# =================================

resumen = []

for tipo, listas in edades_por_tipo.items():

    s = pd.concat(listas)

    resumen.append({
        "tipo_edad": tipo,
        "registros": len(s),
        "minimo": s.min(),
        "percentil_50": s.quantile(0.50),
        "percentil_90": s.quantile(0.90),
        "percentil_95": s.quantile(0.95),
        "percentil_99": s.quantile(0.99),
        "maximo": s.max()
    })

df_resumen = pd.DataFrame(resumen)

df_resumen.to_csv(
    SALIDA / "14_resumen_edad_por_tipo.csv",
    index=False,
    encoding="utf-8-sig"
)

# =================================
# REGISTROS EXTREMOS
# =================================

top_edad.to_csv(
    SALIDA / "15_registros_edad_extrema.csv",
    index=False,
    encoding="utf-8-sig"
)

# =================================
# SEMANA 53
# =================================

df_semana53 = pd.DataFrame([
    {"ano": int(ano), "registros": cantidad}
    for ano, cantidad in semana53.items()
])

df_semana53.to_csv(
    SALIDA / "16_semana53_por_anio.csv",
    index=False,
    encoding="utf-8-sig"
)

# =================================
# COBERTURA TEMPORAL
# =================================

df_cobertura = pd.DataFrame([
    {
        "ano": int(k[0]),
        "semana": int(k[1]),
        "registros": v
    }
    for k, v in cobertura.items()
])

df_cobertura.sort_values(
    ["ano", "semana"]
).to_csv(
    SALIDA / "17_cobertura_semanal.csv",
    index=False,
    encoding="utf-8-sig"
)

# =================================
# INFORME FINAL
# =================================

with open(
    SALIDA / "resumen_edad.txt",
    "w",
    encoding="utf-8"
) as f:

    f.write("TERCERA AUDITORIA - EDADES\n")
    f.write("=" * 45 + "\n\n")

    f.write("DISTRIBUCION POR TIPO DE EDAD:\n")
    f.write(df_resumen.to_string(index=False))

    f.write("\n\nSEMANA 53 POR ANIO:\n")
    f.write(df_semana53.to_string(index=False))

    f.write("\n\nPRIMEROS 20 REGISTROS DE EDAD EXTREMA:\n")
    f.write(top_edad.head(20).to_string(index=False))

print("\nAUDITORIA FINALIZADA")
print("\nDISTRIBUCION DE EDADES:")
print(df_resumen.to_string(index=False))

print("\nREGISTROS DE SEMANA 53:")
print(df_semana53.to_string(index=False))

print("\nArchivos guardados en:", SALIDA)
