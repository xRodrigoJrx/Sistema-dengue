from pathlib import Path
import pandas as pd
import sqlite3
import hashlib

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

CLIMA = BASE / "data/raw/clima"
MINSA = BASE / "data/raw/epidemiologia/data1.csv"
POBLACION = BASE / "data/raw/poblacion"
GEOGRAFIA = BASE / "data/raw/geografia"

SALIDA = BASE / "reports/validacion_integracion"
SALIDA.mkdir(parents=True, exist_ok=True)


# ==========================================
# FUNCIONES
# ==========================================

def normalizar_ubigeo(serie):

    valores = pd.to_numeric(
        serie.astype("string").str.strip(),
        errors="coerce"
    )

    return (
        valores.astype("Int64")
        .astype("string")
        .str.zfill(6)
    )


def huella(df):

    # Convertir valores a texto y normalizar nulos
    temp = df.astype("string").fillna("<NULO>")

    # Generar hashes de las filas
    valores = pd.util.hash_pandas_object(
        temp,
        index=False
    ).tolist()

    # Ordenamiento mediante lista Python.
    # No utiliza arrays NumPy de solo lectura.
    valores.sort()

    h = hashlib.sha256()

    # Incluir los nombres de las columnas
    h.update(
        "|".join(temp.columns).encode("utf-8")
    )

    # Incorporar cada huella en orden
    for valor in valores:
        h.update(
            int(valor).to_bytes(
                8,
                byteorder="little",
                signed=False
            )
        )

    return h.hexdigest()


def guardar_txt(nombre, contenido):

    (SALIDA / nombre).write_text(
        contenido,
        encoding="utf-8"
    )


# ==========================================
# INICIO
# ==========================================

print("=" * 55)
print("VALIDACION DE INTEGRACION DE FUENTES")
print("=" * 55)

resumen = []
comparaciones = []
duplicados = []
diferencias = []

resumen.append("VALIDACION DE INTEGRACION")
resumen.append("=" * 60)


# ==========================================
# 1. ARCHIVOS CLIMATICOS
# ==========================================

archivos = sorted([
    f for f in CLIMA.rglob("*.xlsx")
    if not f.name.startswith("~$")
])

if not archivos:
    raise FileNotFoundError(
        f"No se encontraron Excel en {CLIMA}"
    )

print("\nArchivos climaticos encontrados:", len(archivos))

referencias = {}

ubigeos_clima = set()

