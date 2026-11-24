
from pathlib import Path
import sys
import numpy as np
import pandas as pd

# ============================================================
# CONFIGURACION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

INPUT = (
    ROOT / "data/processed/dataset_maestro/"
    "dataset_maestro_dengue_2000_2025.csv.gz"
)

OUTPUT_DIR = ROOT / "data/processed/modelamiento"
REPORT_DIR = ROOT / "reports/modelamiento"

OUTPUT = (
    OUTPUT_DIR / "dataset_modelamiento_dengue_2000_2025.csv.gz"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

TARGET = "casos_dengue_reportados"

CLIMA = ["tmean", "tmax", "tmin", "humr", "ptot"]

CASOS_LAGS = [1, 2, 3, 4, 5, 6, 7, 8, 12, 52]

CLIMA_LAGS = [1, 2, 3, 4, 8]

COLUMNAS = [
    "ubigeo",
    "departamento",
    "provincia",
    "distrito",
    "ano",
    "semana",
    "fecha_inicio",
    "tmean",
    "tmax",
    "tmin",
    "humr",
    "ptot",
    TARGET,
    "registro_minsa",
    "clima_recuperado"
]

DTYPES = {
    "ubigeo": "string",
    "departamento": "category",
    "provincia": "category",
    "distrito": "category",
    "ano": "int16",
    "semana": "int8",
    "tmean": "float32",
    "tmax": "float32",
    "tmin": "float32",
    "humr": "float32",
    "ptot": "float32",
    TARGET: "float32",
    "registro_minsa": "int8",
    "clima_recuperado": "int8"
}


# ============================================================
# PROCESAMIENTO
# ============================================================

def main():

    print("=" * 65)
    print("INGENIERIA DE CARACTERISTICAS - DENGUE")
    print("PERIODO 2000-2025")
    print("=" * 65)

    if not INPUT.exists():
        raise FileNotFoundError(
            f"No se encuentra el dataset maestro: {INPUT}"
        )

    # --------------------------------------------------------
    # 1. CARGA
    # --------------------------------------------------------

    print("\n1. CARGANDO DATASET MAESTRO...")

    df = pd.read_csv(
        INPUT,
        compression="gzip",
        usecols=COLUMNAS,
        dtype=DTYPES,
        encoding="utf-8-sig"
    )

    print("REGISTROS:", f"{len(df):,}")
    print("COLUMNAS CARGADAS:", len(df.columns))

    # --------------------------------------------------------
    # 2. VALIDACIONES BASICAS
    # --------------------------------------------------------

    print("\n2. VALIDANDO INFORMACION...")

    df["ubigeo"] = (
        df["ubigeo"].str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )

    df["fecha_inicio"] = pd.to_datetime(
        df["fecha_inicio"], errors="coerce"
    )

    if df["fecha_inicio"].isna().any():
        raise ValueError("Existen fechas de inicio invalidas.")

    if df[TARGET].isna().any():
        raise ValueError("Existen casos de dengue nulos.")

    if df[CLIMA].isna().any().any():
        raise ValueError("Existen variables climaticas nulas.")

    if (df[TARGET] < 0).any():
        raise ValueError("Existen casos negativos.")

    if not df["registro_minsa"].isin([0, 1]).all():
        raise ValueError("registro_minsa contiene valores invalidos.")

    inconsistencias = (
        (df["registro_minsa"] == 0) & (df[TARGET] > 0)
    ).sum()

    if inconsistencias:
        raise ValueError(
            "Existen casos positivos sin registro MINSA."
        )

    if not np.allclose(df[TARGET], np.round(df[TARGET])):
        raise ValueError("Los casos contienen valores no enteros.")

    df[TARGET] = df[TARGET].astype("int32")

    # --------------------------------------------------------
    # 3. ORDENAMIENTO TEMPORAL
    # --------------------------------------------------------

    print("\n3. ORDENANDO SERIES TEMPORALES...")

    duplicados = df.duplicated(
        subset=["ubigeo", "fecha_inicio"]
    ).sum()

    if duplicados:
        raise ValueError(
            f"Se encontraron {duplicados} claves distrito-fecha duplicadas."
        )

    df.sort_values(
        ["ubigeo", "fecha_inicio"],
        inplace=True
    )

    df.reset_index(drop=True, inplace=True)

    print("DISTRITOS:", df["ubigeo"].nunique())
    print("DUPLICADOS:", duplicados)

    # --------------------------------------------------------
    # 4. VARIABLES TEMPORALES
    # --------------------------------------------------------

    print("\n4. GENERANDO VARIABLES TEMPORALES...")

    mes = df["fecha_inicio"].dt.month.astype("int8")
    semana = df["semana"].astype("float32")

    tiempo = {
        "mes": mes,
        "trimestre": ((mes - 1) // 3 + 1).astype("int8"),
        "semana_sin": np.sin(
            2 * np.pi * (semana - 1) / 52.1775
        ).astype("float32"),
        "semana_cos": np.cos(
            2 * np.pi * (semana - 1) / 52.1775
        ).astype("float32"),
        "mes_sin": np.sin(
            2 * np.pi * (mes - 1) / 12
        ).astype("float32"),
        "mes_cos": np.cos(
            2 * np.pi * (mes - 1) / 12
        ).astype("float32"),
        "tendencia_anual": (
            df["ano"] - 2000
        ).astype("int16")
    }

    # --------------------------------------------------------
    # 5. REZAGOS EPIDEMIOLOGICOS
    # --------------------------------------------------------

    print("\n5. GENERANDO REZAGOS DE DENGUE...")

    grouped = df.groupby("ubigeo", sort=False)

    features = {}

    for lag in CASOS_LAGS:

        nombre = f"casos_lag_{lag}"

        features[nombre] = (
            grouped[TARGET]
            .shift(lag)
            .astype("float32")
        )

    casos_lag_4 = [f"casos_lag_{i}" for i in range(1, 5)]
    casos_lag_8 = [f"casos_lag_{i}" for i in range(1, 9)]

    # --------------------------------------------------------
    # 6. REZAGOS CLIMATICOS
    # --------------------------------------------------------

    print("\n6. GENERANDO REZAGOS CLIMATICOS...")

    for variable in CLIMA:

        for lag in CLIMA_LAGS:

            nombre = f"{variable}_lag_{lag}"

            features[nombre] = (
                grouped[variable]
                .shift(lag)
                .astype("float32")
            )

    # Incorporar las variables generadas
    df = pd.concat(
        [
            df,
            pd.DataFrame(features, index=df.index),
            pd.DataFrame(tiempo, index=df.index)
        ],
        axis=1
    )

    # --------------------------------------------------------
    # 7. PROMEDIOS MOVILES Y ACUMULADOS
    # --------------------------------------------------------

    print("\n7. GENERANDO INDICADORES MOVILES...")

    def media_completa(columnas):

        valores = df[columnas]

        return valores.mean(axis=1).where(
            valores.notna().all(axis=1)
        ).astype("float32")

    def suma_completa(columnas):

        return df[columnas].sum(
            axis=1,
            min_count=len(columnas)
        ).astype("float32")

    def maximo_completo(columnas):

        valores = df[columnas]

        return valores.max(axis=1).where(
            valores.notna().all(axis=1)
        ).astype("float32")

    def minimo_completo(columnas):

        valores = df[columnas]

        return valores.min(axis=1).where(
            valores.notna().all(axis=1)
        ).astype("float32")

    df["casos_media_prev_4"] = media_completa(casos_lag_4)
    df["casos_suma_prev_4"] = suma_completa(casos_lag_4)

    df["casos_media_prev_8"] = media_completa(casos_lag_8)
    df["casos_suma_prev_8"] = suma_completa(casos_lag_8)

    tmean_lags = [f"tmean_lag_{i}" for i in range(1, 5)]
    humr_lags = [f"humr_lag_{i}" for i in range(1, 5)]
    ptot_lags = [f"ptot_lag_{i}" for i in range(1, 5)]
    tmax_lags = [f"tmax_lag_{i}" for i in range(1, 5)]
    tmin_lags = [f"tmin_lag_{i}" for i in range(1, 5)]

    df["temperatura_media_prev_4"] = media_completa(tmean_lags)
    df["humedad_media_prev_4"] = media_completa(humr_lags)
    df["precipitacion_acum_prev_4"] = suma_completa(ptot_lags)
    df["temperatura_maxima_prev_4"] = maximo_completo(tmax_lags)
    df["temperatura_minima_prev_4"] = minimo_completo(tmin_lags)

    # --------------------------------------------------------
    # 8. DIVISION TEMPORAL
    # --------------------------------------------------------

    print("\n8. DEFINIENDO PERIODOS DE MODELAMIENTO...")

    df["split_temporal"] = np.select(
        [
            df["ano"] <= 2022,
            df["ano"].between(2023, 2024)
        ],
        [
            "train",
            "validation"
        ],
        default="test"
    )

    # --------------------------------------------------------
    # 9. DATASET FINAL DE MODELAMIENTO
    # --------------------------------------------------------

    print("\n9. PREPARANDO DATASET FINAL...")

    columnas_tiempo = list(tiempo.keys())

    columnas_casos = (
        [f"casos_lag_{i}" for i in CASOS_LAGS]
        + [
            "casos_media_prev_4",
            "casos_suma_prev_4",
            "casos_media_prev_8",
            "casos_suma_prev_8"
        ]
    )

    columnas_clima = [
        f"{variable}_lag_{lag}"
        for variable in CLIMA
        for lag in CLIMA_LAGS
    ]

    columnas_clima += [
        "temperatura_media_prev_4",
        "humedad_media_prev_4",
        "precipitacion_acum_prev_4",
        "temperatura_maxima_prev_4",
        "temperatura_minima_prev_4"
    ]

    metadata = [
        "ubigeo",
        "departamento",
        "provincia",
        "distrito",
        "ano",
        "semana",
        "fecha_inicio",
        "clima_recuperado",
        "registro_minsa",
        TARGET
    ]

    columnas_finales = (
        metadata
        + columnas_tiempo
        + columnas_casos
        + columnas_clima
        + ["split_temporal"]
    )

    resultado = df[columnas_finales].copy()

    # --------------------------------------------------------
    # 10. REPORTES
    # --------------------------------------------------------

    print("\n10. GENERANDO REPORTES...")

    resumen = (
        resultado.groupby("split_temporal", observed=True)
        .agg(
            registros=(TARGET, "size"),
            distritos=("ubigeo", "nunique"),
            semanas_con_casos=(
                TARGET,
                lambda x: (x > 0).sum()
            ),
            casos_totales=(TARGET, "sum"),
            promedio_casos=(TARGET, "mean")
        )
        .reset_index()
    )

    resumen.to_csv(
        REPORT_DIR / "01_resumen_periodos.csv",
        index=False,
        encoding="utf-8-sig"
    )

    anual = (
        resultado.groupby("ano")
        .agg(
            registros=(TARGET, "size"),
            casos_totales=(TARGET, "sum"),
            semanas_con_casos=(
                TARGET,
                lambda x: (x > 0).sum()
            ),
            distritos=("ubigeo", "nunique")
        )
        .reset_index()
    )

    anual.to_csv(
        REPORT_DIR / "02_resumen_anual_modelamiento.csv",
        index=False,
        encoding="utf-8-sig"
    )

    rezagos = resultado[
        columnas_casos + columnas_clima
    ].isna().sum()

    rezagos = (
        rezagos.rename("valores_nulos")
        .rename_axis("variable")
        .reset_index()
    )

    rezagos.to_csv(
        REPORT_DIR / "03_revision_rezagos.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 11. EXPORTACION
    # --------------------------------------------------------

    print("\n11. EXPORTANDO DATASET...")

    resultado.to_csv(
        OUTPUT,
        index=False,
        encoding="utf-8-sig",
        compression={
            "method": "gzip",
            "compresslevel": 1
        }
    )

    # --------------------------------------------------------
    # 12. RESULTADO
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print("INGENIERIA DE CARACTERISTICAS COMPLETADA")
    print("=" * 65)

    print("REGISTROS:", f"{len(resultado):,}")
    print("DISTRITOS:", resultado["ubigeo"].nunique())
    print("VARIABLES FINALES:", len(resultado.columns))
    print(
        "CASOS REPORTADOS:",
        f"{resultado[TARGET].sum():,}"
    )

    print("\nDISTRIBUCION TEMPORAL:")
    print(resumen.to_string(index=False))

    print("\nDATASET GENERADO:")
    print(OUTPUT)

    print("\nREPORTES:")
    print(REPORT_DIR)

    print("\nNO SE MODIFICO EL DATASET MAESTRO.")
    print("NO SE MODIFICARON LOS ARCHIVOS ORIGINALES.")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\n" + "=" * 65)
        print("PROCESO CANCELADO")
        print("=" * 65)
        print("MOTIVO:")
        print(error)

        sys.exit(1)
