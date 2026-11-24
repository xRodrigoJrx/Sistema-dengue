from pathlib import Path
import pandas as pd
import geopandas as gpd
import re

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

SHP = BASE / "data/raw/geografia/ign_2025/DISTRITOS.shp"
CLIMA = BASE / "data/raw/clima"
MINSA = BASE / "data/raw/epidemiologia/data1.csv"

SALIDA = BASE / "reports/auditoria_geografia_ign"
SALIDA.mkdir(parents=True, exist_ok=True)

informe = []

def normalizar_ubigeo(serie):
    s = serie.astype("string").str.strip()
    s = s.str.replace(r"\.0$", "", regex=True)
    s = s.str.replace(r"\D", "", regex=True)
    s = s.mask(s.eq(""))
    s = s.where(s.str.len() <= 6)
    return s.str.zfill(6)

# ==========================================
# 1. LEER SHAPEFILE
# ==========================================

print("LEYENDO CARTOGRAFIA IGN...")

if not SHP.exists():
    raise FileNotFoundError(f"No se encuentra: {SHP}")

gdf = gpd.read_file(SHP)

informe.append("AUDITORIA CARTOGRAFICA IGN")
informe.append("=" * 60)

informe.append(f"Archivo: {SHP.name}")
informe.append(f"Registros: {len(gdf):,}")
informe.append(f"Columnas: {list(gdf.columns)}")
informe.append(f"Sistema de coordenadas: {gdf.crs}")

informe.append(
    f"Tipos de geometria: {gdf.geometry.geom_type.value_counts().to_dict()}"
)

informe.append(
    f"Geometrias nulas: {int(gdf.geometry.isna().sum())}"
)

informe.append(
    f"Geometrias vacias: {int(gdf.geometry.is_empty.sum())}"
)

informe.append(
    f"Geometrias invalidas: {int((gdf.geometry.notna() & ~gdf.geometry.is_valid).sum())}"
)

informe.append(
    f"Limites geograficos: {gdf.total_bounds.tolist()}"
)

# ==========================================
# 2. IDENTIFICAR COLUMNA UBIGEO
# ==========================================

columnas = list(gdf.columns)

candidatas = [
    c for c in columnas
    if re.sub(r"[^a-z0-9]", "", c.lower()) in [
        "ubigeo",
        "codubigeo",
        "codigoubigeo"
    ]
]

if not candidatas:
    candidatas = [
        c for c in columnas
        if "ubigeo" in c.lower()
    ]

if not candidatas:

    informe.append("\nNO SE IDENTIFICO UNA COLUMNA UBIGEO.")
    informe.append("Revisar las columnas manualmente.")

    (SALIDA / "50_resumen_ign.txt").write_text(
        "\n".join(informe),
        encoding="utf-8"
    )

    print("\n".join(informe))
    raise SystemExit

UBIGEO = candidatas[0]

informe.append(f"\nColumna UBIGEO identificada: {UBIGEO}")

gdf["_ubigeo"] = normalizar_ubigeo(
    gdf[UBIGEO]
)

codigos_geo = set(
    gdf["_ubigeo"].dropna().tolist()
)

informe.append(
    f"UBIGEO diferentes: {len(codigos_geo):,}"
)

informe.append(
    f"Registros sin UBIGEO: {int(gdf['_ubigeo'].isna().sum())}"
)

informe.append(
    f"UBIGEO duplicados: {int(gdf['_ubigeo'].duplicated().sum())}"
)

# ==========================================
# 3. COMPROBAR ALTO TRUJILLO
# ==========================================

informe.append("\nREVISION DE ALTO TRUJILLO")
informe.append("-" * 40)

alto = gdf[gdf["_ubigeo"] == "130112"]

informe.append(
    f"UBIGEO 130112 encontrado: {len(alto) > 0}"
)

if not alto.empty:

    atributos = alto.drop(
        columns=[gdf.geometry.name],
        errors="ignore"
    )

    informe.append(
        atributos.to_string(index=False)
    )

    atributos.to_csv(
        SALIDA / "51_alto_trujillo.csv",
        index=False,
        encoding="utf-8-sig"
    )

else:

    informe.append(
        "ALTO TRUJILLO NO APARECE EN ESTA CARTOGRAFIA."
    )

# ==========================================
# 4. COMPARAR CLIMA
# ==========================================

print("\nCOMPARANDO CON CLIMA...")

archivos_clima = sorted([
    f for f in CLIMA.rglob("*.xlsx")
    if not f.name.startswith("~$")
])

if not archivos_clima:
    raise FileNotFoundError("No se encontraron Excel climaticos")

df_clima = pd.read_excel(
    archivos_clima[0],
    sheet_name="distrito"
)

df_clima.columns = (
    df_clima.columns.astype(str)
    .str.strip()
    .str.lower()
)

codigos_clima = set(
    normalizar_ubigeo(
        df_clima["ubigeo"]
    ).dropna().tolist()
)

# ==========================================
# 5. COMPARAR MINSA
# ==========================================

print("\nCOMPARANDO CON MINSA...")

codigos_minsa = set()

for i, chunk in enumerate(pd.read_csv(
    MINSA,
    usecols=["ubigeo"],
    dtype="string",
    encoding="utf-8-sig",
    chunksize=200000
), start=1):

    codigos_minsa.update(
        normalizar_ubigeo(
            chunk["ubigeo"]
        ).dropna().tolist()
    )

    print(f"Bloque MINSA {i} procesado")

# ==========================================
# 6. DIFERENCIAS ENTRE FUENTES
# ==========================================

comparaciones = [
    ("IGN_NO_CLIMA", codigos_geo - codigos_clima),
    ("CLIMA_NO_IGN", codigos_clima - codigos_geo),
    ("MINSA_NO_IGN", codigos_minsa - codigos_geo),
    ("MINSA_NO_CLIMA", codigos_minsa - codigos_clima)
]

diferencias = []

informe.append("\nCOMPARACION DE FUENTES")
informe.append("=" * 50)

for nombre, conjunto in comparaciones:

    informe.append(
        f"{nombre}: {len(conjunto):,}"
    )

    for codigo in sorted(conjunto):

        diferencias.append({
            "comparacion": nombre,
            "ubigeo": codigo
        })

pd.DataFrame(
    diferencias,
    columns=["comparacion", "ubigeo"]
).to_csv(
    SALIDA / "52_diferencias_ubigeo_ign.csv",
    index=False,
    encoding="utf-8-sig"
)

# ==========================================
# 7. EXPORTAR INVENTARIO UBIGEO
# ==========================================

gdf.drop(
    columns=[gdf.geometry.name],
    errors="ignore"
).to_csv(
    SALIDA / "53_inventario_distritos_ign.csv",
    index=False,
    encoding="utf-8-sig"
)

informe.append("\nRESUMEN FINAL")
informe.append("=" * 50)
informe.append(f"Registros IGN: {len(gdf):,}")
informe.append(f"UBIGEO IGN: {len(codigos_geo):,}")
informe.append(f"UBIGEO clima: {len(codigos_clima):,}")
informe.append(f"UBIGEO MINSA: {len(codigos_minsa):,}")

(SALIDA / "50_resumen_ign.txt").write_text(
    "\n".join(informe),
    encoding="utf-8"
)

print("\n" + "=" * 55)
print("AUDITORIA IGN COMPLETADA")
print("=" * 55)
print("\n".join(informe))
print("\nResultados guardados en:")
print(SALIDA)
