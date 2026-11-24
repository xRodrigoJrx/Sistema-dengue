
from pathlib import Path
import pandas as pd
import numpy as np

# ============================================================
# AUDITORIA DE EXTREMOS CLIMATICOS 2000-2025
# SOLO LECTURA - NO MODIFICA DATOS
# ============================================================

BASE = Path(__file__).resolve().parents[1]

CARPETA = BASE / "data" / "processed" / "clima_integrado"
REPORTES = BASE / "reports" / "auditoria_extremos_climaticos"

ANIOS = range(2000, 2026)

UBIGEOS_RECUPERADOS = {
    "070102", "070104", "070105",
    "110501", "140114",
    "150108", "150120", "150121",
    "150124", "150136", "150138",
    "150803", "150805"
}

VARIABLES = ["tmean", "tmin", "tmax", "humr", "ptot"]

COLUMNAS = [
    "ano", "semana", "fecha_inicio", "fecha_fin",
    "ubigeo", "departamento", "provincia", "distrito"
]

extremos_anuales = []
resumenes = []


def contar_menores(df, variable, limite):
    if variable not in df.columns:
        return 0
    return int((df[variable] < limite).sum())


def contar_mayores(df, variable, limite):
    if variable not in df.columns:
        return 0
    return int((df[variable] > limite).sum())


