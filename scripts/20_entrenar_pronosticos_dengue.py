import gc
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from dengue_common import (
    load_dataset, build_base_features, add_target_calendar_features,
    create_horizon_targets, MODELS_DIR, REPORTS_DIR
)

HORIZONS = (1, 2, 3, 4)
MAX_TRAIN_ROWS = int(os.getenv("DENGUE_MAX_TRAIN_ROWS", "100000"))
RANDOM_STATE = 42


def _fill_matrices(X_train, X_val, X_test):
    X_train = X_train.replace([np.inf, -np.inf], np.nan)
    medians = X_train.median().replace([np.inf, -np.inf], np.nan).fillna(0)
    return (
        X_train.fillna(medians).astype("float32"),
        X_val.replace([np.inf, -np.inf], np.nan).fillna(medians).astype("float32"),
        X_test.replace([np.inf, -np.inf], np.nan).fillna(medians).astype("float32"),
        medians
    )


def train_horizon(df, base_X, horizon):
    print("\n" + "=" * 65)
    print(f"ENTRENANDO HORIZONTE +{horizon} SEMANAS")
    print("=" * 65)

    targets = create_horizon_targets(df, horizon)
    X = add_target_calendar_features(base_X, targets["year"], targets["week"])
    y = targets["y"]
    target_split = targets["split"]
    valid = y.notna() & target_split.notna() & targets["year"].notna() & targets["week"].notna()

    train_idx = df.index[valid & target_split.eq("train")].to_numpy()
    val_idx = df.index[valid & target_split.eq("validation")].to_numpy()
    test_idx = df.index[valid & target_split.eq("test")].to_numpy()
    if not len(train_idx) or not len(val_idx) or not len(test_idx):
        raise ValueError(f"El horizonte {horizon} no tiene suficientes registros en train/validation/test.")

    if len(train_idx) > MAX_TRAIN_ROWS:
        rng = np.random.default_rng(RANDOM_STATE + horizon)
        train_idx = np.sort(rng.choice(train_idx, MAX_TRAIN_ROWS, replace=False))

    feature_columns = list(X.columns)
    X_train, X_val, X_test, medians = _fill_matrices(
        X.loc[train_idx], X.loc[val_idx], X.loc[test_idx]
    )
    y_train = y.loc[train_idx].astype("float32")

    print(f"Entrenamiento usado: {len(train_idx):,} / {int((valid & target_split.eq('train')).sum()):,}")
    print(f"Validación: {len(val_idx):,} | Prueba: {len(test_idx):,}")
    print(f"Variables predictoras: {len(feature_columns)}")

    models = {
        "random_forest": RandomForestRegressor(
            n_estimators=45, max_depth=15, min_samples_leaf=4,
            max_features=0.8, n_jobs=-1, random_state=RANDOM_STATE
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=75, learning_rate=0.07, max_leaf_nodes=25,
            l2_regularization=1.0, early_stopping=True,
            validation_fraction=0.1, random_state=RANDOM_STATE
        )
    }

    model_dir = MODELS_DIR / f"horizonte_{horizon}"
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, model in models.items():
        print(f"Entrenando {name}...")
        model.fit(X_train, y_train)
        artifact = {
            "model": model,
            "feature_columns": feature_columns,
            "medians": medians.to_dict(),
            "horizon": horizon,
            "model_name": name,
            "target": "casos_dengue_reportados",
            "max_train_rows": MAX_TRAIN_ROWS
        }
        path = model_dir / f"{name}_h{horizon}.joblib"
        joblib.dump(artifact, path, compress=3)
        print(f"Guardado: {path}")

    def save_period(indexes, X_part, period):
        out = pd.DataFrame({
            "ubigeo": df.loc[indexes, "ubigeo"].astype(str).to_numpy(),
            "fecha_origen": df.loc[indexes, "fecha_inicio"].dt.strftime("%Y-%m-%d").to_numpy(),
            "fecha_objetivo": targets["date"].loc[indexes].dt.strftime("%Y-%m-%d").to_numpy(),
            "ano_objetivo": targets["year"].loc[indexes].astype(int).to_numpy(),
            "semana_objetivo": targets["week"].loc[indexes].astype(int).to_numpy(),
            "casos_reales": y.loc[indexes].to_numpy(dtype=float),
            "pred_baseline_persistencia": targets["baseline_persistence"].loc[indexes].to_numpy(dtype=float),
            "pred_baseline_estacional": targets["baseline_seasonal"].loc[indexes].to_numpy(dtype=float),
            "pred_random_forest": np.clip(models["random_forest"].predict(X_part), 0, None),
            "pred_hist_gradient_boosting": np.clip(models["hist_gradient_boosting"].predict(X_part), 0, None),
            "horizonte_semanas": horizon,
            "periodo": period
        })
        out["pred_baseline_estacional"] = out["pred_baseline_estacional"].fillna(out["pred_baseline_persistencia"])
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"predicciones_h{horizon}_{period}.csv.gz"
        out.to_csv(path, index=False, compression="gzip")
        print(f"Predicciones {period}: {path}")

    save_period(val_idx, X_val, "validation")
    save_period(test_idx, X_test, "test")
    del X, X_train, X_val, X_test, models
    gc.collect()


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    print("PRONOSTICOS DE DENGUE | HORIZONTES 1 A 4 SEMANAS")
    print(f"Muestra máxima de entrenamiento por horizonte: {MAX_TRAIN_ROWS:,}")
    df = load_dataset()
    base_X = build_base_features(df)
    print(f"Variables base generadas: {base_X.shape[1]}")
    for horizon in HORIZONS:
        train_horizon(df, base_X, horizon)
    print("\nENTRENAMIENTO COMPLETADO.")
    print("No se modificaron los datasets originales ni el dataset maestro.")


if __name__ == "__main__":
    main()
