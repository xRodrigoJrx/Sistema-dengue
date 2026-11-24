import pandas as pd
from sqlalchemy import text
from dengue_common import ROOT, DATASET, REPORTS_DIR, get_mysql_engine

FORECAST_FILE = REPORTS_DIR / "pronosticos_dengue_4_semanas.csv.gz"
METRICS_FILE = REPORTS_DIR / "metricas_horizontes.csv"


def load_dimension(conn, usecols):
    geo_cols = [c for c in ["ubigeo", "departamento", "provincia", "distrito"] if c in usecols]
    if "ubigeo" not in geo_cols:
        raise ValueError("No existe la columna ubigeo en el dataset.")
    parts = []
    for chunk in pd.read_csv(DATASET, compression="gzip", usecols=geo_cols, dtype={"ubigeo": "string"}, chunksize=200000):
        chunk["ubigeo"] = chunk["ubigeo"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
        parts.append(chunk.dropna(subset=["ubigeo"]).drop_duplicates("ubigeo"))
    dim = pd.concat(parts, ignore_index=True).drop_duplicates("ubigeo")
    for col in ["departamento", "provincia", "distrito"]:
        if col not in dim.columns:
            dim[col] = None
    dim = dim[["ubigeo", "departamento", "provincia", "distrito"]]
    dim.to_sql("dim_distrito", conn, if_exists="append", index=False, chunksize=1000)
    print(f"Distritos cargados: {len(dim):,}")


def load_historical_cases(conn, usecols):
    required = ["ubigeo", "ano", "semana", "fecha_inicio", "casos_dengue_reportados"]
    missing = [c for c in required if c not in usecols]
    if missing:
        raise ValueError(f"Faltan columnas para el histÃ³rico: {missing}")
    selected = required + (["poblacion_proyectada"] if "poblacion_proyectada" in usecols else [])
    total = 0
    for chunk in pd.read_csv(DATASET, compression="gzip", usecols=selected, dtype={"ubigeo": "string"}, chunksize=10000):
        chunk["ubigeo"] = chunk["ubigeo"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
        chunk["ano"] = pd.to_numeric(chunk["ano"], errors="coerce").astype("int16")
        chunk["semana"] = pd.to_numeric(chunk["semana"], errors="coerce").astype("int8")
        chunk["fecha_inicio"] = pd.to_datetime(chunk["fecha_inicio"], errors="coerce").dt.date
        chunk["casos_dengue_reportados"] = pd.to_numeric(chunk["casos_dengue_reportados"], errors="coerce").fillna(0).astype("int64")
        chunk = chunk.rename(columns={"casos_dengue_reportados": "casos_reportados"})
        if "poblacion_proyectada" in chunk.columns:
            chunk["poblacion_proyectada"] = pd.to_numeric(chunk["poblacion_proyectada"], errors="coerce")
        chunk.to_sql("fact_casos_semanales", conn, if_exists="append", index=False, chunksize=5000)
        total += len(chunk)
        print(f"HistÃ³rico importado: {total:,}")
    print(f"Total histÃ³rico: {total:,}")


def load_forecasts(conn):
    if not FORECAST_FILE.exists():
        raise FileNotFoundError(f"No existe {FORECAST_FILE}. Ejecuta primero el script 22.")
    df = pd.read_csv(FORECAST_FILE, compression="gzip")
    cols = [
        "ubigeo", "fecha_generacion", "fecha_origen", "fecha_objetivo",
        "ano_objetivo", "semana_objetivo", "horizonte_semanas",
        "pred_baseline_persistencia", "pred_baseline_estacional",
        "pred_random_forest", "pred_hist_gradient_boosting",
        "modelo_seleccionado", "prediccion_final"
    ]
    df = df[cols].copy()
    df["ubigeo"] = df["ubigeo"].astype("string").str.zfill(6)
    for col in ["fecha_generacion", "fecha_origen", "fecha_objetivo"]:
        df[col] = pd.to_datetime(df[col]).dt.date
    df.to_sql("fact_pronosticos", conn, if_exists="append", index=False, chunksize=1000)
    print(f"PronÃ³sticos cargados: {len(df):,}")


def load_metrics(conn):
    if not METRICS_FILE.exists():
        raise FileNotFoundError(f"No existe {METRICS_FILE}. Ejecuta primero el script 21.")
    df = pd.read_csv(METRICS_FILE)
    df = df.rename(columns={"MAE": "mae", "RMSE": "rmse", "R2": "r2", "MAE_positivos": "mae_positivos"})
    cols = [
        "horizonte", "periodo", "modelo", "registros_evaluados",
        "mae", "rmse", "r2", "mae_positivos", "casos_reales",
        "casos_predichos", "error_total_pct"
    ]
    df = df[cols]
    df = df.astype(object).where(pd.notna(df), None)
    df.to_sql("fact_metricas_modelo", conn, if_exists="append", index=False, chunksize=1000)
    print(f"MÃ©tricas cargadas: {len(df):,}")


def main():
    if not DATASET.exists():
        raise FileNotFoundError(DATASET)
    engine = get_mysql_engine()
    usecols = pd.read_csv(DATASET, compression="gzip", nrows=0).columns.tolist()
    print("Conectando a MySQL...")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fact_pronosticos"))
        conn.execute(text("DELETE FROM fact_metricas_modelo"))
        conn.execute(text("DELETE FROM fact_casos_semanales"))
        conn.execute(text("DELETE FROM dim_distrito"))
        load_dimension(conn, usecols)
        load_historical_cases(conn, usecols)
        load_forecasts(conn)
        load_metrics(conn)
    print("\nEXPORTACIÃ“N A MYSQL COMPLETADA.")
    print("Las tablas quedaron listas para Power BI y la API Groq.")


if __name__ == "__main__":
    main()