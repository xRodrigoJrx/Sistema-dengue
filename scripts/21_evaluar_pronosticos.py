import json
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from dengue_common import MODELS_DIR, REPORTS_DIR

HORIZONS = (1, 2, 3, 4)
MODEL_COLUMNS = {
    "baseline_persistencia": "pred_baseline_persistencia",
    "baseline_estacional": "pred_baseline_estacional",
    "random_forest": "pred_random_forest",
    "hist_gradient_boosting": "pred_hist_gradient_boosting"
}


def metrics(real, predicted):
    real = np.asarray(real, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    valid = np.isfinite(real) & np.isfinite(predicted)
    real, predicted = real[valid], np.clip(predicted[valid], 0, None)
    if not len(real):
        return None
    positive = real > 0
    total = float(real.sum())
    return {
        "registros_evaluados": int(len(real)),
        "MAE": float(mean_absolute_error(real, predicted)),
        "RMSE": float(np.sqrt(mean_squared_error(real, predicted))),
        "R2": float(r2_score(real, predicted)) if len(real) > 1 else None,
        "MAE_positivos": float(mean_absolute_error(real[positive], predicted[positive])) if positive.any() else None,
        "casos_reales": total,
        "casos_predichos": float(predicted.sum()),
        "error_total_pct": float((predicted.sum() - total) / total * 100) if total else None
    }


def main():
    rows = []
    selected = {}
    for horizon in HORIZONS:
        for period in ("validation", "test"):
            path = REPORTS_DIR / f"predicciones_h{horizon}_{period}.csv.gz"
            if not path.exists():
                raise FileNotFoundError(f"No existe {path}. Ejecuta primero el script 20.")
            data = pd.read_csv(path, compression="gzip")
            for model, column in MODEL_COLUMNS.items():
                result = metrics(data["casos_reales"], data[column])
                if result:
                    rows.append({"horizonte": horizon, "periodo": period, "modelo": model, **result})

        val = [r for r in rows if r["horizonte"] == horizon and r["periodo"] == "validation"]
        selected[str(horizon)] = min(val, key=lambda r: r["MAE"])["modelo"]

    report = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "metricas_horizontes.csv"
    report.to_csv(report_path, index=False)
    selection_path = MODELS_DIR / "modelo_seleccionado_por_horizonte.json"
    with open(selection_path, "w", encoding="utf-8") as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)

    print("\nMETRICAS DE VALIDACION Y TEST:")
    cols = ["horizonte", "periodo", "modelo", "MAE", "RMSE", "R2", "MAE_positivos", "error_total_pct"]
    print(report[cols].round(4).to_string(index=False))
    print("\nMODELO ELEGIDO POR HORIZONTE (MAE de VALIDATION):")
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    print(f"\nReporte: {report_path}")
    print(f"Selección: {selection_path}")
    print("TEST se conserva como evaluación final; no se usa para elegir el modelo.")


if __name__ == "__main__":
    main()
