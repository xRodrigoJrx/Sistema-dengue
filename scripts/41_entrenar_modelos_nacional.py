from pathlib import Path
import warnings
import traceback

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score

from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX

try:
    from xgboost import XGBRegressor
    TIENE_XGBOOST = True
except ImportError:
    TIENE_XGBOOST = False


# ============================================================
# 1. CONFIGURACION
# ============================================================

warnings.filterwarnings("ignore")

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ENTRADA = (
    BASE / "data/processed/pronostico_nacional/"
    "serie_nacional_semanal_2000_2025.csv"
)

SALIDA = BASE / "data/processed/pronostico_nacional"
REPORTES = BASE / "reports/pronostico_nacional"

HOLDOUT = 52
ESTACIONALIDAD = 52

RETRASOS = [1, 2, 3, 4, 8, 13, 26, 52, 104]
VENTANAS = [4, 13, 26, 52, 104]

RANDOM_STATE = 42


# ============================================================
# 2. PREPARAR DIRECTORIOS
# ============================================================

def preparar_directorios():

    SALIDA.mkdir(parents=True, exist_ok=True)
    REPORTES.mkdir(parents=True, exist_ok=True)


# ============================================================
# 3. CARGAR Y VALIDAR INFORMACION
# ============================================================

def cargar_datos():

    print("\n1. CARGANDO SERIE HISTORICA...")

    if not ENTRADA.exists():
        raise FileNotFoundError(
            f"No existe el dataset: {ENTRADA}"
        )

    df = pd.read_csv(
        ENTRADA,
        encoding="utf-8-sig"
    )

    requeridas = [
        "fecha_inicio",
        "fecha_fin",
        "casos_dengue"
    ]

    faltantes = [
        c for c in requeridas if c not in df.columns
    ]

    if faltantes:
        raise ValueError(
            f"Columnas faltantes: {faltantes}"
        )

    df["fecha_inicio"] = pd.to_datetime(
        df["fecha_inicio"],
        errors="coerce"
    )

    df["fecha_fin"] = pd.to_datetime(
        df["fecha_fin"],
        errors="coerce"
    )

    df["casos_dengue"] = pd.to_numeric(
        df["casos_dengue"],
        errors="coerce"
    )

    if df["fecha_inicio"].isna().any():
        raise ValueError("Existen fechas iniciales invalidas.")

    if df["casos_dengue"].isna().any():
        raise ValueError("Existen casos dengue nulos.")

    if (df["casos_dengue"] < 0).any():
        raise ValueError("Existen casos negativos.")

    df = df.sort_values(
        "fecha_inicio"
    ).reset_index(drop=True)

    if df["fecha_inicio"].duplicated().any():
        raise ValueError("Existen fechas duplicadas.")

    diferencias = (
        df["fecha_inicio"].diff().dt.days.dropna()
    )

    if not (diferencias == 7).all():
        raise ValueError(
            "La serie presenta intervalos diferentes de 7 dias."
        )

    # La vista SQL presenta fecha_fin nula.
    # Se deriva la fecha de cierre semanal.

    nulos_fecha_fin = int(df["fecha_fin"].isna().sum())

    df["fecha_fin"] = df["fecha_fin"].fillna(
        df["fecha_inicio"] + pd.Timedelta(days=6)
    )

    print("REGISTROS:", len(df))
    print("FECHA INICIAL:", df["fecha_inicio"].min())
    print("FECHA FINAL:", df["fecha_inicio"].max())
    print("FECHAS FIN DERIVADAS:", nulos_fecha_fin)

    if len(df) <= HOLDOUT + max(RETRASOS):
        raise ValueError(
            "No existen suficientes observaciones para entrenar."
        )

    # Guardar una copia corregida sin alterar el original.

    archivo_corregido = (
        SALIDA / "serie_nacional_corregida.csv"
    )

    df.to_csv(
        archivo_corregido,
        index=False,
        encoding="utf-8-sig"
    )

    indice = pd.date_range(
        start=df["fecha_inicio"].iloc[0],
        periods=len(df),
        freq="7D"
    )

    if not np.array_equal(
        indice.values,
        df["fecha_inicio"].values
    ):
        raise ValueError(
            "Las fechas no coinciden con la frecuencia semanal."
        )

    serie = pd.Series(
        df["casos_dengue"].astype(float).values,
        index=indice,
        name="casos_dengue"
    )

    return df, serie, nulos_fecha_fin