for archivo in archivos:

    print(f"\nProcesando: {archivo.name}")

    resumen.append(f"\nARCHIVO: {archivo.name}")

    try:

        excel = pd.ExcelFile(archivo)

        hojas_disponibles = excel.sheet_names

        for hoja in ["departamento", "provincia", "distrito"]:

            if hoja not in hojas_disponibles:
                resumen.append(
                    f"HOJA NO ENCONTRADA: {hoja}"
                )
                continue

            df = pd.read_excel(
                excel,
                sheet_name=hoja
            )

            df.columns = (
                df.columns.astype(str)
                .str.strip()
                .str.lower()
            )

            print(
                f"  Hoja {hoja}: {len(df):,} registros"
            )

            # Validar columnas
            requeridas = ["ano", "semana"]

            if hoja == "departamento":
                requeridas.append("departamento")

            elif hoja == "provincia":
                requeridas.extend([
                    "departamento", "provincia"
                ])

            elif hoja == "distrito":
                requeridas.append("ubigeo")

            faltantes = [
                c for c in requeridas
                if c not in df.columns
            ]

            if faltantes:
                resumen.append(
                    f"Columnas faltantes en {hoja}: {faltantes}"
                )
                continue

            # Normalizar UBIGEO
            if hoja == "distrito":

                df["ubigeo"] = normalizar_ubigeo(
                    df["ubigeo"]
                )

                ubigeos_clima.update(
                    df["ubigeo"].dropna().tolist()
                )

            # Definir clave de análisis
            if hoja == "departamento":
                claves = [
                    "departamento", "ano", "semana"
                ]

            elif hoja == "provincia":
                claves = [
                    "departamento", "provincia",
                    "ano", "semana"
                ]

            else:
                claves = [
                    "ubigeo", "ano", "semana"
                ]

            # Revisar claves repetidas
            frecuencias = df.groupby(
                claves,
                dropna=False
            ).size()

            repetidos = frecuencias[
                frecuencias > 1
            ]

            filas_repetidas = int(
                repetidos.sum()
            )

            # Comparar contenido de hojas
            firma = huella(df)

            if hoja not in referencias:
                referencias[hoja] = firma

            identico = (
                firma == referencias[hoja]
            )

            comparaciones.append({
                "archivo": archivo.name,
                "hoja": hoja,
                "registros": len(df),
                "huella": firma,
                "igual_al_primer_archivo": identico
            })

            resumen.append(f"\nHOJA: {hoja.upper()}")
            resumen.append(
                f"Registros: {len(df):,}"
            )
            resumen.append(
                f"Grupos con claves repetidas: {len(repetidos):,}"
            )
            resumen.append(
                f"Filas en grupos repetidos: {filas_repetidas:,}"
            )
            resumen.append(
                f"Contenido identico al primer archivo: {identico}"
            )

            if hoja == "distrito":
                resumen.append(
                    f"UBIGEO diferentes: {df['ubigeo'].nunique()}"
                )

            # Revisar variables climaticas
            variables = [
                "tmean", "tmax", "tmin",
                "humr", "ptot", "n_dias"
            ]

            nulos = {
                c: int(df[c].isna().sum())
                for c in variables
                if c in df.columns
            }

            resumen.append(
                f"Nulos climaticos: {nulos}"
            )

            # Guardar claves repetidas del primer Excel
            if archivo == archivos[0] and len(repetidos) > 0:

                detalle = df[
                    df.duplicated(
                        subset=claves,
                        keep=False
                    )
                ].copy()

                detalle.insert(0, "hoja", hoja)

                duplicados.append(detalle)

        excel.close()

    except Exception as e:

        resumen.append(
            f"ERROR EN {archivo.name}: {str(e)}"
        )

        print("ERROR:", str(e))


# ==========================================
# 2. REVISAR GEOGRAFIA
# ==========================================

print("\nRevisando archivo geografico...")

gpkg_files = list(
    GEOGRAFIA.rglob("*.gpkg")
)

geo_ubigeos = set()

if not gpkg_files:

    resumen.append(
        "\nNo se encontro archivo GPKG."
    )

else:

    gpkg = gpkg_files[0]

    con_geo = sqlite3.connect(
        f"file:{gpkg.as_posix()}?mode=ro",
        uri=True
    )

    try:

        contenido = pd.read_sql_query(
            """
            SELECT table_name, data_type
            FROM gpkg_contents
            WHERE data_type = 'features'
            """,
            con_geo
        )

        capa_encontrada = False

        for _, fila in contenido.iterrows():

            nombre = str(fila["table_name"])

            seguro = nombre.replace('"', '""')

            estructura = con_geo.execute(
                f'PRAGMA table_info("{seguro}")'
            ).fetchall()

            columnas_geo = [
                x[1] for x in estructura
            ]

            ubigeo_col = next(
                (
                    c for c in columnas_geo
                    if c.lower() == "ubigeo"
                ),
                None
            )

            if ubigeo_col is None:
                continue

            consulta = (
                f'SELECT "{ubigeo_col}" '
                f'FROM "{seguro}"'
            )

            geo = pd.read_sql_query(
                consulta,
                con_geo
            )

            geo_ubigeos = set(
                normalizar_ubigeo(
                    geo[ubigeo_col]
                ).dropna().tolist()
            )

            resumen.append(
                f"\nCAPA GEOGRAFICA: {nombre}"
            )

            resumen.append(
                f"Registros geograficos: {len(geo):,}"
            )

            resumen.append(
                f"UBIGEO diferentes: {len(geo_ubigeos):,}"
            )

            capa_encontrada = True
            break

        if not capa_encontrada:

            resumen.append(
                "No se encontro una capa con columna UBIGEO."
            )

    finally:
        con_geo.close()


