import sys
import re
from pathlib import Path

import pandas as pd
import geopandas as gpd

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dengue_common import get_sql_engine

SHP = (
    ROOT / "data" / "raw" / "geografia" /
    "ign_2025" / "DISTRITOS.shp"
)

REPORT_DIR = ROOT / "reports" / "powerbi"

CSV_OUTPUT = REPORT_DIR / "34_coordenadas_distritos_ign.csv"
BACKUP_OUTPUT = REPORT_DIR / "34_coordenadas_anteriores.csv"


def normalize_code(value):

    if pd.isna(value):
        return None

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if not value.isdigit():
        return None

    return value.zfill(6)


def main():

    print("=" * 65)
    print("INTEGRACION DE COORDENADAS DISTRITALES IGN 2025")
    print("=" * 65)

    if not SHP.exists():
        raise FileNotFoundError(f"No existe: {SHP}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------
    # 1. LEER ARCHIVO GEOGRAFICO
    # -------------------------------------------------

    print("\n1. LEYENDO POLIGONOS IGN...")

    gdf = gpd.read_file(SHP)

    if "UBIGEO" not in gdf.columns:
        raise ValueError("No se encontro el campo UBIGEO.")

    if gdf.crs is None:
        raise ValueError("El archivo no tiene CRS definido.")

    if gdf.geometry.isna().any():
        raise ValueError("Existen geometrías nulas.")

    if gdf.geometry.is_empty.any():
        raise ValueError("Existen geometrías vacías.")

    if (~gdf.geometry.is_valid).any():
        raise ValueError("Existen geometrías inválidas.")

    gdf["ubigeo"] = gdf["UBIGEO"].map(normalize_code)

    if gdf["ubigeo"].isna().any():
        raise ValueError("Hay UBIGEO inválidos.")

    if gdf["ubigeo"].duplicated().any():
        raise ValueError("Hay UBIGEO duplicados.")

    print("Distritos geograficos:", len(gdf))
    print("CRS original:", gdf.crs)

    # Convertir a coordenadas geograficas
    gdf = gdf.to_crs(epsg=4326)

    # -------------------------------------------------
    # 2. GENERAR PUNTOS DENTRO DE CADA DISTRITO
    # -------------------------------------------------

    print("\n2. GENERANDO PUNTOS REPRESENTATIVOS...")

    points = gdf.geometry.representative_point()

    inside = [
        geometry.covers(point)
        for geometry, point in zip(gdf.geometry, points)
    ]

    if not all(inside):
        raise ValueError(
            "Hay puntos que no estan dentro de sus poligonos."
        )

    coords = pd.DataFrame({
        "ubigeo": gdf["ubigeo"].values,
        "longitud": points.x.values,
        "latitud": points.y.values
    })

    # Comprobacion geografica general del Peru
    valid_bounds = (
        coords["longitud"].between(-82, -68)
        & coords["latitud"].between(-19, 1)
    )

    if not valid_bounds.all():
        raise ValueError(
            "Hay coordenadas fuera de los limites geograficos esperados."
        )

    if len(coords) != 1891:
        raise ValueError(
            f"Se esperaban 1891 distritos, encontrados: {len(coords)}"
        )

    print("Puntos generados:", len(coords))
    print("Puntos dentro de sus poligonos:", sum(inside))
    print("Latitud minima:", round(coords.latitud.min(), 7))
    print("Latitud maxima:", round(coords.latitud.max(), 7))
    print("Longitud minima:", round(coords.longitud.min(), 7))
    print("Longitud maxima:", round(coords.longitud.max(), 7))

    # Guardar CSV de coordenadas
    coords.to_csv(
        CSV_OUTPUT,
        index=False,
        encoding="utf-8-sig"
    )

    print("CSV generado:", CSV_OUTPUT)

    # -------------------------------------------------
    # 3. CONECTAR A SQL SERVER
    # -------------------------------------------------

    print("\n3. CONECTANDO A SQL SERVER...")

    engine = get_sql_engine()

    try:

        with engine.connect() as conn:

            sql_codes = {
                normalize_code(value)
                for value in conn.execute(text("""
                    SELECT ubigeo
                    FROM dbo.dim_distrito
                """)).scalars().all()
            }

            sql_codes.discard(None)

            columns = {
                row[0].lower()
                for row in conn.execute(text("""
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'dbo'
                      AND TABLE_NAME = 'dim_distrito'
                """)).all()
            }

            print("Distritos SQL:", len(sql_codes))

            # Respaldar coordenadas anteriores si existen
            if {"latitud", "longitud"}.issubset(columns):

                old = conn.execute(text("""
                    SELECT ubigeo, latitud, longitud
                    FROM dbo.dim_distrito
                """)).mappings().all()

                if old:
                    pd.DataFrame(
                        [dict(row) for row in old]
                    ).to_csv(
                        BACKUP_OUTPUT,
                        index=False,
                        encoding="utf-8-sig"
                    )

                    print("Respaldo anterior:", BACKUP_OUTPUT)

        geo_codes = set(coords["ubigeo"])

        missing = sql_codes - geo_codes
        extra = geo_codes - sql_codes

        print("UBIGEO coincidentes:", len(sql_codes & geo_codes))
        print("Faltantes:", len(missing))
        print("Adicionales:", len(extra))

        if missing or extra or len(sql_codes) != 1891:
            raise ValueError(
                "Los UBIGEO no coinciden. No se modificara SQL."
            )

        # -------------------------------------------------
        # 4. AGREGAR COLUMNAS Y ACTUALIZAR COORDENADAS
        # -------------------------------------------------

        print("\n4. ACTUALIZANDO DIM_DISTRITO...")

        records = coords.to_dict("records")

        with engine.begin() as conn:

            current_columns = {
                row[0].lower()
                for row in conn.execute(text("""
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = 'dbo'
                      AND TABLE_NAME = 'dim_distrito'
                """)).all()
            }

            if "latitud" not in current_columns:
                conn.execute(text("""
                    ALTER TABLE dbo.dim_distrito
                    ADD latitud DECIMAL(10,7) NULL
                """))

                print("Columna latitud creada.")

            if "longitud" not in current_columns:
                conn.execute(text("""
                    ALTER TABLE dbo.dim_distrito
                    ADD longitud DECIMAL(10,7) NULL
                """))

                print("Columna longitud creada.")

            update_sql = text("""
                UPDATE dbo.dim_distrito
                SET latitud = :latitud,
                    longitud = :longitud
                WHERE ubigeo = :ubigeo
            """)

            conn.execute(update_sql, records)

            # -------------------------------------------------
            # 5. VERIFICAR RESULTADO
            # -------------------------------------------------

            print("\n5. VERIFICANDO RESULTADOS...")

            result = conn.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(latitud) AS con_latitud,
                    COUNT(longitud) AS con_longitud,
                    COUNT(DISTINCT ubigeo) AS ubigeos,
                    MIN(latitud) AS latitud_minima,
                    MAX(latitud) AS latitud_maxima,
                    MIN(longitud) AS longitud_minima,
                    MAX(longitud) AS longitud_maxima
                FROM dbo.dim_distrito
            """)).mappings().one()

            print(dict(result))

            if (
                result["total"] != 1891
                or result["con_latitud"] != 1891
                or result["con_longitud"] != 1891
                or result["ubigeos"] != 1891
            ):
                raise ValueError(
                    "La verificacion SQL no fue satisfactoria."
                )

        print("\n" + "=" * 65)
        print("INTEGRACION GEOGRAFICA COMPLETADA")
        print("=" * 65)

        print("Distritos actualizados: 1,891")
        print("Latitud: 100%")
        print("Longitud: 100%")
        print("Correspondencia UBIGEO: 100%")
        print("Puntos dentro de sus poligonos: 100%")
        print("Transaccion SQL: CONFIRMADA")

        print("\nCSV:", CSV_OUTPUT)

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()