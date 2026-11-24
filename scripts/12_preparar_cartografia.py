from pathlib import Path
import geopandas as gpd
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ORIGEN = BASE / "data/raw/geografia/ign_2025/DISTRITOS.shp"

SALIDA = BASE / "data/processed/geografia/distritos_peru"

SALIDA.mkdir(parents=True, exist_ok=True)

print("LEYENDO CARTOGRAFIA IGN...")

gdf = gpd.read_file(ORIGEN)

# Normalizar UBIGEO como texto
ubigeo = (
    gdf["UBIGEO"]
    .astype("string")
    .str.strip()
    .str.replace(r"\.0$", "", regex=True)
    .str.replace(r"\D", "", regex=True)
    .str.zfill(6)
)

if not ubigeo.str.fullmatch(r"\d{6}").all():
    raise ValueError("Existen UBIGEO invalidos.")

if ubigeo.duplicated().any():
    raise ValueError("Existen UBIGEO duplicados.")

gdf["ubigeo"] = ubigeo.astype(str)

# Conservar solamente los campos necesarios
limpio = gdf[
    [
        "ubigeo",
        "DEPARTAMEN",
        "PROVINCIA",
        "DISTRITO",
        "geometry"
    ]
].copy()

limpio = limpio.rename(columns={
    "DEPARTAMEN": "departamento",
    "PROVINCIA": "provincia",
    "DISTRITO": "distrito"
})

# Asegurar EPSG:4326
limpio = limpio.to_crs("EPSG:4326")

if not limpio.geometry.is_valid.all():
    raise ValueError("Existen geometrías inválidas.")

archivo = SALIDA / "distritos_peru.shp"

limpio.to_file(
    archivo,
    driver="ESRI Shapefile",
    encoding="UTF-8"
)

# Verificar archivo generado
verificacion = gpd.read_file(archivo)

print("\nPREPARACION COMPLETADA")
print("Distritos:", len(verificacion))
print("UBIGEO unicos:", verificacion["ubigeo"].nunique())
print("Alto Trujillo:", (
    verificacion["ubigeo"].astype(str) == "130112"
).any())
print("CRS:", verificacion.crs)
print("Archivo:", archivo)
