from pathlib import Path
from collections import Counter
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

CLIMA = BASE / "data/raw/clima"
MINSA = BASE / "data/raw/epidemiologia/data1.csv"
POBLACION = BASE / "data/raw/poblacion"

SALIDA = BASE / "reports/revision_final_fuentes"
SALIDA.mkdir(parents=True, exist_ok=True)

informe = []

# ==========================================
# 1. DUPLICADOS CLIMATICOS
# ==========================================

archivos = sorted([
    f for f in CLIMA.rglob("*.xlsx")
    if not f.name.startswith("~$")
])

if not archivos:
    raise FileNotFoundError("No hay archivos climaticos")

archivo = archivos[0]

df = pd.read_excel(
    archivo,
    sheet_name="distrito"
)

df.columns = (
    df.columns.astype(str).str.strip().str.lower()
)

df["ubigeo"] = (
    df["ubigeo"].astype("string")
    .str.strip()
    .str.replace(r"\.0$", "", regex=True)
    .str.zfill(6)
)

claves = ["ubigeo", "ano", "semana"]

variables = [
    c for c in ["tmean", "tmax", "tmin", "humr", "ptot", "n_dias"]
    if c in df.columns
]

frecuencias = df.groupby(
    claves, dropna=False
).size()

repetidas = frecuencias[frecuencias > 1]

filas = df[
    df.duplicated(subset=claves, keep=False)
].copy()

# Comparar los valores climaticos de cada par
filas["_firma_clima"] = (
    filas[variables]
    .astype("string")
    .fillna("<NULO>")
    .agg("|".join, axis=1)
)

firmas = filas.groupby(
    claves, dropna=False
)["_firma_clima"].nunique()

iguales = int((firmas == 1).sum())
diferentes = int((firmas > 1).sum())

distribucion = (
    repetidas.value_counts()
    .sort_index()
    .to_dict()
)

informe.append("REVISION DE DUPLICADOS CLIMATICOS")
informe.append("=" * 55)
informe.append(f"Archivo: {archivo.name}")
informe.append(f"Registros: {len(df):,}")
informe.append(f"Grupos repetidos: {len(repetidas):,}")
informe.append(f"Filas repetidas: {len(filas):,}")
informe.append(f"Distribucion de frecuencia: {distribucion}")
informe.append(f"Grupos con valores climaticos iguales: {iguales:,}")
informe.append(f"Grupos con valores climaticos diferentes: {diferentes:,}")
informe.append(f"Anios: {sorted(df['ano'].dropna().unique().tolist())}")
informe.append(f"Semanas: {sorted(df['semana'].dropna().unique().tolist())}")

# Guardar registros de ejemplo
columnas_muestra = claves + variables

muestra = filas[
    filas["ubigeo"].isin(["150102", "130112"])
][columnas_muestra]

muestra.to_csv(
    SALIDA / "45_ejemplos_duplicados_clima.csv",
    index=False,
    encoding="utf-8-sig"
)

# Guardar distribucion de frecuencias
pd.DataFrame(
    list(distribucion.items()),
    columns=["frecuencia", "grupos"]
).to_csv(
    SALIDA / "46_frecuencia_clima.csv",
    index=False,
    encoding="utf-8-sig"
)

# ==========================================
# 2. DEPARTAMENTOS EN CADA ARCHIVO
# ==========================================

informe.append("\n\nHOJAS DEPARTAMENTO")
informe.append("=" * 55)

departamentos = []

for f in archivos:

    hoja = pd.read_excel(
        f,
        sheet_name="departamento"
    )

    hoja.columns = (
        hoja.columns.astype(str).str.strip().str.lower()
    )

    valores = sorted(
        hoja["departamento"]
        .dropna().astype(str).unique().tolist()
    )

    departamentos.append({
        "archivo": f.name,
        "registros": len(hoja),
        "departamentos": ", ".join(valores)
    })

    informe.append(
        f"{f.name}: {len(hoja)} registros | {valores}"
    )

pd.DataFrame(departamentos).to_csv(
    SALIDA / "47_departamentos_clima.csv",
    index=False,
    encoding="utf-8-sig"
)

# ==========================================
# 3. MINSA: UBIGEO 130112
# ==========================================

informe.append("\n\nMINSA - UBIGEO 130112")
informe.append("=" * 55)

conteo_anual = Counter()
distritos = Counter()
provincias = Counter()
total_130112 = 0

for chunk in pd.read_csv(
    MINSA,
    usecols=[
        "ubigeo", "ano", "semana",
        "departamento", "provincia", "distrito"
    ],
    dtype="string",
    encoding="utf-8-sig",
    chunksize=200000
):

    ubigeo = (
        chunk["ubigeo"].str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    seleccion = chunk[ubigeo == "130112"].copy()

    if not seleccion.empty:

        total_130112 += len(seleccion)

        conteo_anual.update(
            seleccion["ano"].value_counts().to_dict()
        )

        distritos.update(
            seleccion["distrito"].value_counts().to_dict()
        )

        provincias.update(
            seleccion["provincia"].value_counts().to_dict()
        )

informe.append(f"Total de registros: {total_130112:,}")
informe.append(f"Registros por ano: {dict(sorted(conteo_anual.items()))}")
informe.append(f"Distritos registrados: {dict(distritos)}")
informe.append(f"Provincias registradas: {dict(provincias)}")

pd.DataFrame(
    [
        {"ano": k, "registros": v}
        for k, v in sorted(conteo_anual.items())
    ]
).to_csv(
    SALIDA / "48_minsa_alto_trujillo.csv",
    index=False,
    encoding="utf-8-sig"
)

# ==========================================
# 4. POBLACION: ESTRUCTURA ORIGINAL
# ==========================================

informe.append("\n\nESTRUCTURA DE POBLACION")
informe.append("=" * 55)

poblacion_files = list(
    POBLACION.rglob("Limpia.xlsx")
)

if poblacion_files:

    libro = pd.ExcelFile(poblacion_files[0])

    informe.append(
        f"Archivo: {poblacion_files[0].name}"
    )

    informe.append(
        f"Hojas: {libro.sheet_names}"
    )

    vista = pd.read_excel(
        poblacion_files[0],
        sheet_name=libro.sheet_names[0],
        header=None,
        nrows=15
    )

    lineas = []

    for i, fila in vista.iterrows():

        valores = [
            "" if pd.isna(x) else str(x)
            for x in fila.tolist()
        ]

        lineas.append(
            f"FILA EXCEL {i+1}: {' | '.join(valores)}"
        )

    (SALIDA / "49_estructura_poblacion.txt").write_text(
        "\n".join(lineas),
        encoding="utf-8"
    )

else:

    informe.append("No se encontro Limpia.xlsx")

# ==========================================
# 5. GUARDAR INFORME
# ==========================================

(SALIDA / "resumen_revision.txt").write_text(
    "\n".join(informe),
    encoding="utf-8"
)

print("\n" + "=" * 55)
print("DECIMA AUDITORIA COMPLETADA")
print("=" * 55)
print("\n".join(informe))
print("\nResultados:", SALIDA)