# ============================================================
# 4. SEPARACION TEMPORAL
# ============================================================

def separar_datos(serie):

    print("\n2. SEPARACION DE ENTRENAMIENTO Y VALIDACION...")

    entrenamiento = serie.iloc[:-HOLDOUT].copy()

    validacion = serie.iloc[-HOLDOUT:].copy()

    print(
        "ENTRENAMIENTO:",
        entrenamiento.index.min().date(),
        "hasta",
        entrenamiento.index.max().date()
    )

    print(
        "VALIDACION:",
        validacion.index.min().date(),
        "hasta",
        validacion.index.max().date()
    )

    print("REGISTROS ENTRENAMIENTO:", len(entrenamiento))
    print("REGISTROS VALIDACION:", len(validacion))

    return entrenamiento, validacion


# ============================================================
# 5. METRICAS DE EVALUACION
# ============================================================

def calcular_metricas(real, predicho):

    real = np.asarray(real, dtype=float)

    predicho = np.asarray(predicho, dtype=float)

    error = real - predicho

    mae = np.mean(np.abs(error))

    rmse = np.sqrt(np.mean(error ** 2))

    denominador = np.sum(np.abs(real))

    wape = (
        np.sum(np.abs(error)) / denominador * 100
        if denominador > 0 else np.nan
    )

    smape = np.mean(
        2 * np.abs(error) /
        (np.abs(real) + np.abs(predicho) + 1e-9)
    ) * 100

    r2 = (
        r2_score(real, predicho)
        if len(real) > 1 else np.nan
    )

    return {
        "MAE": mae,
        "RMSE": rmse,
        "WAPE_pct": wape,
        "sMAPE_pct": smape,
        "R2": r2
    }


# ============================================================
# 6. MODELO BASELINE ESTACIONAL
# ============================================================

def entrenar_baseline(entrenamiento):

    print("\n3. ENTRENANDO BASELINE ESTACIONAL...")

    prediccion = entrenamiento.iloc[-ESTACIONALIDAD:].values

    print("BASELINE COMPLETADO")

    return np.maximum(prediccion, 0)


# ============================================================
# 7. MODELO ARIMA
# ============================================================

def entrenar_arima(entrenamiento, horizonte):

    print("\n4. ENTRENANDO ARIMA...")

    modelo = ARIMA(
        entrenamiento,
        order=(2, 1, 2),
        enforce_stationarity=False,
        enforce_invertibility=False
    )

    resultado = modelo.fit()

    prediccion = resultado.forecast(
        steps=horizonte
    )

    print("ARIMA COMPLETADO")

    return np.maximum(
        np.asarray(prediccion, dtype=float),
        0
    )


# ============================================================
# 8. MODELO SARIMA
# ============================================================

def entrenar_sarima(entrenamiento, horizonte):

    print("\n5. ENTRENANDO SARIMA...")

    modelo = SARIMAX(
        entrenamiento,
        order=(1, 1, 1),
        seasonal_order=(1, 0, 1, ESTACIONALIDAD),
        enforce_stationarity=False,
        enforce_invertibility=False
    )

    resultado = modelo.fit(
        disp=False,
        maxiter=80
    )

    prediccion = resultado.forecast(
        steps=horizonte
    )

    print("SARIMA COMPLETADO")

    return np.maximum(
        np.asarray(prediccion, dtype=float),
        0
    )


# ============================================================
# 9. VARIABLES PARA MODELOS MACHINE LEARNING
# ============================================================