def procesar_anio(anio):

    ruta = CARPETA / f"clima_dengue_peru_{anio}.csv"

    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    df = pd.read_csv(
        ruta,
        dtype={"ubigeo": "string"},
        low_memory=False
    )

    df.columns = df.columns.str.strip()

    requeridas = COLUMNAS + VARIABLES

    faltantes = [
        c for c in requeridas
        if c not in df.columns
    ]

    if faltantes:
        raise ValueError(
            f"{anio}: columnas faltantes: {faltantes}"
        )

    df["ubigeo"] = (
        df["ubigeo"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    for variable in VARIABLES + ["ptot_raw"]:
        if variable in df.columns:
            df[variable] = pd.to_numeric(
                df[variable],
                errors="coerce"
            )

    df["grupo"] = np.where(
        df["ubigeo"].isin(UBIGEOS_RECUPERADOS),
        "13_RECUPERADOS",
        "OTROS_DISTRITOS"
    )

    # --------------------------------------------------------
    # 1. EXTREMOS POR VARIABLE
    # --------------------------------------------------------

    columnas_salida = [
        c for c in COLUMNAS + ["grupo"]
        if c in df.columns
    ]

    for variable in VARIABLES:

        validos = df.dropna(subset=[variable])

        for tipo in ["MINIMO", "MAXIMO"]:

            if tipo == "MINIMO":
                muestra = validos.nsmallest(10, variable)
            else:
                muestra = validos.nlargest(10, variable)

            muestra = muestra[
                columnas_salida + [variable]
            ].copy()

            muestra["variable"] = variable
            muestra["tipo_extremo"] = tipo
            muestra["valor_evaluado"] = muestra[variable]

            extremos_anuales.append(muestra)

    # --------------------------------------------------------
    # 2. RESUMEN POR GRUPO
    # --------------------------------------------------------

    grupos = {
        "TODOS": df,
        "13_RECUPERADOS": df[
            df["grupo"] == "13_RECUPERADOS"
        ],
        "OTROS_DISTRITOS": df[
            df["grupo"] == "OTROS_DISTRITOS"
        ]
    }

    for nombre, sub in grupos.items():

        registro = {
            "anio": anio,
            "grupo": nombre,
            "registros": len(sub)
        }

        # Temperaturas: indicadores de revisión
        registro["tmean_menor_menos_5"] = contar_menores(
            sub, "tmean", -5
        )

        registro["tmean_mayor_30"] = contar_mayores(
            sub, "tmean", 30
        )

        registro["tmin_menor_menos_10"] = contar_menores(
            sub, "tmin", -10
        )

        registro["tmax_mayor_35"] = contar_mayores(
            sub, "tmax", 35
        )

        # Humedad
        registro["humr_menor_30"] = contar_menores(
            sub, "humr", 30
        )

        registro["humr_mayor_95"] = contar_mayores(
            sub, "humr", 95
        )

        # Precipitacion semanal
        registro["ptot_mayor_100"] = contar_mayores(
            sub, "ptot", 100
        )

        registro["ptot_mayor_300"] = contar_mayores(
            sub, "ptot", 300
        )

        registro["ptot_mayor_500"] = contar_mayores(
            sub, "ptot", 500
        )

        # Comparacion de precipitacion
        if "ptot_raw" in sub.columns:

            diferencia = (
                sub["ptot"] - sub["ptot_raw"]
            ).abs()

            registro["diferencias_ptot_raw"] = int(
                (diferencia > 0.000001).sum()
            )

            registro["diferencia_ptot_raw_maxima"] = (
                diferencia.max()
                if diferencia.notna().any()
                else np.nan
            )

        else:
            registro["diferencias_ptot_raw"] = np.nan
            registro["diferencia_ptot_raw_maxima"] = np.nan

        # Horas de precipitacion
        if "n_horas_ptot" in sub.columns:

            horas = pd.to_numeric(
                sub["n_horas_ptot"],
                errors="coerce"
            )

            registro["n_horas_ptot_nulos"] = int(
                horas.isna().sum()
            )

            registro["n_horas_ptot_no_168"] = int(
                (horas.notna() & (horas != 168)).sum()
            )

        else:
            registro["n_horas_ptot_nulos"] = np.nan
            registro["n_horas_ptot_no_168"] = np.nan

        resumenes.append(registro)


# ============================================================
# 3. EJECUCION
# ============================================================

def main():

    print("=" * 65)
    print("AUDITORIA DE EXTREMOS CLIMATICOS")
    print("PERIODO 2000-2025")
    print("=" * 65)

    REPORTES.mkdir(
        parents=True,
        exist_ok=True
    )

    for anio in ANIOS:

        print(f"\nANALIZANDO ANIO: {anio}")

        procesar_anio(anio)

        print("ANIO PROCESADO CORRECTAMENTE")

    # --------------------------------------------------------
    # 4. CONSOLIDAR EXTREMOS
    # --------------------------------------------------------

    todos_extremos = pd.concat(
        extremos_anuales,
        ignore_index=True
    )

    resultados = []

    for variable in VARIABLES:

        for tipo in ["MINIMO", "MAXIMO"]:

            sub = todos_extremos[
                (todos_extremos["variable"] == variable) &
                (todos_extremos["tipo_extremo"] == tipo)
            ].copy()

            sub = sub.sort_values(
                "valor_evaluado",
                ascending=(tipo == "MINIMO")
            )

            resultados.append(sub.head(20))

    df_extremos = pd.concat(
        resultados,
        ignore_index=True
    )

    df_resumen = pd.DataFrame(resumenes)

    # --------------------------------------------------------
    # 5. GUARDAR REPORTES
    # --------------------------------------------------------

    archivo_extremos = (
        REPORTES / "85_extremos_climaticos.csv"
    )

    archivo_resumen = (
        REPORTES / "86_revision_valores_extremos.csv"
    )

    df_extremos.to_csv(
        archivo_extremos,
        index=False,
        encoding="utf-8-sig"
    )

    df_resumen.to_csv(
        archivo_resumen,
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 6. RESULTADO
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print("RESUMEN DE INDICADORES DE REVISION")
    print("=" * 65)

    indicadores = [
        "tmean_menor_menos_5",
        "tmean_mayor_30",
        "tmin_menor_menos_10",
        "tmax_mayor_35",
        "humr_menor_30",
        "humr_mayor_95",
        "ptot_mayor_100",
        "ptot_mayor_300",
        "ptot_mayor_500",
        "diferencias_ptot_raw",
        "n_horas_ptot_no_168"
    ]

    print(
        df_resumen.groupby("grupo")[indicadores]
        .sum(min_count=1)
        .to_string()
    )

    print("\nREPORTES GENERADOS:")
    print(archivo_extremos)
    print(archivo_resumen)

    print("\nANIOS ANALIZADOS:", len(ANIOS))

    print("\nNO SE MODIFICARON LOS DATOS ORIGINALES.")
    print("NO SE MODIFICARON LOS ARCHIVOS CONSOLIDADOS.")

    print("=" * 65)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nAUDITORIA INTERRUMPIDA")
        print("MOTIVO:", error)
        raise
