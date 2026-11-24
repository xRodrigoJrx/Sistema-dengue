
from pathlib import Path
import sys
import warnings
import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)

warnings.filterwarnings("ignore")

# ============================================================
# CONFIGURACION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

INPUT = (
    ROOT / "data/processed/modelamiento/"
    "dataset_modelamiento_dengue_2000_2025.csv.gz"
)

REPORT_DIR = ROOT / "reports/modelamiento"
MODEL_DIR = ROOT / "models/modelamiento"

REPORT_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

TARGET = "casos_dengue_reportados"

MAX_TRAIN = 300_000
CHUNK_SIZE = 200_000
SEED = 42

CASE_LAGS = [1, 2, 3, 4, 5, 6, 7, 8, 12, 52]

CLIMATE = ["tmean", "tmax", "tmin", "humr", "ptot"]
CLIMATE_LAGS = [1, 2, 3, 4, 8]

TEMP_FEATURES = [
    "ano", "semana", "mes", "trimestre",
    "semana_sin", "semana_cos",
    "mes_sin", "mes_cos", "tendencia_anual"
]

CASE_FEATURES = [
    f"casos_lag_{i}" for i in CASE_LAGS
] + [
    "casos_media_prev_4",
    "casos_suma_prev_4",
    "casos_media_prev_8",
    "casos_suma_prev_8"
]

CLIMATE_FEATURES = [
    f"{v}_lag_{i}"
    for v in CLIMATE
    for i in CLIMATE_LAGS
] + [
    "temperatura_media_prev_4",
    "humedad_media_prev_4",
    "precipitacion_acum_prev_4",
    "temperatura_maxima_prev_4",
    "temperatura_minima_prev_4"
]

FEATURES = TEMP_FEATURES + CASE_FEATURES + CLIMATE_FEATURES

METADATA = [
    "ubigeo", "departamento", "ano",
    "semana", "fecha_inicio"
]

USECOLS = list(dict.fromkeys(
    METADATA + FEATURES + [TARGET, "split_temporal"]
))


# ============================================================
# METRICAS
# ============================================================

def calcular_metricas(real, pred):

    real = np.asarray(real, dtype=float)
    pred = np.maximum(np.asarray(pred, dtype=float), 0)

    positivos = real > 0

    return {
        "MAE": mean_absolute_error(real, pred),
        "RMSE": np.sqrt(mean_squared_error(real, pred)),
        "R2": r2_score(real, pred),
        "MAE_positivos": (
            mean_absolute_error(real[positivos], pred[positivos])
            if positivos.any() else np.nan
        ),
        "casos_reales": real.sum(),
        "casos_predichos": pred.sum(),
        "error_total_pct": (
            (pred.sum() - real.sum()) / real.sum() * 100
            if real.sum() > 0 else np.nan
        )
    }


# ============================================================
# MATRIZ DE VARIABLES
# ============================================================

def construir_matriz(part, departamentos):

    base = part[FEATURES].copy()

    base["departamento"] = pd.Categorical(
        part["departamento"].fillna("DESCONOCIDO"),
        categories=departamentos
    )

    X = pd.get_dummies(
        base,
        columns=["departamento"],
        dtype=np.float32
    )

    return X.astype(np.float32)


# ============================================================
# PROCESO PRINCIPAL
# ============================================================

