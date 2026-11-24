import json
import joblib
import numpy as np
import pandas as pd
from dengue_common import (
    load_dataset, build_base_features, add_target_calendar_features,
    prepare_model_matrix, epidemiological_year_week, observed_cases,
    MODELS_DIR, REPORTS_DIR, ID, TARGET, DATE
)

HORIZONS = (1, 2, 3, 4)


def main():
    df = load_dataset()
    latest = df.sort_values([ID, DATE]).groupby(ID, sort=False).tail(1).copy()
    latest = latest.sort_values(ID)
    print(f"Distritos a pronosticar: {latest[ID].nunique():,}")
    print(f"Última fecha observada: {latest[DATE].max().date()}")

    selection_path = MODELS_DIR / "modelo_seleccionado_por_horizonte.json"
    if not selection_path.exists():
        raise FileNotFoundError("No existe la selección de modelos. Ejecuta primero el script 21.")
    with open(selection_path, "r", encoding="utf-8") as f:
        selected = json.load(f)

    # Lags are calculated from the complete historical series, then only latest rows are used.
    all_features = build_base_features(df)
    latest_X_base = all_features.loc[latest.index].copy()
    observed = observed_cases(df)
    grouped_target = observed.groupby(df[ID], sort=False)
    # Seasonal baseline for horizon h is the observed value at t+h-52.
    outputs = []

    for horizon in HORIZONS:
        target_dates = latest[DATE] + pd.to_timedelta(7 * horizon, unit="D")
        epi = [epidemiological_year_week(d) for d in target_dates]
        target_year = pd.Series([x[0] for x in epi], index=latest.index)
        target_week = pd.Series([x[1] for x in epi], index=latest.index)
        X = add_target_calendar_features(latest_X_base, target_year, target_week)

        persistence_source = grouped_target.ffill()
        baseline_persistence = persistence_source.loc[latest.index].fillna(0).to_numpy(dtype=float)
        seasonal_source = grouped_target.shift(52 - horizon)
        baseline_seasonal = seasonal_source.loc[latest.index].to_numpy(dtype=float)
        baseline_seasonal = np.where(np.isfinite(baseline_seasonal), baseline_seasonal, baseline_persistence)

        rf_artifact = joblib.load(MODELS_DIR / f"horizonte_{horizon}" / f"random_forest_h{horizon}.joblib")
        hgb_artifact = joblib.load(MODELS_DIR / f"horizonte_{horizon}" / f"hist_gradient_boosting_h{horizon}.joblib")
        X_rf = prepare_model_matrix(X, rf_artifact["feature_columns"], rf_artifact["medians"])
        X_hgb = prepare_model_matrix(X, hgb_artifact["feature_columns"], hgb_artifact["medians"])
        pred_rf = np.clip(rf_artifact["model"].predict(X_rf), 0, None)
        pred_hgb = np.clip(hgb_artifact["model"].predict(X_hgb), 0, None)

        chosen = selected[str(horizon)]
        candidates = {
            "baseline_persistencia": baseline_persistence,
            "baseline_estacional": baseline_seasonal,
            "random_forest": pred_rf,
            "hist_gradient_boosting": pred_hgb
        }
        final_pred = np.clip(candidates[chosen], 0, None)
        out = pd.DataFrame({
            "ubigeo": latest[ID].astype(str).to_numpy(),
            "departamento": latest["departamento"].to_numpy() if "departamento" in latest else "",
            "provincia": latest["provincia"].to_numpy() if "provincia" in latest else "",
            "distrito": latest["distrito"].to_numpy() if "distrito" in latest else "",
            "fecha_generacion": pd.Timestamp.now().date(),
            "fecha_origen": latest[DATE].dt.date.to_numpy(),
            "fecha_objetivo": target_dates.dt.date.to_numpy(),
            "ano_objetivo": target_year.to_numpy(),
            "semana_objetivo": target_week.to_numpy(),
            "horizonte_semanas": horizon,
            "pred_baseline_persistencia": baseline_persistence,
            "pred_baseline_estacional": baseline_seasonal,
            "pred_random_forest": pred_rf,
            "pred_hist_gradient_boosting": pred_hgb,
            "modelo_seleccionado": chosen,
            "prediccion_final": final_pred
        })
        outputs.append(out)
        print(f"Horizonte +{horizon}: modelo elegido = {chosen}")

    result = pd.concat(outputs, ignore_index=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / "pronosticos_dengue_4_semanas.csv.gz"
    result.to_csv(output, index=False, compression="gzip")
    print("\nPRONOSTICOS GENERADOS")
    print(f"Registros: {len(result):,}")
    print(f"Distritos: {result[ID].nunique():,}")
    print(f"Archivo: {output}")
    print(result.groupby("horizonte_semanas")["prediccion_final"].agg(["count", "sum", "mean", "max"]).round(2))
    print("ADVERTENCIA: el pronóstico parte de la última semana disponible en el dataset. Las variables climáticas futuras se aproximan con los últimos valores observados; no se ha añadido un nuevo dataset climático.")


if __name__ == "__main__":
    main()