# ==========================================
# 3. REVISAR UBIGEO MINSA
# ==========================================

print("\nRevisando UBIGEO de MINSA...")

minsa_ubigeos = set()

for i, chunk in enumerate(pd.read_csv(
    MINSA,
    usecols=["ubigeo"],
    dtype="string",
    encoding="utf-8-sig",
    chunksize=200000
), start=1):

    minsa_ubigeos.update(
        normalizar_ubigeo(
            chunk["ubigeo"]
        ).dropna().tolist()
    )

    print(
        f"Bloque MINSA {i} procesado"
    )


# ==========================================
# 4. COMPARAR UBIGEO
# ==========================================

print("\nComparando codigos territoriales...")

comparaciones_ubigeo = [
    (
        "CLIMA_NO_GEOGRAFIA",
        ubigeos_clima - geo_ubigeos
    ),
    (
        "GEOGRAFIA_NO_CLIMA",
        geo_ubigeos - ubigeos_clima
    ),
    (
        "MINSA_NO_CLIMA",
        minsa_ubigeos - ubigeos_clima
    ),
    (
        "MINSA_NO_GEOGRAFIA",
        minsa_ubigeos - geo_ubigeos
    )
]

for nombre, conjunto in comparaciones_ubigeo:

    resumen.append(
        f"\n{nombre}: {len(conjunto):,}"
    )

    print(
        nombre, ":", len(conjunto)
    )

    for codigo in sorted(conjunto):

        diferencias.append({
            "comparacion": nombre,
            "ubigeo": codigo
        })


# ==========================================
# 5. INSPECCIONAR POBLACION
# ==========================================

print("\nRevisando archivo poblacional...")

poblacion_files = list(
    POBLACION.rglob("Limpia.xlsx")
)

if poblacion_files:

    archivo_poblacion = poblacion_files[0]

    vista = pd.read_excel(
        archivo_poblacion,
        header=None,
        nrows=20
    )

    texto = vista.fillna("").to_string(
        index=False,
        header=False
    )

    guardar_txt(
        "44_vista_poblacion.txt",
        texto
    )

    resumen.append(
        "\nVista de poblacion generada."
    )

else:

    resumen.append(
        "\nNo se encontro Limpia.xlsx."
    )


# ==========================================
# 6. EXPORTAR RESULTADOS
# ==========================================

pd.DataFrame(comparaciones).to_csv(
    SALIDA / "41_comparacion_clima.csv",
    index=False,
    encoding="utf-8-sig"
)

pd.DataFrame(
    diferencias,
    columns=["comparacion", "ubigeo"]
).to_csv(
    SALIDA / "43_diferencias_ubigeo.csv",
    index=False,
    encoding="utf-8-sig"
)

if duplicados:

    pd.concat(
        duplicados,
        ignore_index=True
    ).to_csv(
        SALIDA / "42_claves_repetidas.csv",
        index=False,
        encoding="utf-8-sig"
    )

else:

    pd.DataFrame(
        columns=["hoja"]
    ).to_csv(
        SALIDA / "42_claves_repetidas.csv",
        index=False,
        encoding="utf-8-sig"
    )

guardar_txt(
    "40_resumen_validacion.txt",
    "\n".join(resumen)
)


# ==========================================
# 7. FINALIZACION
# ==========================================

print("\n" + "=" * 55)
print("VALIDACION FINALIZADA")
print("=" * 55)

print("Archivos climaticos:", len(archivos))
print("UBIGEO clima:", len(ubigeos_clima))
print("UBIGEO geografia:", len(geo_ubigeos))
print("UBIGEO MINSA:", len(minsa_ubigeos))

print("\nResultados guardados en:")
print(SALIDA)
