from pathlib import Path
import pandas as pd
import re

ROOT = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

folders = [
    ROOT / "data/processed/clima_integrado",
    ROOT / "data/processed/clima/recuperado_13_distritos_fecha_corregida",
    ROOT / "data/raw/clima/era5_land",
    ROOT / "data/raw/clima/recuperado_13_distritos"
]

climate_pattern = re.compile(
    r"^(tmean|tmax|tmin|humr|ptot)(_|$)", re.I
)

lat_pattern = re.compile(
    r"(^|_)(lat|latitude|latitud)(_|$)", re.I
)

lon_pattern = re.compile(
    r"(^|_)(lon|lng|long|longitude|longitud)(_|$)", re.I
)

results = []
inventario = []

def inspect(path):
    try:
        encoding = "utf-8-sig"

        try:
            header = pd.read_csv(
                path, nrows=0, encoding=encoding
            )
        except UnicodeDecodeError:
            encoding = "latin1"
            header = pd.read_csv(
                path, nrows=0, encoding=encoding
            )

        cols = list(header.columns)

        climate = [
            c for c in cols
            if climate_pattern.search(c.lower())
        ]

        lat = [c for c in cols if lat_pattern.search(c.lower())]
        lon = [c for c in cols if lon_pattern.search(c.lower())]

        ids = [
            c for c in cols
            if c.lower() in ["ubigeo", "cod_ubigeo"]
        ]

        dates = [
            c for c in cols
            if c.lower() in [
                "fecha", "fecha_inicio", "fecha_fin", "date"
            ]
        ]

        selected = list(dict.fromkeys(
            ids + dates + climate + lat + lon
        ))

        if not selected:
            selected = cols

        rows = 0
        districts = set()
        valid = {c: 0 for c in climate}
        minimum = {c: None for c in climate}
        maximum = {c: None for c in climate}

        coord_min = {}
        coord_max = {}

        date_min = None
        date_max = None

        for chunk in pd.read_csv(
            path,
            usecols=selected,
            chunksize=100000,
            encoding=encoding
        ):
            rows += len(chunk)

            for c in ids:
                districts.update(
                    chunk[c].dropna().astype(str).unique()
                )

            for c in climate:
                values = pd.to_numeric(
                    chunk[c], errors="coerce"
                )

                valid[c] += int(values.notna().sum())

                if values.notna().any():
                    mn = float(values.min())
                    mx = float(values.max())

                    minimum[c] = (
                        mn if minimum[c] is None
                        else min(minimum[c], mn)
                    )
                    maximum[c] = (
                        mx if maximum[c] is None
                        else max(maximum[c], mx)
                    )

            for c in lat + lon:
                values = pd.to_numeric(
                    chunk[c], errors="coerce"
                ).dropna()

                if len(values):
                    coord_min[c] = min(
                        coord_min.get(c, float("inf")),
                        float(values.min())
                    )
                    coord_max[c] = max(
                        coord_max.get(c, float("-inf")),
                        float(values.max())
                    )

            for c in dates:
                values = chunk[c].dropna().astype(str)

                if len(values):
                    mn, mx = values.min(), values.max()
                    date_min = mn if date_min is None else min(date_min, mn)
                    date_max = mx if date_max is None else max(date_max, mx)

        completeness = "; ".join(
            f"{c}: {valid[c]/rows*100:.2f}%"
            for c in climate
        ) if rows else "Sin registros"

        results.append({
            "archivo": str(path.relative_to(ROOT)),
            "registros": rows,
            "ubigeos_unicos": len(districts),
            "variables_climaticas": ", ".join(climate),
            "disponibilidad_clima": completeness,
            "columnas_latitud": ", ".join(lat) or "NO",
            "columnas_longitud": ", ".join(lon) or "NO",
            "coordenadas": (
                "SI" if lat and lon else "NO"
            ),
            "rangos_coordenadas": str({
                c: (coord_min.get(c), coord_max.get(c))
                for c in lat + lon
            }),
            "fecha_minima": date_min,
            "fecha_maxima": date_max,
            "columnas": ", ".join(cols)
        })

        print(
            f"OK | {path.name} | "
            f"{rows:,} filas | "
            f"{len(districts)} UBIGEOs | "
            f"Coordenadas: {'SI' if lat and lon else 'NO'}"
        )

    except Exception as e:
        print(f"ERROR | {path} | {e}")

# Inspeccionar las fuentes climáticas
files = []

for folder in folders:
    if folder.exists():
        files.extend(folder.glob("*.csv"))

files = sorted(set(files))

print("\nARCHIVOS ENCONTRADOS:", len(files))

for path in files:
    inspect(path)

# Buscar posibles fuentes geográficas adicionales
geo_candidates = []

for folder in [ROOT / "data/raw", ROOT / "data/processed"]:
    if folder.exists():
        for f in folder.rglob("*"):
            if not f.is_file():
                continue

            name = f.name.lower()

            if (
                any(x in name for x in [
                    "coordenada", "coordenadas",
                    "geograf", "geojson",
                    "centroid", "ubigeo", "distrito"
                ])
                and f.suffix.lower() in [
                    ".csv", ".xlsx", ".parquet",
                    ".json", ".geojson", ".shp"
                ]
            ):
                geo_candidates.append(
                    str(f.relative_to(ROOT))
                )

# Exportar resultados
out = ROOT / "reports/powerbi"
out.mkdir(parents=True, exist_ok=True)

df = pd.DataFrame(results)

csv_path = out / "diagnostico_clima_coordenadas.csv"
txt_path = out / "diagnostico_clima_coordenadas.txt"

df.to_csv(csv_path, index=False, encoding="utf-8-sig")

with open(txt_path, "w", encoding="utf-8") as f:
    f.write("DIAGNOSTICO DE CLIMA Y COORDENADAS\n\n")
    f.write(df.to_string(index=False))
    f.write("\n\nPOSIBLES FUENTES GEOGRAFICAS\n")

    for item in geo_candidates:
        f.write(item + "\n")

print("\n======================================")
print("DIAGNOSTICO TERMINADO")
print("Archivos examinados:", len(files))
print("Reporte CSV:", csv_path)
print("Reporte TXT:", txt_path)
print("Fuentes geograficas:", len(geo_candidates))
print("======================================")
