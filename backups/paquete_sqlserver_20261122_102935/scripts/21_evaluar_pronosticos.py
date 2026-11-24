import json
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from dengue_common import MODELS_DIR, REPORTS_DIR

HORIZONS = [1, 2, 3, 4]
MODEL_COLUMNS = {
    "baseline_persistencia": "pred_baseline_persistencia",
    "baseline_estacional": "pred_baseline_estacional",
    "random_forest": "pred_random_forest",
    "hist_gradient_boosting": "pred_hist_gradient_boosting"
}


def calculate_metrics(real, predicted):
    real = np.asarray(real, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    valid = np.isfinite(real) & np.isfinite(predicted)
    real, predicted = real[valid], predicted[valid]
    if len(real) == 0:
        return None
    positive = real > 0
    total_real = real.sum()
    return {
        "registros_evaluados": int(len(real)),
        "MAE": float(mean_absolute_error(real, predicted)),
        "RMSE": float(np.sqrt(mean_squared_error(real, predicted))),
        "R2": float(r2_score(real, predicted)) if len(real) > 1 else None,
        "MAE_positivos": float(mean_absolute_error(real[positive], predicted[positive])) if positive.any() else None,
        "casos_reales": float(total_real),
        "casos_predichos": float(predicted.sum()),
        "error_total_pct": float((predicted.sum() - total_real) / total_real * 100) if total_real > 0 else None
    }


def main():
    rows = []
    selected = {}
    for horizon in HORIZONS:
        print(f"Evaluando horizonte +{horizon}...")
        for period in ["validation", "test"]:
            path = REPORTS_DIR / f"predicciones_h{horizon}_{period}.csv.gz"
            if not path.exists():
                raise FileNotFoundError(f"No existe {path}. Ejecuta primero el script 20.")
            df = pd.read_csv(path, compression="gzip")
            for model_name, column in MODEL_COLUMNS.items():
                metrics = calculate_metrics(df["casos_reales"], df[column])
                if metrics is not None:
                    rows.append({"horizonte": horizon, "periodo": period, "modelo": model_name, **metrics})

        validation_rows = [r for r in rows if r["horizonte"] == horizon and r["periodo"] == "validation"]
        winner = min(validation_rows, key=lambda r: r["MAE"])
        selected[str(horizon)] = winner["modelo"]
        print(f"Mejor modelo segÃºn MAE de validaciÃ³n: {winner['modelo']}")

    report = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "metricas_horizontes.csv"
    report.to_csv(report_path, index=False)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    selection_path = MODELS_DIR / "modelo_seleccionado_por_horizonte.json"
    with open(selection_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=4)

    print("\nMETRICAS:")
    print(report[["horizonte", "periodo", "modelo", "MAE", "RMSE", "R2", "MAE_positivos", "error_total_pct"]].round(4).to_string(index=False))
    print("\nMODELOS SELECCIONADOS:")
    print(json.dumps(selected, indent=4, ensure_ascii=False))
    print(f"\nReporte: {report_path}")
    print(f"SelecciÃ³n: {selection_path}")
    print("La selecciÃ³n se hizo exclusivamente con VALIDATION; TEST queda como evaluaciÃ³n final.")


if __name__ == "__main__":
    main()