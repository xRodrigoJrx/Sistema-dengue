import argparse
import sys
import pandas as pd
from sqlalchemy import text
from dengue_common import ROOT, DATASET, REPORTS_DIR, get_sql_engine

FORECAST_FILE = REPORTS_DIR / "pronosticos_dengue_4_semanas.csv.gz"
METRICS_FILE = REPORTS_DIR / "metricas_horizontes.csv"
CHUNK_SIZE = 10000


def table_count(conn, table):
    return int(conn.execute(text(f"SELECT COUNT_BIG(*) FROM dbo.{table}")).scalar_one())


def clear_tables(engine, historical=False):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dbo.fact_pronosticos"))
        conn.execute(text("DELETE FROM dbo.fact_metricas_modelo"))
        if historical:
            conn.execute(text("DELETE FROM dbo.fact_semanal_dengue"))
            conn.execute(text("DELETE FROM dbo.dim_distrito"))


def load_dimension(engine):
    wanted = ["ubigeo", "departamento", "provincia", "distrito"]
    header = pd.read_csv(DATASET, compression="gzip", nrows=0).columns.tolist()
    usecols = [c for c in wanted if c in header]
    if "ubigeo" not in usecols:
        raise ValueError("El dataset no contiene ubigeo.")
    parts = []
    for chunk in pd.read_csv(DATASET, compression="gzip", usecols=usecols, dtype={"ubigeo": "string"}, chunksize=200000):
        chunk["ubigeo"] = chunk["ubigeo"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
        parts.append(chunk.dropna(subset=["ubigeo"]).drop_duplicates("ubigeo"))
    dim = pd.concat(parts, ignore_index=True).drop_duplicates("ubigeo")
    for col in ["departamento", "provincia", "distrito"]:
        if col not in dim.columns:
            dim[col] = None
    dim = dim[["ubigeo", "departamento", "provincia", "distrito"]]
    dim["ubigeo"] = dim["ubigeo"].astype(str)
    dim.to_sql("dim_distrito", engine, schema="dbo", if_exists="append", index=False, chunksize=1000)
    print(f"Dimensión distrito: {len(dim):,} UBIGEO")


def load_historical(engine):
    header = pd.read_csv(DATASET, compression="gzip", nrows=0).columns.tolist()
    required = ["ubigeo", "ano", "semana", "fecha_inicio", "casos_dengue_reportados"]
    missing = [c for c in required if c not in header]
    if missing:
        raise ValueError(f"Faltan columnas del histórico: {missing}")

    optional = [
        "fecha_fin", "registro_minsa", "poblacion_proyectada",
        "tmean", "tmax", "tmin", "humr", "ptot",
        "clima_recuperado", "clima_grupo", "clima_metodo_extraccion"
    ]
    selected = required + [c for c in optional if c in header]
    total = 0
    for chunk in pd.read_csv(DATASET, compression="gzip", usecols=selected, dtype={"ubigeo": "string"}, chunksize=CHUNK_SIZE):
        chunk["ubigeo"] = chunk["ubigeo"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
        chunk["ano"] = pd.to_numeric(chunk["ano"], errors="coerce").fillna(0).astype("int16")
        chunk["semana"] = pd.to_numeric(chunk["semana"], errors="coerce").fillna(0).astype("int16")
        chunk["fecha_inicio"] = pd.to_datetime(chunk["fecha_inicio"], errors="coerce").dt.date
        if "fecha_fin" in chunk:
            chunk["fecha_fin"] = pd.to_datetime(chunk["fecha_fin"], errors="coerce").dt.date
        chunk["casos_dengue_reportados"] = pd.to_numeric(chunk["casos_dengue_reportados"], errors="coerce").fillna(0).astype("int64")
        chunk = chunk.rename(columns={"casos_dengue_reportados": "casos_reportados"})
        for col in ["poblacion_proyectada", "tmean", "tmax", "tmin", "humr", "ptot"]:
            if col in chunk:
                chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
        for col in ["registro_minsa", "clima_recuperado"]:
            if col in chunk:
                values = pd.to_numeric(chunk[col], errors="coerce").astype("Int64")
                chunk[col] = values.astype(object).where(values.notna(), None)
        chunk = chunk.dropna(subset=["ubigeo", "fecha_inicio"])
        chunk["ubigeo"] = chunk["ubigeo"].astype(str)
        chunk.to_sql("fact_semanal_dengue", engine, schema="dbo", if_exists="append", index=False, chunksize=2000)
        total += len(chunk)
        print(f"Histórico importado: {total:,}")
    print(f"Total histórico cargado: {total:,}")


def load_forecasts(engine):
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
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    df.to_sql("fact_pronosticos", engine, schema="dbo", if_exists="append", index=False, chunksize=1000)
    print(f"Pronósticos cargados: {len(df):,}")


def load_metrics(engine):
    if not METRICS_FILE.exists():
        raise FileNotFoundError(f"No existe {METRICS_FILE}. Ejecuta primero el script 21.")
    df = pd.read_csv(METRICS_FILE)
    df = df.rename(columns={"MAE": "mae", "RMSE": "rmse", "R2": "r2", "MAE_positivos": "mae_positivos"})
    cols = [
        "horizonte", "periodo", "modelo", "registros_evaluados", "mae", "rmse",
        "r2", "mae_positivos", "casos_reales", "casos_predichos", "error_total_pct"
    ]
    df = df[cols].astype(object).where(pd.notna(df[cols]), None)
    df.to_sql("fact_metricas_modelo", engine, schema="dbo", if_exists="append", index=False, chunksize=1000)
    print(f"Filas de métricas cargadas: {len(df):,}")


def main():
    parser = argparse.ArgumentParser(description="Carga el dataset de dengue a SQL Server Express.")
    parser.add_argument("--replace", action="store_true", help="Borra y vuelve a cargar el histórico, pronósticos y métricas.")
    parser.add_argument("--solo-pronosticos", action="store_true", help="Actualiza pronósticos y métricas sin recargar el histórico de 2.5 millones de filas.")
    args = parser.parse_args()

    if not DATASET.exists():
        raise FileNotFoundError(DATASET)
    engine = get_sql_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        existing = {
            "dim_distrito": table_count(conn, "dim_distrito"),
            "fact_semanal_dengue": table_count(conn, "fact_semanal_dengue"),
            "fact_pronosticos": table_count(conn, "fact_pronosticos"),
            "fact_metricas_modelo": table_count(conn, "fact_metricas_modelo")
        }
    print("Conexión SQL Server correcta.")
    print("Registros actuales:", existing)

    if args.solo_pronosticos:
        clear_tables(engine, historical=False)
        load_forecasts(engine)
        load_metrics(engine)
    else:
        historical_exists = existing["dim_distrito"] or existing["fact_semanal_dengue"]
        if historical_exists and not args.replace:
            raise RuntimeError(
                "El histórico ya tiene datos. No se sobrescribió nada. "
                "Usa --solo-pronosticos para actualizar predicciones o --replace para recargar todo."
            )
        if args.replace:
            clear_tables(engine, historical=True)
        else:
            clear_tables(engine, historical=False)
        load_dimension(engine)
        load_historical(engine)
        load_forecasts(engine)
        load_metrics(engine)

    print("\nEXPORTACIÓN A SQL SERVER COMPLETADA.")
    print("Tablas disponibles para SSMS y Power BI.")
    print("IMPORTANTE: en el histórico, registro_minsa=0 identifica semanas sin registro MINSA; no las interpretes como cero casos confirmados.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR DE EXPORTACIÓN: {exc}")
        sys.exit(1)