def main():

    print("=" * 65)
    print("ENTRENAMIENTO DE MODELOS PREDICTIVOS DE DENGUE")
    print("PERIODO 2000-2025")
    print("=" * 65)

    if not INPUT.exists():
        raise FileNotFoundError(
            f"No existe el dataset: {INPUT}"
        )

    # --------------------------------------------------------
    # 1. CARGA POR BLOQUES
    # --------------------------------------------------------

    print("\n1. CARGANDO DATOS POR BLOQUES...")

    train_parts = []
    val_parts = []
    test_parts = []

    for i, chunk in enumerate(
        pd.read_csv(
            INPUT,
            compression="gzip",
            usecols=USECOLS,
            dtype={
                "ubigeo": "string",
                "departamento": "string"
            },
            chunksize=CHUNK_SIZE
        )
    ):

        train_chunk = chunk[
            chunk["split_temporal"] == "train"
        ]

        if not train_chunk.empty:
            train_parts.append(
                train_chunk.sample(
                    frac=0.20,
                    random_state=SEED + i
                )
            )

        val_chunk = chunk[
            chunk["split_temporal"] == "validation"
        ]

        if not val_chunk.empty:
            val_parts.append(val_chunk)

        test_chunk = chunk[
            chunk["split_temporal"] == "test"
        ]

        if not test_chunk.empty:
            test_parts.append(test_chunk)

        print(f"Bloque {i + 1}: {len(chunk):,} registros")

    train = pd.concat(train_parts, ignore_index=True)
    validation = pd.concat(val_parts, ignore_index=True)
    test = pd.concat(test_parts, ignore_index=True)

    if len(train) > MAX_TRAIN:
        train = train.sample(
            n=MAX_TRAIN,
            random_state=SEED
        )

    print("\nREGISTROS CARGADOS:")
    print("ENTRENAMIENTO:", f"{len(train):,}")
    print("VALIDACION:", f"{len(validation):,}")
    print("PRUEBA:", f"{len(test):,}")

    # --------------------------------------------------------
    # 2. VALIDACION DE VARIABLES
    # --------------------------------------------------------

    print("\n2. VALIDANDO VARIABLES PREDICTORAS...")

    def limpiar(part, nombre):

        part = part.copy()

        mascara = (
            part[FEATURES].notna().all(axis=1)
            & part[TARGET].notna()
        )

        eliminados = int((~mascara).sum())

        if nombre != "ENTRENAMIENTO" and eliminados > 0:
            raise ValueError(
                f"{nombre}: existen {eliminados} registros "
                "con variables incompletas."
            )

        part = part.loc[mascara].copy()

        if not np.isfinite(
            part[FEATURES].to_numpy(dtype=np.float32)
        ).all():

            raise ValueError(
                f"{nombre}: existen valores infinitos."
            )

        return part, eliminados

    train, eliminados_train = limpiar(
        train, "ENTRENAMIENTO"
    )

    validation, eliminados_val = limpiar(
        validation, "VALIDACION"
    )

    test, eliminados_test = limpiar(
        test, "PRUEBA"
    )

    print("FILAS INCOMPLETAS ELIMINADAS:")
    print("ENTRENAMIENTO:", eliminados_train)
    print("VALIDACION:", eliminados_val)
    print("PRUEBA:", eliminados_test)

    # --------------------------------------------------------
    # 3. CODIFICACION GEOGRAFICA
    # --------------------------------------------------------

    print("\n3. PREPARANDO VARIABLES GEOGRAFICAS...")

    departamentos = sorted(
        set(train["departamento"].dropna())
        | set(validation["departamento"].dropna())
        | set(test["departamento"].dropna())
        | {"DESCONOCIDO"}
    )

    X_train = construir_matriz(train, departamentos)
    X_val = construir_matriz(validation, departamentos)
    X_test = construir_matriz(test, departamentos)

    X_val = X_val.reindex(
        columns=X_train.columns,
        fill_value=0
    )

    X_test = X_test.reindex(
        columns=X_train.columns,
        fill_value=0
    )

    y_train = np.log1p(
        train[TARGET].to_numpy(dtype=np.float32)
    )

    print("VARIABLES DEL MODELO:", X_train.shape[1])

    # --------------------------------------------------------
    # 4. MODELOS DE REFERENCIA
    # --------------------------------------------------------

    print("\n4. PREPARANDO MODELOS BASELINE...")

    modelos = {}

    # --------------------------------------------------------
    # 5. RANDOM FOREST
    # --------------------------------------------------------

    print("\n5. ENTRENANDO RANDOM FOREST...")

    rf = RandomForestRegressor(
        n_estimators=60,
        max_depth=16,
        min_samples_leaf=10,
        max_features=0.8,
        n_jobs=-1,
        random_state=SEED
    )

    rf.fit(X_train, y_train)

    modelos["RandomForest"] = rf

    joblib.dump(
        rf,
        MODEL_DIR / "random_forest_dengue.joblib",
        compress=1
    )

    print("RANDOM FOREST ENTRENADO Y GUARDADO.")

    # --------------------------------------------------------
    # 6. XGBOOST O ALTERNATIVA
    # --------------------------------------------------------

    print("\n6. ENTRENANDO SEGUNDO MODELO...")

    try:

        from xgboost import XGBRegressor

        segundo_modelo = XGBRegressor(
            n_estimators=250,
            max_depth=7,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=5,
            reg_lambda=2,
            objective="reg:squarederror",
            tree_method="hist",
            n_jobs=-1,
            random_state=SEED,
            verbosity=0
        )

        nombre_segundo = "XGBoost"

    except ImportError:

        from sklearn.ensemble import HistGradientBoostingRegressor

        segundo_modelo = HistGradientBoostingRegressor(
            max_iter=100,
            learning_rate=0.08,
            max_leaf_nodes=31,
            min_samples_leaf=50,
            l2_regularization=1,
            early_stopping=False,
            random_state=SEED
        )

        nombre_segundo = "HistGradientBoosting"

        print("XGBOOST NO INSTALADO.")
        print("SE UTILIZARA HIST GRADIENT BOOSTING.")

    segundo_modelo.fit(X_train, y_train)

    modelos[nombre_segundo] = segundo_modelo

    joblib.dump(
        segundo_modelo,
        MODEL_DIR / f"{nombre_segundo.lower()}_dengue.joblib",
        compress=1
    )

    print(nombre_segundo, "ENTRENADO Y GUARDADO.")

    # --------------------------------------------------------
    # 7. PREDICCIONES Y EVALUACION
    # --------------------------------------------------------

    print("\n7. EVALUANDO MODELOS...")

    resultados = []
    predicciones = {}

    conjuntos = {
        "validation": (validation, X_val),
        "test": (test, X_test)
    }

    for nombre_split, (part, X) in conjuntos.items():

        real = part[TARGET].to_numpy(dtype=float)

        predicciones[nombre_split] = pd.DataFrame({
            "ubigeo": part["ubigeo"].astype(str).values,
            "ano": part["ano"].values,
            "semana": part["semana"].values,
            "fecha_inicio": part["fecha_inicio"].values,
            "casos_reales": real
        })

        # Baseline: semana anterior
        baseline_1 = part["casos_lag_1"].to_numpy(dtype=float)

        # Baseline: misma semana del año anterior
        baseline_52 = part["casos_lag_52"].to_numpy(dtype=float)

        baselines = {
            "Baseline_Lag1": baseline_1,
            "Baseline_Lag52": baseline_52
        }

        for nombre, pred in baselines.items():

            resultados.append({
                "modelo": nombre,
                "periodo": nombre_split,
                **calcular_metricas(real, pred)
            })

            predicciones[nombre_split][
                f"pred_{nombre}"
            ] = np.maximum(pred, 0)

        # Modelos entrenados
        for nombre, modelo in modelos.items():

            pred_log = modelo.predict(X)

            pred = np.maximum(
                np.expm1(pred_log),
                0
            )

            resultados.append({
                "modelo": nombre,
                "periodo": nombre_split,
                **calcular_metricas(real, pred)
            })

            predicciones[nombre_split][
                f"pred_{nombre}"
            ] = pred

        print("\nPERIODO:", nombre_split.upper())

        print(
            pd.DataFrame([
                r for r in resultados
                if r["periodo"] == nombre_split
            ])[
                ["modelo", "MAE", "RMSE", "R2"]
            ].round(4).to_string(index=False)
        )

    # --------------------------------------------------------
    # 8. EXPORTACION DE RESULTADOS
    # --------------------------------------------------------

    print("\n8. GUARDANDO RESULTADOS...")

    metricas = pd.DataFrame(resultados)

    metricas.to_csv(
        REPORT_DIR / "04_metricas_modelos.csv",
        index=False,
        encoding="utf-8-sig"
    )

    predicciones["validation"].to_csv(
        REPORT_DIR / "05_predicciones_validacion.csv.gz",
        index=False,
        compression="gzip",
        encoding="utf-8-sig"
    )

    predicciones["test"].to_csv(
        REPORT_DIR / "06_predicciones_prueba_2025.csv.gz",
        index=False,
        compression="gzip",
        encoding="utf-8-sig"
    )

    # --------------------------------------------------------
    # 9. RESULTADO FINAL
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print("ENTRENAMIENTO Y EVALUACION COMPLETADOS")
    print("=" * 65)

    print("\nMODELOS ENTRENADOS:")
    for nombre in modelos:
        print("-", nombre)

    print("\nMETRICAS COMPLETAS:")
    print(
        metricas.round(4).to_string(index=False)
    )

    print("\nREPORTES:")
    print(REPORT_DIR)

    print("\nMODELOS GUARDADOS:")
    print(MODEL_DIR)

    print("\nNO SE MODIFICO EL DATASET MAESTRO.")
    print("NO SE MODIFICARON LOS ARCHIVOS ORIGINALES.")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\n" + "=" * 65)
        print("ENTRENAMIENTO CANCELADO")
        print("=" * 65)
        print("MOTIVO:")
        print(error)

        sys.exit(1)
