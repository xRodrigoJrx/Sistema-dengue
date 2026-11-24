from pathlib import Path
import sys
import pandas as pd
import pyodbc

# ============================================================
# CONFIGURACION
# ============================================================

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

SALIDA = BASE / "data/processed/pronostico_nacional"
REPORTES = BASE / "reports/pronostico_nacional"

ARCHIVO = SALIDA / "serie_nacional_semanal_2000_2025.csv"
REPORTE = REPORTES / "40_diagnostico_serie_nacional.txt"

SERVIDOR = "127.0.0.1,51433"
BASE_DATOS = "dengue_analytics"

CONEXION = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={SERVIDOR};"
    f"DATABASE={BASE_DATOS};"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

ESPERADO_SEMANAS = 1357
ESPERADO_DISTRITOS = 1891

VARIABLES_CLIMA = [
    "tmean_media_distritos",
    "tmax_media_distritos",
    "tmin_media_distritos",
    "humr_media_distritos",
    "ptot_media_distritos",
]


# ============================================================
# 1. VERIFICAR CONEXION Y ESTRUCTURA
# ============================================================

def main():

    print("=" * 65)
    print("PREPARACION DE SERIE NACIONAL DE DENGUE")
    print("HISTORICO 2000-2025")
    print("=" * 65)

    SALIDA.mkdir(parents=True, exist_ok=True)
    REPORTES.mkdir(parents=True, exist_ok=True)

    print("\n1. CONECTANDO A SQL SERVER...")

    try:
        conn = pyodbc.connect(CONEXION, timeout=20)
    except Exception as error:
        raise RuntimeError(
            f"No se pudo conectar a SQL Server: {error}"
        )

    print("CONEXION CORRECTA")

    try:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME = 'vw_historico_dengue'
            ORDER BY ORDINAL_POSITION
        """)

        columnas_sql = cursor.fetchall()

        if not columnas_sql:
            raise ValueError(
                "No se encontro dbo.vw_historico_dengue."
            )

        columnas = {
            str(fila[0]).lower()
            for fila in columnas_sql
        }

        requeridas = {
            "ubigeo",
            "ano",
            "semana",
            "fecha_inicio",
            "fecha_fin",
            "casos_reportados",
            "registro_minsa",
            "tmean",
            "tmax",
            "tmin",
            "humr",
            "ptot",
        }

        faltantes = requeridas - columnas

        if faltantes:
            raise ValueError(
                f"Columnas faltantes en la vista: {sorted(faltantes)}"
            )

        print("ESTRUCTURA SQL VALIDADA")
        print("Columnas disponibles:", len(columnas))


        # ====================================================
        # 2. AGREGAR INFORMACION EN SQL SERVER
        # ====================================================

        print("\n2. CONSOLIDANDO INFORMACION SEMANAL...")

        consulta = """
            SELECT
                CAST(fecha_inicio AS date) AS fecha_inicio,

                MAX(CAST(fecha_fin AS date)) AS fecha_fin,

                MAX(ano) AS ano,

                MAX(semana) AS semana,

                SUM(
                    CASE
                        WHEN registro_minsa = 1
                        THEN COALESCE(
                            TRY_CONVERT(bigint, casos_reportados),
                            0
                        )
                        ELSE 0
                    END
                ) AS casos_dengue,

                AVG(TRY_CONVERT(float, tmean))
                    AS tmean_media_distritos,

                AVG(TRY_CONVERT(float, tmax))
                    AS tmax_media_distritos,

                AVG(TRY_CONVERT(float, tmin))
                    AS tmin_media_distritos,

                AVG(TRY_CONVERT(float, humr))
                    AS humr_media_distritos,

                AVG(TRY_CONVERT(float, ptot))
                    AS ptot_media_distritos,

                COUNT(DISTINCT ubigeo)
                    AS distritos_incluidos,

                SUM(
                    CASE WHEN registro_minsa = 1
                    THEN 1 ELSE 0 END
                ) AS distritos_con_registro

            FROM dbo.vw_historico_dengue

            GROUP BY CAST(fecha_inicio AS date)

            ORDER BY fecha_inicio;
        """

        cursor.execute(consulta)

        nombres = [
            columna[0]
            for columna in cursor.description
        ]

        registros = cursor.fetchall()

        df = pd.DataFrame.from_records(
            registros,
            columns=nombres
        )

    finally:
        conn.close()


    # ============================================================
    # 3. LIMPIEZA Y VALIDACION
    # ============================================================

    print("\n3. VALIDANDO SERIE TEMPORAL...")

    df["fecha_inicio"] = pd.to_datetime(
        df["fecha_inicio"],
        errors="coerce"
    )

    df["fecha_fin"] = pd.to_datetime(
        df["fecha_fin"],
        errors="coerce"
    )

    numericas = [
        "ano",
        "semana",
        "casos_dengue",
        "distritos_incluidos",
        "distritos_con_registro",
    ] + VARIABLES_CLIMA

    for columna in numericas:
        df[columna] = pd.to_numeric(
            df[columna],
            errors="coerce"
        )

    df = df.sort_values("fecha_inicio").reset_index(drop=True)

    problemas = []

    if df.empty:
        problemas.append("La serie historica esta vacia.")

    if df["fecha_inicio"].isna().any():
        problemas.append("Existen fechas invalidas.")

    if df["fecha_inicio"].duplicated().any():
        problemas.append("Existen fechas semanales duplicadas.")

    if len(df) != ESPERADO_SEMANAS:
        problemas.append(
            f"Se esperaban {ESPERADO_SEMANAS} semanas "
            f"y se encontraron {len(df)}."
        )

    if not df.empty:

        diferencias = (
            df["fecha_inicio"].diff().dt.days.dropna()
        )

        semanas_irregulares = int(
            (diferencias != 7).sum()
        )

        if semanas_irregulares:
            problemas.append(
                f"Existen {semanas_irregulares} "
                "intervalos diferentes de 7 dias."
            )

        if df["fecha_inicio"].min() != pd.Timestamp("2000-01-02"):
            problemas.append("Fecha inicial historica diferente.")

        if df["fecha_inicio"].max() != pd.Timestamp("2025-12-28"):
            problemas.append("Fecha final historica diferente.")

    cobertura = (
        df["distritos_incluidos"] == ESPERADO_DISTRITOS
    ).all()

    if not cobertura:
        problemas.append(
            "Existen semanas con cobertura distinta "
            "de 1891 distritos."
        )

    nulos_clima = df[VARIABLES_CLIMA].isna().sum()

    for variable, cantidad in nulos_clima.items():
        if cantidad > 0:
            problemas.append(
                f"{variable}: {cantidad} valores nulos."
            )

    if (df["casos_dengue"] < 0).any():
        problemas.append("Se encontraron casos negativos.")


    # ============================================================
    # 4. GUARDAR RESULTADOS
    # ============================================================

    print("\n4. GENERANDO DATASET NACIONAL...")

    df.to_csv(
        ARCHIVO,
        index=False,
        encoding="utf-8-sig"
    )

    resumen = [
        "DIAGNOSTICO DE SERIE NACIONAL DE DENGUE",
        "=" * 60,
        f"Registros semanales: {len(df):,}",
        f"Fecha inicial: {df['fecha_inicio'].min()}",
        f"Fecha final: {df['fecha_inicio'].max()}",
        f"Total de casos: {df['casos_dengue'].sum():,.0f}",
        f"Distritos esperados: {ESPERADO_DISTRITOS}",
        f"Cobertura completa: {cobertura}",
        "",
        "VARIABLES CLIMATICAS",
        "-" * 60,
    ]

    for variable in VARIABLES_CLIMA:
        resumen.append(
            f"{variable}: "
            f"{df[variable].notna().sum():,} valores disponibles"
        )

    resumen.extend([
        "",
        "ULTIMAS 5 SEMANAS",
        "-" * 60,
        df.tail(5).to_string(index=False),
        "",
        "VALIDACION",
        "-" * 60,
    ])

    if problemas:
        resumen.append("ESTADO: REQUIERE REVISION")

        for problema in problemas:
            resumen.append("ERROR: " + problema)
    else:
        resumen.append("ESTADO: VALIDADO CORRECTAMENTE")

    REPORTE.write_text(
        "\n".join(resumen),
        encoding="utf-8"
    )

    print("\n".join(resumen))

    print("\nARCHIVO GENERADO:")
    print(ARCHIVO)

    print("\nREPORTE GENERADO:")
    print(REPORTE)

    if problemas:
        raise SystemExit(
            "\nNO CONTINUAR CON EL ENTRENAMIENTO "
            "HASTA RESOLVER LOS PROBLEMAS."
        )

    print("\n" + "=" * 65)
    print("SERIE NACIONAL PREPARADA CORRECTAMENTE")
    print("=" * 65)


if __name__ == "__main__":
    main()
