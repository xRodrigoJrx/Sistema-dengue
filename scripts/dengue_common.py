from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "processed" / "modelamiento" / "dataset_modelamiento_dengue_2000_2025.csv.gz"
MODELS_DIR = ROOT / "models" / "pronosticos"
REPORTS_DIR = ROOT / "reports" / "pronosticos"
TARGET = "casos_dengue_reportados"
ID = "ubigeo"
DATE = "fecha_inicio"
YEAR = "ano"
WEEK = "semana"
SPLIT = "split_temporal"

REQUIRED_COLUMNS = [ID, DATE, YEAR, WEEK, TARGET, SPLIT]
EXCLUDED_FEATURE_TOKENS = (
    "casos", "tasa", "registro_minsa", "poblacion", "geografia_disponible",
    "ubigeo", "fecha", "split", "fuente", "zona_horaria", "nombre_",
    "departamento", "provincia", "distrito", "ano", "semana", "id"
)


def load_dataset() -> pd.DataFrame:
    """Read only the model dataset; never changes source files."""
    if not DATASET.exists():
        raise FileNotFoundError(f"No existe el dataset de modelamiento: {DATASET}")

    header = pd.read_csv(DATASET, compression="gzip", nrows=0).columns.tolist()
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"Faltan columnas obligatorias en el dataset: {missing}")

    # Keep identifiers, target/split, geographic label and numeric exogenous candidates.
    # Case-derived columns, population (mostly unavailable before 2018), and IDs are excluded.
    usecols = []
    for col in header:
        low = col.lower()
        if col in REQUIRED_COLUMNS or col in {"departamento", "provincia", "distrito", "registro_minsa"}:
            usecols.append(col)
            continue
        if any(token in low for token in EXCLUDED_FEATURE_TOKENS):
            continue
        usecols.append(col)

    df = pd.read_csv(
        DATASET,
        compression="gzip",
        usecols=usecols,
        low_memory=False,
        dtype={ID: "string"}
    )

    df[ID] = (
        df[ID].astype("string").str.strip()
        .str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    df[DATE] = pd.to_datetime(df[DATE], errors="coerce")
    for col in [YEAR, WEEK, TARGET]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df[SPLIT] = (
        df[SPLIT].astype("string").str.strip().str.lower()
        .replace({
            "validacion": "validation", "validación": "validation",
            "entrenamiento": "train", "prueba": "test"
        })
    )

    df = df.dropna(subset=REQUIRED_COLUMNS).copy()
    df[YEAR] = df[YEAR].astype("int16")
    df[WEEK] = df[WEEK].astype("int16")
    df[TARGET] = pd.to_numeric(df[TARGET], errors="coerce").clip(lower=0).astype("float32")
    if "registro_minsa" in df.columns:
        df["registro_minsa"] = pd.to_numeric(df["registro_minsa"], errors="coerce")

    valid_splits = {"train", "validation", "test"}
    found = set(df[SPLIT].dropna().unique())
    if not valid_splits.issubset(found):
        raise ValueError(f"Se requieren train, validation y test. Encontrados: {sorted(found)}")

    df = df.sort_values([ID, DATE]).reset_index(drop=True)
    duplicated = int(df.duplicated([ID, DATE]).sum())
    if duplicated:
        raise ValueError(
            f"Hay {duplicated:,} duplicados por UBIGEO y fecha. "
            "Se detiene para no desplazar incorrectamente los rezagos."
        )

    # Convert candidate predictors to numeric; non-numeric columns remain labels only.
    for col in df.columns:
        if col not in REQUIRED_COLUMNS and col not in {"departamento", "provincia", "distrito"}:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")

    print(f"Registros cargados: {len(df):,}")
    print(f"Distritos: {df[ID].nunique():,}")
    print(f"Variables leídas: {len(df.columns)}")
    print("Distribución temporal:")
    print(df.groupby(SPLIT).size().to_string())
    return df


def observed_cases(df: pd.DataFrame) -> pd.Series:
    """Cases are observed only when MINSA has a record; unreported weeks are NaN, not zero."""
    values = pd.to_numeric(df[TARGET], errors="coerce").clip(lower=0)
    if "registro_minsa" in df.columns:
        registered = pd.to_numeric(df["registro_minsa"], errors="coerce").eq(1)
        return values.where(registered)
    print("ADVERTENCIA: el dataset no tiene registro_minsa; se tratarán todos los valores de casos como observados.")
    return values


def build_base_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build predictors using only exogenous variables and past reported dengue cases."""
    excluded = set(REQUIRED_COLUMNS) | {
        "fecha_fin", "departamento", "provincia", "distrito",
        "clima_grupo", "clima_metodo_extraccion"
    }
    numeric_cols = []
    for col in df.columns:
        if col in excluded:
            continue
        low = col.lower()
        if any(token in low for token in EXCLUDED_FEATURE_TOKENS):
            continue
        if pd.api.types.is_numeric_dtype(df[col]) and df[col].notna().any():
            numeric_cols.append(col)

    X = df[numeric_cols].copy() if numeric_cols else pd.DataFrame(index=df.index)
    X = X.replace([np.inf, -np.inf], np.nan)

    observed = observed_cases(df)
    grouped = observed.groupby(df[ID], sort=False)
    for lag in (1, 2, 3, 4, 52):
        X[f"casos_lag_{lag}"] = grouped.shift(lag).astype("float32")

    previous = grouped.shift(1)
    for window in (4, 8):
        rolling = previous.groupby(df[ID], sort=False).rolling(window, min_periods=1).mean()
        X[f"casos_media_movil_{window}"] = rolling.reset_index(level=0, drop=True).astype("float32")

    current_week = pd.to_numeric(df[WEEK], errors="coerce").astype("float32")
    X["semana_sin"] = np.sin(2 * np.pi * current_week / 53).astype("float32")
    X["semana_cos"] = np.cos(2 * np.pi * current_week / 53).astype("float32")
    X["ano_indice"] = (pd.to_numeric(df[YEAR], errors="coerce") - 2000).astype("float32")

    if "departamento" in df.columns:
        department = df["departamento"].fillna("SIN_DATO").astype("string").str.strip().str.upper()
        dummies = pd.get_dummies(department, prefix="depto", dtype="float32")
        dummies.index = df.index
        X = pd.concat([X, dummies], axis=1)

    if X.empty:
        raise ValueError("No se encontraron variables predictoras válidas.")
    return X.replace([np.inf, -np.inf], np.nan).astype("float32")


def add_target_calendar_features(X: pd.DataFrame, target_year, target_week) -> pd.DataFrame:
    X = X.copy()
    year = pd.Series(target_year, index=X.index, dtype="float32")
    week = pd.Series(target_week, index=X.index, dtype="float32")
    X["objetivo_ano"] = year
    X["objetivo_semana"] = week
    X["objetivo_semana_sin"] = np.sin(2 * np.pi * week / 53).astype("float32")
    X["objetivo_semana_cos"] = np.cos(2 * np.pi * week / 53).astype("float32")
    return X


def create_horizon_targets(df: pd.DataFrame, horizon: int) -> dict:
    observed = observed_cases(df)
    grouped_observed = observed.groupby(df[ID], sort=False)
    grouped = df.groupby(ID, sort=False)
    persistence = grouped_observed.ffill()
    return {
        # Evaluate/train only weeks with a MINSA record. Missing reports are not zeros.
        "y": grouped_observed.shift(-horizon),
        "split": grouped[SPLIT].shift(-horizon),
        "year": grouped[YEAR].shift(-horizon),
        "week": grouped[WEEK].shift(-horizon),
        "date": grouped[DATE].shift(-horizon),
        "baseline_persistence": persistence,
        "baseline_seasonal": grouped_observed.shift(52 - horizon)
    }


def prepare_model_matrix(X: pd.DataFrame, feature_columns, medians) -> pd.DataFrame:
    X = X.reindex(columns=feature_columns).replace([np.inf, -np.inf], np.nan)
    fill = pd.Series(medians).reindex(feature_columns).fillna(0)
    return X.fillna(fill).astype("float32")


def epidemiological_year_week(value) -> tuple[int, int]:
    """Sunday-start epidemiological week, aligned to this project's date convention."""
    current = pd.Timestamp(value).date()

    def first_sunday(year: int) -> date:
        # Week 1 is the Sunday-start week that contains January 4.
        jan4 = date(year, 1, 4)
        return jan4 - timedelta(days=(jan4.weekday() + 1) % 7)

    epi_year = current.year
    if current < first_sunday(epi_year):
        epi_year -= 1
    start = first_sunday(epi_year)
    epi_week = ((current - start).days // 7) + 1
    return epi_year, epi_week


def get_sql_engine():
    """Connect to local SQL Server Express using Windows or SQL authentication."""
    load_dotenv(ROOT / ".env")
    server = os.getenv("SQL_SERVER", r"localhost\SQLEXPRESS")
    database = os.getenv("SQL_DATABASE", "dengue_analytics")
    driver = os.getenv("SQL_DRIVER", "ODBC Driver 18 for SQL Server")
    trust = os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "yes")
    encrypt = os.getenv("SQL_ENCRYPT", "yes")
    auth = os.getenv("SQL_AUTH", "windows").strip().lower()

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        f"Encrypt={encrypt}",
        f"TrustServerCertificate={trust}",
        "LongAsMax=Yes"
    ]
    if auth == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        username = os.getenv("SQL_USER")
        password = os.getenv("SQL_PASSWORD")
        if not username or not password:
            raise ValueError("SQL_AUTH=sql requiere SQL_USER y SQL_PASSWORD en .env")
        parts.extend([f"UID={username}", f"PWD={password}"])

    url = URL.create("mssql+pyodbc", query={"odbc_connect": ";".join(parts) + ";"})
    return create_engine(url, fast_executemany=True, pool_pre_ping=True, pool_recycle=1800)


def test_sql_connection() -> dict:
    engine = get_sql_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT @@SERVERNAME AS servidor, DB_NAME() AS base_datos, @@VERSION AS version_sql")).mappings().one()
    return dict(row)
