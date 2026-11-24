import json
import joblib
import numpy as np
import pandas as pd
from dengue_common import (
    load_dataset, build_base_features, add_target_calendar_features,
    prepare_model_matrix, epidemiological_year_week,
    MODELS_DIR, REPORTS_DIR
)

HORIZONS = [1, 2, 3, 4]


def main():
    df = load_dataset()
    latest = (
        df.sort_values(["ubigeo", "fecha_inicio"])
        .groupby("ubigeo", sort=False).tail(1).copy()
    )
    latest = latest.sort_values("ubigeo")
    print(f"Distritos a pronosticar: {latest['ubigeo'].nunique():,}")
    print(f"Ãšltima fecha disponible: {latest['fecha_inicio'].max().date()}")

    selection_path = MODELS_DIR / "modelo_seleccionado_por_horizonte.json"
    if not selection_path.exists():
        raise FileNotFoundError("No existe el archivo de selecciÃ³n. Ejecuta primero el script 21.")
    with open(selection_path, "r", encoding="utf-8") as f:
        selected_models = json.load(f)

    all_predictions = []
    grouped = df.groupby("ubigeo", sort=False)
    base_X = build_base_features(latest)

    for horizon in HORIZONS:
        print(f"Generando semana +{horizon}...")
        target_dates = latest["fecha_inicio"] + pd.to_timedelta(7 * horizon, unit="D")
        epi = [epidemiological_year_week(d) for d in target_dates]
        target_year = pd.Series([v[0] for v in epi], index=latest.index)
        target_week = pd.Series([v[1] for v in epi], index=latest.index)
        X = add_target_calendar_features(base_X, target_year, target_week)

        rf_path = MODELS_DIR / f"horizonte_{horizon}" / f"random_forest_h{horizon}.joblib"
        hgb_path = MODELS_DIR / f"horizonte_{horizon}" / f"hist_gradient_boosting_h{horizon}.joblib"
        rf_artifact = joblib.load(rf_path)
        hgb_artifact = joblib.load(hgb_path)

        X_rf = prepare_model_matrix(X, rf_artifact["feature_columns"], rf_artifact["medians"])
        X_hgb = prepare_model_matrix(X, hgb_artifact["feature_columns"], hgb_artifact["medians"])
        pred_rf = np.clip(rf_artifact["model"].predict(X_rf), 0, None)
        pred_hgb = np.clip(hgb_artifact["model"].predict(X_hgb), 0, None)

        pred_persistence = latest["casos_dengue_reportados"].to_numpy(dtype=float)
        seasonal_series = grouped["casos_dengue_reportados"].shift(52 - horizon)
        pred_seasonal = seasonal_series.loc[latest.index].to_numpy(dtype=float)
        pred_seasonal = np.where(np.isfinite(pred_seasonal), pred_seasonal, pred_persistence)

        chosen = selected_models[str(horizon)]
        candidates = {
            "baseline_persistencia": pred_persistence,
            "baseline_estacional": pred_seasonal,
            "random_forest": pred_rf,
            "hist_gradient_boosting": pred_hgb
        }
        final_prediction = candidates[chosen]

        result = pd.DataFrame({
            "ubigeo": latest["ubigeo"].to_numpy(),
            "departamento": latest["departamento"].to_numpy() if "departamento" in latest else "",
            "provincia": latest["provincia"].to_numpy() if "provincia" in latest else "",
            "distrito": latest["distrito"].to_numpy() if "distrito" in latest else "",
            "fecha_generacion": pd.Timestamp.now().date(),
            "fecha_origen": latest["fecha_inicio"].dt.date.to_numpy(),
            "fecha_objetivo": target_dates.dt.date.to_numpy(),
            "ano_objetivo": target_year.to_numpy(),
            "semana_objetivo": target_week.to_numpy(),
            "horizonte_semanas": horizon,
            "pred_baseline_persistencia": pred_persistence,
            "pred_baseline_estacional": pred_seasonal,
            "pred_random_forest": pred_rf,
            "pred_hist_gradient_boosting": pred_hgb,
            "modelo_seleccionado": chosen,
            "prediccion_final": np.clip(final_prediction, 0, None)
        })
        all_predictions.append(result)

    output_df = pd.concat(all_predictions, ignore_index=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORTS_DIR / "pronosticos_dengue_4_semanas.csv.gz"
    output_df.to_csv(output, index=False, compression="gzip")
    print("\nPRONOSTICOS GENERADOS")
    print(f"Registros: {len(output_df):,}")
    print(f"Distritos: {output_df['ubigeo'].nunique():,}")
    print(f"Archivo: {output}")
    print(output_df.groupby("horizonte_semanas")["prediccion_final"].agg(["count", "sum", "mean", "max"]).round(2))
    print("Nota: el pronÃ³stico parte de la Ãºltima semana que existe en el dataset; no equivale a un pronÃ³stico actualizado a la fecha actual si faltan datos de 2026.")


if __name__ == "__main__":
    main()