def construir_variables(historial, fecha):

    historial = np.asarray(
        historial,
        dtype=float
    )

    if len(historial) < max(RETRASOS):
        raise ValueError(
            "Historial insuficiente para construir variables."
        )

    caracteristicas = []

    # Casos anteriores.

    for lag in RETRASOS:

        caracteristicas.append(
            historial[-lag]
        )

    # Estadisticas de ventanas anteriores.

    for ventana in VENTANAS:

        valores = historial[-ventana:]

        caracteristicas.extend([
            np.mean(valores),
            np.std(valores),
            np.max(valores)
        ])

    # Estacionalidad anual.

    dia = fecha.dayofyear

    caracteristicas.extend([
        np.sin(2 * np.pi * dia / 365.25),
        np.cos(2 * np.pi * dia / 365.25)
    ])

    return np.asarray(
        caracteristicas,
        dtype=float
    )


def construir_dataset_ml(serie_entrenamiento):

    valores = serie_entrenamiento.values

    fechas = serie_entrenamiento.index

    X = []
    y = []

    inicio = max(RETRASOS)

    for i in range(inicio, len(valores)):

        variables = construir_variables(
            valores[:i],
            fechas[i]
        )

        X.append(variables)

        y.append(valores[i])

    return np.asarray(X), np.asarray(y)


# ============================================================
# 10. PREDICCION RECURSIVA
# ============================================================

def pronosticar_ml(modelo, historial, fechas):

    historial = list(
        np.asarray(historial, dtype=float)
    )

    predicciones = []

    for fecha in fechas:

        variables = construir_variables(
            historial,
            fecha
        ).reshape(1, -1)

        prediccion = float(
            modelo.predict(variables)[0]
        )

        prediccion = max(0, prediccion)

        predicciones.append(prediccion)

        # La prediccion pasa a formar parte
        # del historial para la siguiente semana.

        historial.append(prediccion)

    return np.asarray(predicciones)


# ============================================================
# 11. RANDOM FOREST
# ============================================================

def entrenar_random_forest(entrenamiento, fechas):

    print("\n6. ENTRENANDO RANDOM FOREST...")

    X, y = construir_dataset_ml(entrenamiento)

    modelo = RandomForestRegressor(
        n_estimators=500,
        max_depth=None,
        min_samples_leaf=3,
        max_features=0.9,
        random_state=RANDOM_STATE,
        n_jobs=-1
    )

    modelo.fit(X, y)

    prediccion = pronosticar_ml(
        modelo,
        entrenamiento.values,
        fechas
    )

    print("RANDOM FOREST COMPLETADO")

    return prediccion


# ============================================================
# 12. XGBOOST
# ============================================================

def entrenar_xgboost(entrenamiento, fechas):

    if not TIENE_XGBOOST:

        print("\nXGBOOST NO INSTALADO. SE OMITIRA.")

        return None

    print("\n7. ENTRENANDO XGBOOST...")

    X, y = construir_dataset_ml(entrenamiento)

    modelo = XGBRegressor(
        n_estimators=500,
        max_depth=4,
        learning_rate=0.03,
        subsample=0.85,
        colsample_bytree=0.9,
        reg_lambda=2,
        objective="reg:squarederror",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        verbosity=0
    )

    modelo.fit(X, y)

    prediccion = pronosticar_ml(
        modelo,
        entrenamiento.values,
        fechas
    )

    print("XGBOOST COMPLETADO")

    return prediccion


# ============================================================
# 13. EVALUAR Y GUARDAR MODELOS
# ============================================================

