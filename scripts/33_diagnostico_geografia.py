import sys
import re
import unicodedata
from pathlib import Path

import pandas as pd
import geopandas as gpd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.dengue_common import get_sql_engine

SOURCES = [
    (
        "IGN_2025",
        ROOT / "data" / "raw" / "geografia" /
        "ign_2025" / "DISTRITOS.shp"
    ),
    (
        "DISTRITOS_PROCESADOS",
        ROOT / "data" / "processed" / "geografia" /
        "distritos_peru" / "distritos_peru.shp"
    )
]

REPORT = ROOT / "reports" / "powerbi" / "33_diagnostico_geografia.txt"

ALIASES = {
    "ubigeo", "codubigeo", "idubigeo",
    "iddist", "coddist", "coddist",
    "iddistrito", "coddistrito",
    "codigodistrito", "ubigeodist"
}


def normalize_name(value):
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_code(value):
    if pd.isna(value):
        return None

    s = str(value).strip()

    if re.fullmatch(r"\d+(\.0+)?", s):
        s = s.split(".")[0]

        if len(s) <= 6:
            return s.zfill(6)

    return None


def inspect_source(name, path, sql_codes):

    print("\n" + "=" * 65)
    print("FUENTE:", name)
    print("=" * 65)

    if not path.exists():
        print("ARCHIVO NO ENCONTRADO:", path)
        return [
            f"\n{name}: ARCHIVO NO ENCONTRADO\n"
        ]

    gdf = gpd.read_file(path)

    lines = []

    def out(message):
        print(message)
        lines.append(str(message))

    out(f"Ruta: {path}")
    out(f"Registros geograficos: {len(gdf):,}")
    out(f"CRS original: {gdf.crs}")
    out(f"Columnas: {list(gdf.columns)}")

    # Geometrias
    geom = gdf.geometry

    out("\nTIPOS DE GEOMETRIA:")
    out(str(geom.geom_type.value_counts().to_dict()))

    out(f"Geometrias vacias: {int(geom.is_empty.sum())}")
    out(f"Geometrias invalidas: {int((~geom.is_valid).sum())}")

    # Coordenadas
    if gdf.crs is not None:

        geographic = gdf.to_crs(epsg=4326)

        out("\nLIMITES EN EPSG:4326:")
        out(str(geographic.total_bounds.tolist()))

        out("Orden: longitud minima, latitud minima, "
            "longitud maxima, latitud maxima")

    else:
        out("\nADVERTENCIA: LA FUENTE NO TIENE CRS DEFINIDO.")

    # Campos candidatos
    out("\nCAMPOS CANDIDATOS A UBIGEO:")

    candidates = []

    for column in gdf.columns:

        if column == gdf.geometry.name:
            continue

        series = gdf[column].dropna()

        if series.empty:
            continue

        normalized_name = normalize_name(column)

        codes = [
            normalize_code(value)
            for value in series
        ]

        valid = [value for value in codes if value is not None]

        ratio = len(valid) / len(series)

        if (
            normalized_name in ALIASES
            or (ratio >= 0.95 and len(set(valid)) >= 100)
        ):

            unique_codes = set(valid)
            matched = unique_codes & sql_codes
            missing = sql_codes - unique_codes
            extra = unique_codes - sql_codes

            result = (
                f"\nCampo: {column}\n"
                f"Nombre normalizado: {normalized_name}\n"
                f"Valores validos: {len(valid):,}\n"
                f"UBIGEOs unicos: {len(unique_codes):,}\n"
                f"Coinciden con SQL: {len(matched):,}\n"
                f"Faltan respecto a SQL: {len(missing):,}\n"
                f"Codigos adicionales: {len(extra):,}\n"
                f"Muestra: {list(unique_codes)[:10]}\n"
            )

            out(result)

            candidates.append({
                "campo": column,
                "coinciden": len(matched),
                "faltan": len(missing),
                "adicionales": len(extra)
            })

    if not candidates:
        out("No se identifico un campo UBIGEO directo.")

    # Campos territoriales
    out("\nCAMPOS TERRITORIALES POSIBLES:")

    for column in gdf.columns:
        normalized = normalize_name(column)

        if any(
            word in normalized
            for word in [
                "dep", "dpto", "prov", "dist",
                "ubigeo", "codigo", "ccdd", "ccpp", "ccdi"
            ]
        ):
            out(
                f"{column}: "
                f"{gdf[column].head(5).tolist()}"
            )

    # Muestra de atributos
    out("\nMUESTRA DE ATRIBUTOS:")

    sample = gdf.drop(columns=[gdf.geometry.name]).head(5)

    out(sample.to_string(index=False))

    return lines


def main():

    print("=" * 65)
    print("DIAGNOSTICO DE GEOGRAFIA DISTRITAL DEL PERU")
    print("=" * 65)

    engine = get_sql_engine()

    try:
        with engine.connect() as conn:

            sql_codes = set(
                conn.execute(text("""
                    SELECT LTRIM(RTRIM(ubigeo))
                    FROM dbo.dim_distrito
                """)).scalars().all()
            )

        print(f"\nUBIGEOS EN SQL SERVER: {len(sql_codes):,}")

        all_lines = []

        for name, path in SOURCES:

            try:
                all_lines.extend(
                    inspect_source(name, path, sql_codes)
                )

            except Exception as error:
                message = f"ERROR EN {name}: {error}"
                print(message)
                all_lines.append(message)

        REPORT.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        REPORT.write_text(
            "\n".join(all_lines),
            encoding="utf-8"
        )

        print("\n" + "=" * 65)
        print("DIAGNOSTICO TERMINADO")
        print("Reporte:", REPORT)
        print("=" * 65)

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()