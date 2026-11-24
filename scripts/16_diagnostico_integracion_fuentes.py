
from pathlib import Path
import pandas as pd
import sqlite3
import re

# ============================================================
# CONFIGURACION
# ============================================================

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

CLIMA_ORIGINAL = BASE / "data/raw/clima/era5_land"

CLIMA_RECUPERADO = (
    BASE / "data/processed/clima/"
    "recuperado_13_distritos_fecha_corregida"
)

CLIMA_RAW_RECUPERADO = (
    BASE / "data/raw/clima/recuperado_13_distritos"
)

MINSA = BASE / "data/raw/epidemiologia/data1.csv"

POBLACION = BASE / "data/raw/poblacion/Limpia.xlsx"

GEOGRAFIA = BASE / "data/raw/geografia/DISTRITO.gpkg"

SALIDA = BASE / "reports/diagnostico_integracion"

SALIDA.mkdir(parents=True, exist_ok=True)

reporte = []


def escribir(texto=""):
    texto = str(texto)
    print(texto)
    reporte.append(texto)


def leer_csv_muestra(archivo, filas=5):

    mejor = None
    mejor_formato = None

    for encoding in ["utf-8-sig", "utf-8", "latin1"]:

        for separador in [None, ",", ";", "\t"]:

            try:

                argumentos = {
                    "nrows": filas,
                    "dtype": "string",
                    "encoding": encoding,
                    "sep": separador,
                }

                if separador is None:
                    argumentos["engine"] = "python"

                df = pd.read_csv(archivo, **argumentos)

                if mejor is None or len(df.columns) > len(mejor.columns):

                    mejor = df
                    mejor_formato = (encoding, separador)

                if len(df.columns) > 2:
                    return df, mejor_formato

            except Exception:
                continue

    if mejor is None:
        raise ValueError(f"No se pudo leer: {archivo}")

    return mejor, mejor_formato


def mostrar_muestra(archivo, filas=3):

    df, formato = leer_csv_muestra(archivo, filas)

    escribir(f"ARCHIVO: {archivo.name}")
    escribir(f"CODIFICACION: {formato[0]}")
    escribir(f"SEPARADOR: {formato[1]}")
    escribir(f"COLUMNAS ({len(df.columns)}):")
    escribir(" | ".join(map(str, df.columns)))

    escribir("MUESTRA:")
    escribir(df.to_string(index=False, max_cols=None))

    return df


def extraer_anio(archivo):

    resultado = re.search(r"(20\d{2})", archivo.name)

    return int(resultado.group(1)) if resultado else None


# ============================================================
# INICIO
# ============================================================

escribir("=" * 65)
escribir("DIAGNOSTICO DEFINITIVO DE FUENTES")
escribir("=" * 65)


# ============================================================
# 1. CLIMA NACIONAL ORIGINAL
# ============================================================

escribir("\n1. CLIMA NACIONAL ORIGINAL")

archivos_clima = sorted(
    CLIMA_ORIGINAL.glob("clima_dengue_peru_*.csv")
)

anios_clima = {
    extraer_anio(f)
    for f in archivos_clima
}

esperados = set(range(2000, 2026))

escribir(f"ARCHIVOS: {len(archivos_clima)}")
escribir(f"ANIOS: {sorted(anios_clima)}")
escribir(f"ANIOS FALTANTES: {sorted(esperados - anios_clima)}")

if archivos_clima:

    mostrar_muestra(archivos_clima[0])

    if len(archivos_clima) > 1:
        escribir("\nULTIMO ARCHIVO:")
        mostrar_muestra(archivos_clima[-1])


# ============================================================
# 2. CLIMA RECUPERADO CORREGIDO
# ============================================================

escribir("\n" + "=" * 65)
escribir("2. CLIMA RECUPERADO CORREGIDO")
escribir("=" * 65)

archivos_recuperados = sorted(
    CLIMA_RECUPERADO.glob("CLIMA_RECUPERADO_*.csv")
)

anios_recuperados = {
    extraer_anio(f)
    for f in archivos_recuperados
}

escribir(f"ARCHIVOS: {len(archivos_recuperados)}")
escribir(f"ANIOS: {sorted(anios_recuperados)}")
escribir(
    f"ANIOS FALTANTES: "
    f"{sorted(esperados - anios_recuperados)}"
)

if archivos_recuperados:

    mostrar_muestra(archivos_recuperados[0])

    escribir("\nULTIMO ARCHIVO:")
    mostrar_muestra(archivos_recuperados[-1])


# ============================================================
# 3. COMPARACION DE FECHAS RECUPERADAS
# ============================================================

escribir("\n" + "=" * 65)
escribir("3. COMPARACION DE VERSIONES RECUPERADAS")
escribir("=" * 65)

archivo_raw = CLIMA_RAW_RECUPERADO / "CLIMA_RECUPERADO_2000.csv"
archivo_procesado = (
    CLIMA_RECUPERADO / "CLIMA_RECUPERADO_2000.csv"
)

