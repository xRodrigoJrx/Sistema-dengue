from pathlib import Path
import pandas as pd
import sqlite3

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

CARPETAS = {
    "CLIMA": BASE / "data/raw/clima",
    "POBLACION": BASE / "data/raw/poblacion",
    "GEOGRAFIA": BASE / "data/raw/geografia"
}

SALIDA = BASE / "reports/auditoria_fuentes"
SALIDA.mkdir(parents=True, exist_ok=True)

inventario = []
hojas = []
columnas = []
capas = []
informe = []

informe.append("AUDITORIA DE FUENTES SECUNDARIAS")
informe.append("=" * 60)

# ==========================================
# 1. REVISAR EXCEL
# ==========================================

for categoria in ["CLIMA", "POBLACION"]:

    carpeta = CARPETAS[categoria]

    informe.append(f"\nFUENTE: {categoria}")
    informe.append("=" * 45)

    if not carpeta.exists():
        informe.append(f"CARPETA NO ENCONTRADA: {carpeta}")
        continue

    archivos = [
        f for f in carpeta.rglob("*")
        if f.is_file()
        and f.suffix.lower() in [".xlsx", ".xls"]
        and not f.name.startswith("~$")
    ]

    if not archivos:
        informe.append("No se encontraron archivos Excel.")

    for archivo in archivos:

        tamano = round(
            archivo.stat().st_size / (1024 * 1024), 2
        )

        inventario.append({
            "categoria": categoria,
            "archivo": archivo.name,
            "ruta": str(archivo),
            "tamano_mb": tamano
        })

        informe.append(f"\nARCHIVO: {archivo.name}")
        informe.append(f"Tamaño: {tamano} MB")

        try:

            excel = pd.ExcelFile(archivo)

            informe.append(
                f"Hojas encontradas: {excel.sheet_names}"
            )

            for nombre_hoja in excel.sheet_names:

                df = pd.read_excel(
                    archivo,
                    sheet_name=nombre_hoja
                )

                df.columns = (
                    df.columns.astype(str)
                    .str.strip()
                    .str.lower()
                )

                duplicados = int(
                    df.duplicated().sum()
                )

                hojas.append({
                    "categoria": categoria,
                    "archivo": archivo.name,
                    "hoja": nombre_hoja,
                    "registros": len(df),
                    "columnas": len(df.columns),
                    "duplicados_exactos": duplicados
                })

                informe.append(
                    f"\nHOJA: {nombre_hoja}"
                )

                informe.append(
                    f"Registros: {len(df):,}"
                )

                informe.append(
                    f"Columnas: {len(df.columns)}"
                )

                informe.append(
                    f"Duplicados exactos: {duplicados:,}"
                )

                informe.append(
                    "COLUMNAS: " + str(df.columns.tolist())
                )

                for col in df.columns:

                    serie = df[col].astype("string")

                    nulos = int(df[col].isna().sum())

                    vacios = int(
                        serie.str.strip()
                        .eq("")
                        .fillna(False)
                        .sum()
                    )

                    columnas.append({
                        "categoria": categoria,
                        "archivo": archivo.name,
                        "hoja": nombre_hoja,
                        "columna": col,
                        "tipo_dato": str(df[col].dtype),
                        "nulos": nulos,
                        "vacios": vacios,
                        "valores_diferentes": int(
                            df[col].nunique(dropna=True)
                        )
                    })

                    informe.append(
                        f"  {col}: nulos={nulos:,}, "
                        f"vacios={vacios:,}, "
                        f"unicos={df[col].nunique(dropna=True):,}"
                    )

                informe.append("\nMUESTRA DE REGISTROS:")
                informe.append(
                    df.head(4).to_string(index=False)
                )

            excel.close()

        except Exception as e:

            informe.append(
                f"ERROR AL LEER ARCHIVO: {str(e)}"
            )

# ==========================================
# 2. REVISAR GEOGRAFIA GPKG
# ==========================================

carpeta = CARPETAS["GEOGRAFIA"]

informe.append("\n\nFUENTE: GEOGRAFIA")
informe.append("=" * 45)

if carpeta.exists():

    archivos = list(carpeta.rglob("*.gpkg"))

    for archivo in archivos:

        informe.append(f"\nARCHIVO: {archivo.name}")

        try:

            con = sqlite3.connect(
                f"file:{archivo.as_posix()}?mode=ro",
                uri=True
            )

            tablas = pd.read_sql_query(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'",
                con
            )["name"].tolist()

            informe.append(
                "Tablas internas: " + str(tablas)
            )

            if "gpkg_contents" in tablas:

                contenido = pd.read_sql_query(
                    "SELECT * FROM gpkg_contents",
                    con
                )

                for _, fila in contenido.iterrows():

                    nombre = fila["table_name"]

                    seguro = str(nombre).replace('"', '""')

                    cantidad = con.execute(
                        f'SELECT COUNT(*) FROM "{seguro}"'
                    ).fetchone()[0]

                    capas.append({
                        "archivo": archivo.name,
                        "capa": nombre,
                        "tipo": fila["data_type"],
                        "registros": cantidad,
                        "srs_id": fila.get("srs_id")
                    })

                    informe.append(
                        f"\nCAPA: {nombre}"
                    )

                    informe.append(
                        f"Tipo: {fila['data_type']}"
                    )

                    informe.append(
                        f"Registros: {cantidad:,}"
                    )

                    estructura = con.execute(
                        f'PRAGMA table_info("{seguro}")'
                    ).fetchall()

                    informe.append(
                        "Columnas: " + str([
                            x[1] for x in estructura
                        ])
                    )

            if "gpkg_geometry_columns" in tablas:

                geometria = pd.read_sql_query(
                    "SELECT * FROM gpkg_geometry_columns",
                    con
                )

                informe.append("\nGEOMETRIAS:")
                informe.append(
                    geometria.to_string(index=False)
                )

            con.close()

        except Exception as e:

            informe.append(
                f"ERROR AL LEER GPKG: {str(e)}"
            )

else:
    informe.append("Carpeta geografica no encontrada.")

# ==========================================
# 3. EXPORTAR INFORMES
# ==========================================

pd.DataFrame(inventario).to_csv(
    SALIDA / "36_inventario_archivos.csv",
    index=False,
    encoding="utf-8-sig"
)

pd.DataFrame(hojas).to_csv(
    SALIDA / "37_estructura_excel.csv",
    index=False,
    encoding="utf-8-sig"
)

pd.DataFrame(columnas).to_csv(
    SALIDA / "38_auditoria_columnas.csv",
    index=False,
    encoding="utf-8-sig"
)

pd.DataFrame(capas).to_csv(
    SALIDA / "39_capas_geograficas.csv",
    index=False,
    encoding="utf-8-sig"
)

(SALIDA / "resumen_fuentes.txt").write_text(
    "\n".join(informe),
    encoding="utf-8"
)

print("\n" + "=" * 55)
print("AUDITORIA DE FUENTES COMPLETADA")
print("=" * 55)

print("Archivos encontrados:", len(inventario))
print("Hojas Excel revisadas:", len(hojas))
print("Columnas examinadas:", len(columnas))
print("Capas geograficas:", len(capas))

print("\nResultados guardados en:")
print(SALIDA)
