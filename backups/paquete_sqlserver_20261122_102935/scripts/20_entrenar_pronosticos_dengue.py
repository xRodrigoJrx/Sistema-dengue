import os
import gc
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from dengue_common import (
    load_dataset, build_base_features, add_target_calendar_features,
    create_horizon_targets, MODELS_DIR, REPORTS_DIR
)

HORIZONS = [1, 2, 3, 4]
MAX_TRAIN_ROWS = int(os.getenv("DENGUE_MAX_TRAIN_ROWS", "150000"))


def fill_matrices(X_train, X_validation, X_test):
    X_train = X_train.replace([np.inf, -np.inf], np.nan)
    medians = X_train.median().replace([np.inf, -np.inf], np.nan).fillna(0)
    X_train = X_train.fillna(medians).astype("float32")
    X_validation = X_validation.replace([np.inf, -np.inf], np.nan).fillna(medians).astype("float32")
    X_test = X_test.replace([np.inf, -np.inf], np.nan).fillna(medians).astype("float32")
    return X_train, X_validation, X_test, medians


def train_one_horizon(df, base_X, horizon):
    print("\n" + "=" * 65)
    print(f"ENTRENANDO HORIZONTE +{horizon} SEMANAS")
    print("=" * 65)

    target = create_horizon_targets(df, horizon)
    X = add_target_calendar_features(base_X, target["year"], target["week"])
    y = target["y"]
    split = target["split"]

    valid = y.notna() & split.notna() & target["year"].notna() & target["week"].notna()
    train_idx = df.index[valid & split.eq("train")].to_numpy()
    val_idx = df.index[valid & split.eq("validation")].to_numpy()
    test_idx = df.index[valid & split.eq("test")].to_numpy()

    if min(len(train_idx), len(val_idx), len(test_idx)) == 0:
        raise ValueError(f"No hay suficientes datos para el horizonte {horizon}.")

    if len(train_idx) > MAX_TRAIN_ROWS:
        rng = np.random.default_rng(42)
        train_idx = np.sort(rng.choice(train_idx, size=MAX_TRAIN_ROWS, replace=False))

    feature_columns = list(X.columns)
    X_train, X_val, X_test, medians = fill_matrices(
        X.loc[train_idx], X.loc[val_idx], X.loc[test_idx]
    )
    y_train = y.loc[train_idx].astype("float32")

    print(f"Entrenamiento utilizado: {len(train_idx):,}")
    print(f"ValidaciÃ³n: {len(val_idx):,}")
    print(f"Prueba: {len(test_idx):,}")
    print(f"Variables predictoras: {len(feature_columns)}")

    print("Entrenando Random Forest...")
    rf = RandomForestRegressor(
        n_estimators=80,
        max_depth=18,
        min_samples_leaf=3,
        max_features=0.8,
        n_jobs=-1,
        random_state=42
    )
    rf.fit(X_train, y_train)

    print("Entrenando HistGradientBoosting...")
    hgb = HistGradientBoostingRegressor(
        max_iter=100,
        learning_rate=0.07,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=42
    )
    hgb.fit(X_train, y_train)

    model_dir = MODELS_DIR / f"horizonte_{horizon}"
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, model in [("random_forest", rf), ("hist_gradient_boosting", hgb)]:
        artifact = {
            "model": model,
            "feature_columns": feature_columns,
            "medians": medians.to_dict(),
            "horizon": horizon,
            "model_name": name,
            "target": "casos_dengue_reportados"
        }
        path = model_dir / f"{name}_h{horizon}.joblib"
        joblib.dump(artifact, path, compress=3)
        print(f"Guardado: {path}")

    def save_predictions(indexes, X_part, period):
        y_real = y.loc[indexes].to_numpy(dtype=float)
        seasonal = target["baseline_seasonal"].loc[indexes].to_numpy(dtype=float)
        persistence = target["baseline_persistence"].loc[indexes].to_numpy(dtype=float)
        seasonal = np.where(np.isfinite(seasonal), seasonal, persistence)
        result = pd.DataFrame({
            "ubigeo": df.loc[indexes, "ubigeo"].to_numpy(),
            "fecha_origen": df.loc[indexes, "fecha_inicio"].dt.strftime("%Y-%m-%d").to_numpy(),
            "fecha_objetivo": target["date"].loc[indexes].dt.strftime("%Y-%m-%d").to_numpy(),
            "ano_objetivo": target["year"].loc[indexes].to_numpy(),
            "semana_objetivo": target["week"].loc[indexes].to_numpy(),
            "casos_reales": y_real,
            "pred_baseline_persistencia": persistence,
            "pred_baseline_estacional": seasonal,
            "pred_random_forest": np.clip(rf.predict(X_part), 0, None),
            "pred_hist_gradient_boosting": np.clip(hgb.predict(X_part), 0, None),
            "horizonte_semanas": horizon,
            "periodo": period
        })
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        output = REPORTS_DIR / f"predicciones_h{horizon}_{period}.csv.gz"
        result.to_csv(output, index=False, compression="gzip")
        print(f"Predicciones guardadas: {output}")

    save_predictions(val_idx, X_val, "validation")
    save_predictions(test_idx, X_test, "test")

    del X, X_train, X_val, X_test, rf, hgb
    gc.collect()


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("PRONOSTICOS DE DENGUE: HORIZONTES DE 1 A 4 SEMANAS")
    df = load_dataset()
    base_X = build_base_features(df)
    print(f"Variables base: {base_X.shape[1]}")
    for horizon in HORIZONS:
        train_one_horizon(df, base_X, horizon)
    print("\nENTRENAMIENTO DE LOS CUATRO HORIZONTES COMPLETADO.")
    print("No se modificÃ³ el dataset maestro ni los archivos originales.")


if __name__ == "__main__":
    main()