for archivo in [archivo_raw, archivo_procesado]:

    if archivo.exists():

        df = pd.read_csv(
            archivo,
            nrows=3,
            dtype="string",
            encoding="utf-8-sig"
        )

        escribir(f"\nARCHIVO: {archivo}")
        escribir(
            df[
                [
                    c for c in [
                        "ano",
                        "semana",
                        "fecha_inicio",
                        "fecha_fin",
                        "ubigeo",
                        "distrito"
                    ]
                    if c in df.columns
                ]
            ].to_string(index=False)
        )

    else:

        escribir(f"NO ENCONTRADO: {archivo}")


# ============================================================
# 4. EPIDEMIOLOGIA MINSA
# ============================================================

escribir("\n" + "=" * 65)
escribir("4. FUENTE EPIDEMIOLOGICA MINSA")
escribir("=" * 65)

if MINSA.exists():

    escribir(f"ARCHIVO: {MINSA}")
    escribir(f"TAMANO MB: {MINSA.stat().st_size / 1024**2:.2f}")

    df_minsa = mostrar_muestra(MINSA, 8)

    escribir("\nCOLUMNAS CANDIDATAS:")

    terminos = [
        "ubigeo",
        "fecha",
        "ano",
        "año",
        "semana",
        "caso",
        "dengue",
        "departamento",
        "provincia",
        "distrito",
        "edad",
        "sexo",
        "serotipo",
        "diagnostico"
    ]

    candidatas = [
        c for c in df_minsa.columns
        if any(t in str(c).lower() for t in terminos)
    ]

    escribir(candidatas)

else:

    escribir(f"NO ENCONTRADO: {MINSA}")


# ============================================================
# 5. POBLACION
# ============================================================

escribir("\n" + "=" * 65)
escribir("5. FUENTE POBLACIONAL")
escribir("=" * 65)

if POBLACION.exists():

    excel = pd.ExcelFile(POBLACION)

    escribir(f"ARCHIVO: {POBLACION}")
    escribir(f"HOJAS: {excel.sheet_names}")

    for hoja in excel.sheet_names:

        escribir(f"\nHOJA: {hoja}")

        df = pd.read_excel(
            excel,
            sheet_name=hoja,
            header=None,
            nrows=15
        )

        escribir("PRIMERAS 15 FILAS:")
        escribir(df.to_string(index=False, header=False))

    excel.close()

else:

    escribir(f"NO ENCONTRADO: {POBLACION}")


# ============================================================
# 6. GEOGRAFIA
# ============================================================

escribir("\n" + "=" * 65)
escribir("6. FUENTE GEOGRAFICA")
escribir("=" * 65)

if GEOGRAFIA.exists():

    escribir(f"ARCHIVO: {GEOGRAFIA}")

    conexion = sqlite3.connect(
        f"file:{GEOGRAFIA.as_posix()}?mode=ro",
        uri=True
    )

    try:

        capas = pd.read_sql_query(
            """
            SELECT table_name, data_type
            FROM gpkg_contents
            WHERE data_type = 'features'
            """,
            conexion
        )

        escribir("\nCAPAS DISPONIBLES:")
        escribir(capas.to_string(index=False))

        for _, fila in capas.iterrows():

            tabla = str(fila["table_name"])
            segura = tabla.replace('"', '""')

            estructura = conexion.execute(
                f'PRAGMA table_info("{segura}")'
            ).fetchall()

            columnas = [x[1] for x in estructura]

            escribir(f"\nCAPA: {tabla}")
            escribir("COLUMNAS:")
            escribir(columnas)

            columnas_muestra = [
                c for c in columnas
                if c.lower() not in ["geom", "geometry"]
            ][:15]

            if columnas_muestra:

                seleccion = ", ".join(
                    f'"{c}"' for c in columnas_muestra
                )

                muestra = pd.read_sql_query(
                    f'SELECT {seleccion} FROM "{segura}" LIMIT 5',
                    conexion
                )

                escribir("MUESTRA:")
                escribir(muestra.to_string(index=False))

    finally:

        conexion.close()

else:

    escribir(f"NO ENCONTRADO: {GEOGRAFIA}")


# ============================================================
# 7. RESULTADO
# ============================================================

escribir("\n" + "=" * 65)
escribir("DIAGNOSTICO FINALIZADO")
escribir("=" * 65)

escribir(f"CLIMA ORIGINAL: {len(archivos_clima)}")
escribir(f"CLIMA RECUPERADO: {len(archivos_recuperados)}")
escribir(f"MINSA EXISTE: {MINSA.exists()}")
escribir(f"POBLACION EXISTE: {POBLACION.exists()}")
escribir(f"GEOGRAFIA EXISTE: {GEOGRAFIA.exists()}")

destino = SALIDA / "01_diagnostico_fuentes.txt"

destino.write_text(
    "\n".join(reporte),
    encoding="utf-8"
)

print("\nREPORTE GUARDADO EN:")
print(destino)

print("\nNO SE MODIFICARON LOS DATOS ORIGINALES.")
print("NO SE MODIFICARON LOS DATOS PROCESADOS.")
print("NO SE GENERARON DATASETS INTEGRADOS.")
