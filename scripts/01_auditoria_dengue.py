from pathlib import Path
from collections import Counter
import pandas as pd

# ==========================================
# CONFIGURACION
# ==========================================

BASE = Path(
    r"C:\Users\xxter\Documents\Data_Dengue\Sistema"
)

CSV_PATH = (
    BASE / "data" / "raw" /
    "epidemiologia" / "data1.csv"
)

REPORT_PATH = (
    BASE / "reports" / "auditoria_dengue_resumen.txt"
)

print("=" * 55)
print("AUDITORIA DE DATOS EPIDEMIOLOGICOS - MINSA")
print("=" * 55)

if not CSV_PATH.exists():
    raise FileNotFoundError(
        f"No se encontro el archivo: {CSV_PATH}"
    )

print("\nArchivo encontrado:", CSV_PATH.name)
print(
    "Tamano:",
    round(CSV_PATH.stat().st_size / (1024**2), 2),
    "MB"
)

# ==========================================
# DETECTAR CODIFICACION
# ==========================================

encoding = None

for enc in ["utf-8-sig", "cp1252", "latin-1"]:
    try:
        pd.read_csv(
            CSV_PATH,
            nrows=5,
            encoding=enc
        )
        encoding = enc
        break
    except UnicodeDecodeError:
        continue

print("\nCodificacion:", encoding)

# ==========================================
# VARIABLES DE AUDITORIA
# ==========================================

total_registros = 0
anios = set()
departamentos = set()
ubigeos_validos = set()
ubigeos_invalidos = 0

frecuencias = {
    "tipo_dx": Counter(),
    "diagnostic": Counter(),
    "enfermedad": Counter()
}

nulos = pd.Series(dtype="int64")

# ==========================================
# PROCESAMIENTO POR BLOQUES
# ==========================================

print("\nProcesando CSV por bloques...")
print("No cierres la terminal mientras trabaja.\n")

for i, chunk in enumerate(
    pd.read_csv(
        CSV_PATH,
        chunksize=200_000,
        encoding=encoding,
        dtype={"ubigeo": "string"},
        low_memory=False
    ),
    start=1
):

    chunk.columns = (
        chunk.columns
        .str.strip()
        .str.lower()
    )

    total_registros += len(chunk)

    # Valores nulos
    nulos = nulos.add(
        chunk.isna().sum(),
        fill_value=0
    )

    # Años
    if "ano" in chunk.columns:
        valores = pd.to_numeric(
            chunk["ano"],
            errors="coerce"
        ).dropna()

        anios.update(
            valores.astype(int).unique()
        )

    # Departamentos
    if "departamento" in chunk.columns:
        departamentos.update(
            chunk["departamento"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
            .unique()
        )

    # UBIGEO
    if "ubigeo" in chunk.columns:
        ub = chunk["ubigeo"].astype("string").str.strip()

        valido = ub.str.fullmatch(
            r"\d{6}", na=False
        )

        ubigeos_validos.update(
            ub[valido].dropna().unique()
        )

        ubigeos_invalidos += int(
            (~valido).sum()
        )

    # Frecuencias de variables categoricas
    for columna in frecuencias:

        if columna in chunk.columns:

            valores = (
                chunk[columna]
                .fillna("SIN DATO")
                .astype(str)
                .str.strip()
            )

            frecuencias[columna].update(
                valores.value_counts().to_dict()
            )

    print(
        f"Bloque {i} procesado | "
        f"Registros acumulados: {total_registros:,}"
    )

# ==========================================
# GENERAR RESULTADOS
# ==========================================

print("\n" + "=" * 55)
print("RESULTADOS DE AUDITORIA")
print("=" * 55)

print(f"\nTotal de registros: {total_registros:,}")

print("\nAños disponibles:")
print(sorted(anios))

print("\nCantidad de departamentos:")
print(len(departamentos))

print("\nDepartamentos:")
print(sorted(departamentos))

print("\nUBIGEO validos diferentes:")
print(len(ubigeos_validos))

print("\nFilas con UBIGEO vacio o invalido:")
print(f"{ubigeos_invalidos:,}")

print("\nVALORES DE TIPO_DX:")
print(frecuencias["tipo_dx"].most_common(20))

print("\nVALORES DE DIAGNOSTIC:")
print(frecuencias["diagnostic"].most_common(20))

print("\nVALORES DE ENFERMEDAD:")
print(frecuencias["enfermedad"].most_common(20))

print("\nVALORES NULOS POR COLUMNA:")
print(nulos.sort_values(ascending=False))

# ==========================================
# GUARDAR INFORME
# ==========================================

lineas = [
    "AUDITORIA EPIDEMIOLOGICA MINSA",
    "=" * 50,
    f"Archivo: {CSV_PATH.name}",
    f"Registros: {total_registros:,}",
    f"Codificacion: {encoding}",
    f"Años: {sorted(anios)}",
    f"Departamentos: {len(departamentos)}",
    f"UBIGEO diferentes: {len(ubigeos_validos)}",
    f"Filas UBIGEO invalido: {ubigeos_invalidos:,}",
    "",
    "DEPARTAMENTOS:",
    str(sorted(departamentos)),
    "",
]

for columna, contador in frecuencias.items():
    lineas.extend([
        f"VALORES DE {columna.upper()}:",
        str(contador.most_common(30)),
        ""
    ])

lineas.extend([
    "VALORES NULOS:",
    nulos.sort_values(
        ascending=False
    ).to_string()
])

REPORT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

REPORT_PATH.write_text(
    "\n".join(lineas),
    encoding="utf-8"
)

print("\n" + "=" * 55)
print("AUDITORIA FINALIZADA")
print("Informe guardado en:")
print(REPORT_PATH)
print("=" * 55)
