from pathlib import Path
import pandas as pd
import re
from sqlalchemy import text
from dengue_common import get_sql_engine

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "processed" / "modelamiento" / "dataset_modelamiento_dengue_2000_2025.csv.gz"

salida = []

def mostrar(titulo, contenido):
    texto = f"\n{'='*65}\n{titulo}\n{'='*65}\n{contenido}"
    print(texto)
    salida.append(texto)

print("\nDIAGNOSTICO DE FUENTES Y POWER BI DENGUE")

# 1. Dataset maestro
if DATASET.exists():
    encabezado = pd.read_csv(DATASET, compression="infer", nrows=0)
    columnas = list(encabezado.columns)

    mostrar("COLUMNAS DEL DATASET MAESTRO", "\n".join(columnas))

    tokens = [
        "tmean", "tmax", "tmin", "humr", "ptot",
        "temp", "humedad", "precip", "clima",
        "weather", "rain"
    ]

    columnas_clima = [
        c for c in columnas
        if any(t in c.lower() for t in tokens)
    ]

    if columnas_clima:
        conteos = {c: 0 for c in columnas_clima}
        filas = 0

        for chunk in pd.read_csv(
            DATASET,
            compression="infer",
            usecols=columnas_clima,
            chunksize=200000
        ):
            filas += len(chunk)
            for c in columnas_clima:
                conteos[c] += int(chunk[c].notna().sum())

        resultado = pd.DataFrame({
            "variable": list(conteos.keys()),
            "valores_disponibles": list(conteos.values())
        })

        resultado["porcentaje_disponible"] = (
            resultado["valores_disponibles"] / filas * 100
        ).round(3)

        mostrar("DISPONIBILIDAD CLIMATICA EN DATASET MAESTRO",
                resultado.to_string(index=False))
    else:
        mostrar("DISPONIBILIDAD CLIMATICA",
                "No se encontraron columnas climáticas.")
else:
    mostrar("DATASET MAESTRO", f"No encontrado: {DATASET}")

# 2. Buscar archivos climáticos originales
data_dir = ROOT / "data"
candidatos = []
tokens_archivo = [
    "clima", "clim", "weather", "era5",
    "temperature", "temperatura", "precip",
    "humedad", "meteor", "power"
]

if data_dir.exists():
    for f in data_dir.rglob("*"):
        if not f.is_file():
            continue

        nombre = f.name.lower()
        extension_valida = (
            nombre.endswith((".csv", ".csv.gz", ".parquet",
                             ".xlsx", ".xls"))
        )

        if not extension_valida:
            continue

        if any(t in nombre for t in tokens_archivo):
            candidatos.append(
                f"{f.relative_to(ROOT)} | {f.stat().st_size:,} bytes"
            )
            continue

        # Inspeccionar encabezados de archivos CSV
        if nombre.endswith((".csv", ".csv.gz")):
            try:
                cols = pd.read_csv(
                    f, compression="infer", nrows=0
                ).columns

                hits = [
                    c for c in cols
                    if any(t in c.lower() for t in tokens_archivo)
                ]

                if hits:
                    candidatos.append(
                        f"{f.relative_to(ROOT)} | Columnas: {hits}"
                    )
            except Exception:
                pass

mostrar("ARCHIVOS FUENTE POTENCIALMENTE CLIMATICOS",
        "\n".join(candidatos[:100]) if candidatos
        else "No se encontraron archivos candidatos.")

# 3. SQL Server
engine = get_sql_engine()

consultas = {
    "DISTRITO CON DEPARTAMENTO VACIO": """
        SELECT ubigeo, departamento, provincia, distrito
        FROM dbo.dim_distrito
        WHERE departamento IS NULL
           OR LTRIM(RTRIM(departamento)) = '';
    """,

    "FECHAS DEL HISTORICO": """
        SELECT MIN(fecha_inicio) AS fecha_minima,
               MAX(fecha_inicio) AS fecha_maxima,
               MIN(fecha_fin) AS fecha_fin_minima,
               MAX(fecha_fin) AS fecha_fin_maxima
        FROM dbo.fact_semanal_dengue;
    """,

    "DISTRIBUCION DE DEPARTAMENTOS": """
        SELECT departamento, COUNT(*) AS distritos
        FROM dbo.dim_distrito
        GROUP BY departamento
        ORDER BY departamento;
    """
}

try:
    with engine.connect() as conn:
        for nombre, sql in consultas.items():
            df = pd.read_sql_query(text(sql), conn)
            mostrar(nombre, df.to_string(index=False))

finally:
    engine.dispose()

# 4. Medidas DAX y relaciones del modelo PBIP
model_dir = (
    ROOT / "powerbi" / "Dengue_Analytics" /
    "Dengue_Analytics.SemanticModel" / "definition"
)

tables_dir = model_dir / "tables"

if tables_dir.exists():
    palabras = [
        "variacion", "variación", "temperatura",
        "precipitacion", "precipitación",
        "casos reportados", "registro minsa",
        "dateadd", "sameperiodlastyear"
    ]

    for archivo in sorted(tables_dir.glob("*.tmdl")):
        try:
            lineas = archivo.read_text(
                encoding="utf-8-sig"
            ).splitlines()

            hallazgos = []
            for i, linea in enumerate(lineas):
                if any(p in linea.lower() for p in palabras):
                    inicio = max(0, i - 2)
                    fin = min(len(lineas), i + 5)

                    bloque = "\n".join(
                        f"{j+1}: {lineas[j]}"
                        for j in range(inicio, fin)
                    )

                    if bloque not in hallazgos:
                        hallazgos.append(bloque)

            if hallazgos:
                mostrar(
                    f"MODELO DAX: {archivo.name}",
                    "\n\n".join(hallazgos[:15])
                )

        except Exception as e:
            print("No se pudo leer:", archivo.name, e)

# 5. Relaciones
relaciones = model_dir / "relationships.tmdl"

if relaciones.exists():
    mostrar(
        "RELACIONES DEL MODELO",
        relaciones.read_text(encoding="utf-8-sig")
    )

# Guardar informe
destino = ROOT / "reports" / "powerbi"
destino.mkdir(parents=True, exist_ok=True)

reporte = destino / "diagnostico_fuentes_dashboard.txt"
reporte.write_text("\n".join(salida), encoding="utf-8")

print("\n========================================")
print("INSPECCION COMPLETADA")
print("Reporte:", reporte)
print("No se modificaron datos ni medidas.")
print("========================================")
