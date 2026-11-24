from pathlib import Path
import sys
import pandas as pd
import geopandas as gpd

from sqlalchemy import text, String, NVARCHAR, Float

PROJECT = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")
SHAPE = PROJECT / "data" / "processed" / "geografia" / "distritos_peru" / "distritos_peru.shp"

sys.path.insert(0, str(PROJECT))
from scripts.dengue_common import get_sql_engine

print("=" * 65)
print("GENERACION DE COORDENADAS DISTRITALES DEL PERU")
print("=" * 65)

if not SHAPE.exists():
    raise FileNotFoundError(f"No se encontro: {SHAPE}")

# 1. Leer geometria distrital
print("\n1. LEYENDO SHAPEFILE...")

gdf = gpd.read_file(SHAPE)

if gdf.crs is None:
    raise ValueError("El shapefile no tiene sistema de coordenadas.")

ubigeo_col = next(
    (c for c in gdf.columns if c.lower() == "ubigeo"),
    None
)

if ubigeo_col is None:
    raise ValueError("No se encontro la columna UBIGEO.")

gdf = gdf[[ubigeo_col, "geometry"]].copy()
gdf = gdf.rename(columns={ubigeo_col: "ubigeo"})

gdf["ubigeo"] = (
    gdf["ubigeo"].astype(str).str.strip().str.zfill(6)
)

if gdf["ubigeo"].duplicated().any():
    raise ValueError("Hay UBIGEO duplicados en el shapefile.")

print("Distritos geograficos:", len(gdf))
print("CRS original:", gdf.crs)

# 2. Calcular puntos representativos
print("\n2. CALCULANDO COORDENADAS...")

# Proyeccion equivalente para trabajar con geometria
projected = gdf.to_crs("EPSG:6933")

# Punto dentro de cada poligono distrital
points = projected.geometry.representative_point()

# Regresar a coordenadas geograficas
points = gpd.GeoSeries(
    points,
    crs=projected.crs
).to_crs("EPSG:4326")

coords = pd.DataFrame({
    "ubigeo": gdf["ubigeo"].values,
    "latitud": points.y.values,
    "longitud": points.x.values
})

if coords[["latitud", "longitud"]].isna().any().any():
    raise ValueError("Hay coordenadas nulas.")

if not coords["latitud"].between(-19, 0).all():
    raise ValueError("Se encontraron latitudes fuera del Peru.")

if not coords["longitud"].between(-82, -68).all():
    raise ValueError("Se encontraron longitudes fuera del Peru.")

print("Coordenadas calculadas:", len(coords))

# 3. Conectar a SQL Server
print("\n3. CONECTANDO A SQL SERVER...")

engine = get_sql_engine()

try:
    # 4. Leer dimension existente
    print("\n4. LEYENDO DIMENSION DE DISTRITOS...")

    with engine.connect() as conn:
        dim = pd.read_sql(
            text("""
                SELECT
                    ubigeo,
                    departamento,
                    provincia,
                    distrito
                FROM dbo.dim_distrito
            """),
            conn
        )

    dim["ubigeo"] = (
        dim["ubigeo"].astype(str).str.strip().str.zfill(6)
    )

    if dim["ubigeo"].duplicated().any():
        raise ValueError("Hay UBIGEO duplicados en SQL.")

    # 5. Cruzar por UBIGEO
    print("\n5. CRUZANDO INFORMACION GEOGRAFICA...")

    result = dim.merge(
        coords,
        on="ubigeo",
        how="left",
        validate="one_to_one",
        indicator=True
    )

    faltantes = (result["_merge"] != "both").sum()

    if faltantes:
        raise ValueError(
            f"Hay {faltantes} distritos sin coordenadas."
        )

    result = result.drop(columns="_merge")

    print("Distritos relacionados:", len(result))
    print("UBIGEO coincidentes:", result["ubigeo"].nunique())

    # 6. Crear tabla auxiliar SQL
    print("\n6. GUARDANDO TABLA AUXILIAR...")

    result.to_sql(
        name="dim_distrito_geo",
        con=engine,
        schema="dbo",
        if_exists="replace",
        index=False,
        chunksize=300,
        dtype={
            "ubigeo": String(6),
            "departamento": NVARCHAR(100),
            "provincia": NVARCHAR(100),
            "distrito": NVARCHAR(150),
            "latitud": Float(),
            "longitud": Float()
        }
    )

    # 7. Validar resultado
    print("\n7. VALIDANDO TABLA SQL...")

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
                COUNT(*) AS registros,
                COUNT(DISTINCT ubigeo) AS ubigeos,
                COUNT(latitud) AS con_latitud,
                COUNT(longitud) AS con_longitud,
                MIN(latitud) AS lat_min,
                MAX(latitud) AS lat_max,
                MIN(longitud) AS lon_min,
                MAX(longitud) AS lon_max
            FROM dbo.dim_distrito_geo
        """)).mappings().one()

        print(dict(row))

        if (
            row["registros"] != 1891
            or row["ubigeos"] != 1891
            or row["con_latitud"] != 1891
            or row["con_longitud"] != 1891
        ):
            raise ValueError("La validacion final no fue satisfactoria.")

    print("\n" + "=" * 65)
    print("COORDENADAS DISTRITALES INTEGRADAS CORRECTAMENTE")
    print("Tabla: dbo.dim_distrito_geo")
    print("Distritos: 1891")
    print("Coordenadas: 100%")
    print("Tabla original dim_distrito: SIN MODIFICAR")
    print("=" * 65)

finally:
    engine.dispose()
