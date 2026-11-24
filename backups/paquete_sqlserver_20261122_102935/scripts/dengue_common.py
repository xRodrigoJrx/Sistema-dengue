from pathlib import Path
from datetime import date, timedelta
import os
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
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


def load_dataset():
    if not DATASET.exists():
        raise FileNotFoundError(f"No existe el dataset de modelamiento: {DATASET}")

    print(f"Leyendo: {DATASET}")
    df = pd.read_csv(
        DATASET,
        compression="gzip",
        low_memory=False,
        dtype={ID: "string"}
    )

    required = [ID, DATE, YEAR, WEEK, TARGET, SPLIT]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas obligatorias en el dataset: {missing}")

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
            "validacion": "validation",
            "validaciÃ³n": "validation",
            "entrenamiento": "train",
            "prueba": "test"
        })
    )

    df = df.dropna(subset=[ID, DATE, YEAR, WEEK, TARGET, SPLIT]).copy()
    df[YEAR] = df[YEAR].astype("int16")
    df[WEEK] = df[WEEK].astype("int8")
    df[TARGET] = df[TARGET].astype("float32")

    valid_splits = {"train", "validation", "test"}
    found_splits = set(df[SPLIT].unique())
    if not found_splits.issubset(valid_splits):
        raise ValueError(f"Valores inesperados en {SPLIT}: {found_splits}")
    if not valid_splits.issubset(found_splits):
        raise ValueError(f"El dataset debe contener train, validation y test. Encontrados: {found_splits}")

    df = df.sort_values([ID, DATE]).reset_index(drop=True)
    duplicated = df.duplicated([ID, DATE]).sum()
    if duplicated:
        raise ValueError(f"Hay {duplicated:,} duplicados por UBIGEO y fecha. No se continuarÃ¡ para evitar desplazar semanas incorrectamente.")

    print(f"Registros: {len(df):,}")
    print(f"Distritos: {df[ID].nunique():,}")
    print(f"Columnas: {len(df.columns)}")
    print("DistribuciÃ³n temporal:")
    print(df.groupby(SPLIT).size().to_string())
    return df


def build_base_features(df):
    excluded = {
        ID, DATE, "fecha_fin", SPLIT,
        "departamento", "provincia", "distrito",
        "fuente", "zona_horaria", "clima_fuente_detalle",
        "nombre_departamento_geografico",
        "nombre_provincia_geografico",
        "nombre_distrito_geografico"
    }

    numeric = {}
    for col in df.columns:
        if col in excluded:
            continue
        values = pd.to_numeric(df[col], errors="coerce")
        if values.notna().any():
            numeric[col] = values.astype("float32")

    X = pd.DataFrame(numeric, index=df.index)

    if "departamento" in df.columns:
        department = (
            df["departamento"].fillna("SIN_DATO")
            .astype("string").str.strip().str.upper()
        )
        geo = pd.get_dummies(department, prefix="depto", dtype="float32")
        X = pd.concat([X, geo], axis=1)

    if X.empty:
        raise ValueError("No se encontraron variables predictoras utilizables.")
    return X


def add_target_calendar_features(X, target_year, target_week):
    X = X.copy()
    year = pd.to_numeric(pd.Series(target_year, index=X.index), errors="coerce")
    week = pd.to_numeric(pd.Series(target_week, index=X.index), errors="coerce")
    X["objetivo_ano"] = year.astype("float32")
    X["objetivo_semana"] = week.astype("float32")
    X["objetivo_semana_sin"] = np.sin(2 * np.pi * week / 53).astype("float32")
    X["objetivo_semana_cos"] = np.cos(2 * np.pi * week / 53).astype("float32")
    return X


def create_horizon_targets(df, horizon):
    grouped = df.groupby(ID, sort=False)
    return {
        "y": grouped[TARGET].shift(-horizon),
        "split": grouped[SPLIT].shift(-horizon),
        "year": grouped[YEAR].shift(-horizon),
        "week": grouped[WEEK].shift(-horizon),
        "date": grouped[DATE].shift(-horizon),
        "baseline_persistence": df[TARGET].copy(),
        "baseline_seasonal": grouped[TARGET].shift(52 - horizon)
    }


def prepare_model_matrix(X, feature_columns, medians):
    X = X.reindex(columns=feature_columns)
    X = X.replace([np.inf, -np.inf], np.nan)
    fill_values = pd.Series(medians).reindex(feature_columns).fillna(0)
    return X.fillna(fill_values).astype("float32")


def epidemiological_year_week(value):
    current = pd.Timestamp(value).date()
    epi_year = (current + timedelta(days=3)).year
    january_four = date(epi_year, 1, 4)
    days_since_sunday = (january_four.weekday() + 1) % 7
    first_sunday = january_four - timedelta(days=days_since_sunday)
    epi_week = ((current - first_sunday).days // 7) + 1
    return epi_year, epi_week


def get_mysql_engine():
    load_dotenv(ROOT / ".env")
    required = ["MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_HOST", "MYSQL_DATABASE"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Faltan variables en .env: {missing}")

    url = URL.create(
        drivername="mysql+mysqlconnector",
        username=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE", "dengue_analytics"),
        query={"charset": "utf8mb4"}
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)