def main():

    preparar_directorios()

    print("=" * 65)
    print("ENTRENAMIENTO Y COMPARACION DE MODELOS")
    print("PRONOSTICO NACIONAL DE DENGUE")
    print("=" * 65)

    df, serie, nulos_fecha_fin = cargar_datos()

    entrenamiento, validacion = separar_datos(serie)

    resultados = {}

    errores_modelos = []

    # --------------------------------------------------------
    # BASELINE
    # --------------------------------------------------------

    try:

        resultados["BASELINE_ESTACIONAL"] = entrenar_baseline(
            entrenamiento
        )

    except Exception as error:

        errores_modelos.append(
            f"BASELINE: {error}"
        )

    # --------------------------------------------------------
    # ARIMA
    # --------------------------------------------------------

    try:

        resultados["ARIMA"] = entrenar_arima(
            entrenamiento,
            len(validacion)
        )

    except Exception as error:

        errores_modelos.append(
            f"ARIMA: {error}"
        )

        traceback.print_exc()

    # --------------------------------------------------------
    # SARIMA
    # --------------------------------------------------------

    try:

        resultados["SARIMA"] = entrenar_sarima(
            entrenamiento,
            len(validacion)
        )

    except Exception as error:

        errores_modelos.append(
            f"SARIMA: {error}"
        )

        traceback.print_exc()

    # --------------------------------------------------------
    # RANDOM FOREST
    # --------------------------------------------------------

    try:

        resultados["RANDOM_FOREST"] = entrenar_random_forest(
            entrenamiento,
            validacion.index
        )

    except Exception as error:

        errores_modelos.append(
            f"RANDOM FOREST: {error}"
        )

        traceback.print_exc()

    # --------------------------------------------------------
    # XGBOOST
    # --------------------------------------------------------

    try:

        prediccion_xgb = entrenar_xgboost(
            entrenamiento,
            validacion.index
        )

        if prediccion_xgb is not None:

            resultados["XGBOOST"] = prediccion_xgb

    except Exception as error:

        errores_modelos.append(
            f"XGBOOST: {error}"
        )

        traceback.print_exc()

    if not resultados:

        raise RuntimeError(
            "Ningun modelo pudo generar predicciones."
        )

    # ========================================================
    # 14. COMPARACION DE METRICAS
    # ========================================================

    print("\n8. COMPARANDO RESULTADOS...")

    metricas = []

    predicciones_detalle = []

    real = validacion.values

    for nombre, prediccion in resultados.items():

        prediccion = np.asarray(
            prediccion,
            dtype=float
        )

        if len(prediccion) != len(real):
            continue

        prediccion = np.maximum(prediccion, 0)

        valores = calcular_metricas(
            real,
            prediccion
        )

        valores["modelo"] = nombre

        valores["registros_evaluados"] = len(real)

        metricas.append(valores)

        detalle = pd.DataFrame({

            "modelo": nombre,

            "fecha_inicio": validacion.index,

            "horizonte_semanas": np.arange(
                1,
                len(real) + 1
            ),

            "casos_reales": real,

            "casos_predichos": prediccion,

            "error_absoluto": np.abs(
                real - prediccion
            ),

            "error": real - prediccion

        })

        predicciones_detalle.append(detalle)

        print(
            f"{nombre}: "
            f"MAE={valores['MAE']:.2f} | "
            f"RMSE={valores['RMSE']:.2f} | "
            f"WAPE={valores['WAPE_pct']:.2f}%"
        )

    tabla_metricas = pd.DataFrame(metricas)

    tabla_metricas = tabla_metricas.sort_values(
        ["WAPE_pct", "RMSE"],
        ascending=True
    ).reset_index(drop=True)

    # ========================================================
    # 15. EVALUACION POR HORIZONTE
    # ========================================================

    print("\n9. EVALUACION POR HORIZONTES...")

    rangos = [
        (1, 4, "SEMANA_1_4"),
        (5, 13, "SEMANA_5_13"),
        (14, 26, "SEMANA_14_26"),
        (27, 52, "SEMANA_27_52")
    ]

    metricas_horizonte = []

    for detalle in predicciones_detalle:

        for inicio, fin, etiqueta in rangos:

            sub = detalle[
                detalle["horizonte_semanas"].between(
                    inicio,
                    fin
                )
            ]

            if sub.empty:
                continue

            valores = calcular_metricas(
                sub["casos_reales"],
                sub["casos_predichos"]
            )

            valores["modelo"] = detalle["modelo"].iloc[0]

            valores["horizonte"] = etiqueta

            metricas_horizonte.append(valores)

    tabla_horizontes = pd.DataFrame(
        metricas_horizonte
    )

    # ========================================================
    # 16. IDENTIFICAR MEJOR MODELO
    # ========================================================

    ganador = tabla_metricas.iloc[0]

    nombre_ganador = ganador["modelo"]

    print("\n" + "=" * 65)
    print("MODELO CON MEJOR RESULTADO EN VALIDACION")
    print("=" * 65)

    print("MODELO:", nombre_ganador)
    print("MAE:", round(ganador["MAE"], 3))
    print("RMSE:", round(ganador["RMSE"], 3))
    print("WAPE:", round(ganador["WAPE_pct"], 3), "%")
    print("sMAPE:", round(ganador["sMAPE_pct"], 3), "%")
    print("R2:", round(ganador["R2"], 4))

    # ========================================================
    # 17. EXPORTAR RESULTADOS
    # ========================================================

    archivo_metricas = (
        SALIDA / "metricas_comparacion_modelos.csv"
    )

    archivo_predicciones = (
        SALIDA / "predicciones_validacion_2025.csv"
    )

    archivo_horizontes = (
        SALIDA / "metricas_por_horizonte.csv"
    )

    archivo_ganador = (
        REPORTES / "modelo_nacional_seleccionado.txt"
    )

    archivo_diagnostico = (
        REPORTES / "41_diagnostico_entrenamiento.txt"
    )

    tabla_metricas.to_csv(
        archivo_metricas,
        index=False,
        encoding="utf-8-sig"
    )

    pd.concat(
        predicciones_detalle,
        ignore_index=True
    ).to_csv(
        archivo_predicciones,
        index=False,
        encoding="utf-8-sig"
    )

    tabla_horizontes.to_csv(
        archivo_horizontes,
        index=False,
        encoding="utf-8-sig"
    )

    texto_ganador = f"""
SELECCION DE MODELO NACIONAL DE DENGUE

Modelo seleccionado: {nombre_ganador}

Periodo de entrenamiento:
{entrenamiento.index.min().date()} - {entrenamiento.index.max().date()}

Periodo de validacion:
{validacion.index.min().date()} - {validacion.index.max().date()}

Metricas:

MAE: {ganador['MAE']:.4f}
RMSE: {ganador['RMSE']:.4f}
WAPE: {ganador['WAPE_pct']:.4f}%
sMAPE: {ganador['sMAPE_pct']:.4f}%
R2: {ganador['R2']:.4f}

Criterio de seleccion:
Menor WAPE. En caso de empate, menor RMSE.

Este modelo es el mejor entre los modelos evaluados
en el periodo de validacion 2025.

La seleccion debe complementarse con la revision
de los errores por horizonte y del comportamiento
en periodos epidemiologicos de alta incidencia.
"""

    archivo_ganador.write_text(
        texto_ganador,
        encoding="utf-8"
    )

    diagnostico = [
        "DIAGNOSTICO DEL ENTRENAMIENTO NACIONAL",
        "=" * 60,
        f"Registros historicos: {len(serie)}",
        f"Entrenamiento: {len(entrenamiento)}",
        f"Validacion: {len(validacion)}",
        f"Fecha fin derivadas: {nulos_fecha_fin}",
        f"Modelos completados: {len(resultados)}",
        f"Modelo seleccionado: {nombre_ganador}",
        "",
        "MODELOS EJECUTADOS:"
    ]

    diagnostico.extend(
        [f"- {nombre}" for nombre in resultados]
    )

    diagnostico.extend([
        "",
        "MODELOS CON ERRORES:"
    ])

    diagnostico.extend(
        [f"- {error}" for error in errores_modelos]
    )

    diagnostico.extend([
        "",
        "TABLA DE RESULTADOS:",
        tabla_metricas.to_string(index=False),
        "",
        "VALIDACION POR HORIZONTES:",
        tabla_horizontes.to_string(index=False)
    ])

    archivo_diagnostico.write_text(
        "\n".join(diagnostico),
        encoding="utf-8"
    )

    # ========================================================
    # 18. RESUMEN FINAL
    # ========================================================

    print("\n" + "=" * 65)
    print("ENTRENAMIENTO FINALIZADO")
    print("=" * 65)

    print("\nTABLA COMPARATIVA:")

    print(
        tabla_metricas.to_string(
            index=False
        )
    )

    print("\nARCHIVOS GENERADOS:")

    print(archivo_metricas)
    print(archivo_predicciones)
    print(archivo_horizontes)
    print(archivo_ganador)
    print(archivo_diagnostico)

    print("\nNO SE MODIFICO SQL SERVER.")

    print("\n" + "=" * 65)


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\nERROR EN EL ENTRENAMIENTO:")
        print(error)

        raise
