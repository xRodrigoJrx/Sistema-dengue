
from pathlib import Path
import pandas as pd
import numpy as np

# ============================================================
# AUDITORIA INDEPENDIENTE DEL CLIMA INTEGRADO
# PERIODO: 2000-2025
# ============================================================

BASE = Path(__file__).resolve().parents[1]

ORIGINAL_DIR = BASE / "data/raw/clima/era5_land"
RECUPERADO_DIR = BASE / "data/raw/clima/recuperado_13_distritos"
INTEGRADO_DIR = BASE / "data/processed/clima_integrado"

REPORT_DIR = BASE / "reports/auditoria_clima_integrado"

ANIOS = range(2000, 2026)
TOTAL_DISTRITOS = 1891

UBIGEOS = {
    "070102", "070104", "070105",
    "110501", "140114",
    "150108", "150120", "150121",
    "150124", "150136", "150138",
    "150803", "150805"
}

CLIMA = [
    "tmean", "tmax", "tmin",
    "humr", "ptot", "ptot_raw",
    "n_dias", "n_horas"
]

GEOGRAFIA = [
    "departamento", "provincia", "distrito"
]

CLAVES = ["ano", "ubigeo", "semana"]


# ============================================================
# FUNCIONES
# ============================================================

def cargar(ruta):

    if not ruta.exists():
        raise FileNotFoundError(str(ruta))

    df = pd.read_csv(
        ruta,
        dtype={"ubigeo": "string"},
        low_memory=False
    )

    df.columns = df.columns.str.strip()

    df["ubigeo"] = (
        df["ubigeo"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    for col in ["ano", "semana"]:
        df[col] = pd.to_numeric(
            df[col], errors="raise"
        ).astype(int)

    df["_key"] = (
        df["ano"].astype(str)
        + "|"
        + df["ubigeo"]
        + "|"
        + df["semana"].astype(str)
    )

    return df


def comparar(a, b):

    a = pd.Series(a).reset_index(drop=True)
    b = pd.Series(b).reset_index(drop=True)

    na = pd.to_numeric(a, errors="coerce")
    nb = pd.to_numeric(b, errors="coerce")

    son_numericos = (
        (a.isna() | na.notna()).all()
        and
        (b.isna() | nb.notna()).all()
    )

    if son_numericos:

        return np.isclose(
            na.to_numpy(dtype=float, na_value=np.nan),
            nb.to_numpy(dtype=float, na_value=np.nan),
            rtol=0,
            atol=1e-9,
            equal_nan=True
        )

    sa = (
        a.astype("string")
        .fillna("__NULO__")
    )

    sb = (
        b.astype("string")
        .fillna("__NULO__")
    )

    return sa.eq(sb).to_numpy()


def normalizar_geografia(serie):

    return (
        serie.astype("string")
        .fillna("")
        .str.strip()
        .str.upper()
    )


# ============================================================
# EJECUCION
# ============================================================

def main():

    print("=" * 65)
    print("AUDITORIA INDEPENDIENTE DEL CLIMA INTEGRADO")
    print("=" * 65)

    resultados = []

    for anio in ANIOS:

        print(f"\nANALIZANDO ANIO: {anio}")

        original = cargar(
            ORIGINAL_DIR /
            f"clima_dengue_peru_{anio}.csv"
        )

        recuperado = cargar(
            RECUPERADO_DIR /
            f"CLIMA_RECUPERADO_{anio}.csv"
        )

        integrado = cargar(
            INTEGRADO_DIR /
            f"clima_dengue_peru_{anio}.csv"
        )

        errores = []

        # ----------------------------------------------------
        # 1. ESTRUCTURA
        # ----------------------------------------------------

        if set(original.columns) != set(integrado.columns):
            errores.append("Diferencias en columnas")

        for col in CLIMA + GEOGRAFIA:
            if col not in integrado.columns:
                errores.append(f"Falta columna: {col}")

        # ----------------------------------------------------
        # 2. REGISTROS Y DISTRITOS
        # ----------------------------------------------------

        semanas = original["semana"].nunique()

        if semanas not in [52, 53]:
            errores.append("Calendario semanal incorrecto")

        if len(original) != TOTAL_DISTRITOS * semanas:
            errores.append("Registros originales incorrectos")

        if len(integrado) != len(original):
            errores.append("Cantidad de registros modificada")

        if original["ubigeo"].nunique() != TOTAL_DISTRITOS:
            errores.append("Distritos originales incorrectos")

        if integrado["ubigeo"].nunique() != TOTAL_DISTRITOS:
            errores.append("Distritos integrados incorrectos")

        # ----------------------------------------------------
        # 3. DUPLICADOS
        # ----------------------------------------------------

        duplicados_original = int(
            original["_key"].duplicated().sum()
        )

        duplicados_integrado = int(
            integrado["_key"].duplicated().sum()
        )

        duplicados_recuperado = int(
            recuperado["_key"].duplicated().sum()
        )

        if any([
            duplicados_original,
            duplicados_integrado,
            duplicados_recuperado
        ]):
            errores.append("Se encontraron claves duplicadas")

        # ----------------------------------------------------
        # 4. COBERTURA DE DISTRITOS Y SEMANAS
        # ----------------------------------------------------

        cobertura = original.groupby(
            "ubigeo"
        )["semana"].nunique()

        if not cobertura.eq(semanas).all():
            errores.append("Cobertura semanal original incompleta")

        # ----------------------------------------------------
        # 5. COMPARACION DE CLAVES
        # ----------------------------------------------------

        if set(original["_key"]) != set(integrado["_key"]):
            errores.append("Las claves originales e integradas difieren")

        if set(recuperado["ubigeo"]) != UBIGEOS:
            errores.append("UBIGEO recuperados incorrectos")

        claves_objetivo = original.loc[
            original["ubigeo"].isin(UBIGEOS),
            "_key"
        ].tolist()

        if set(recuperado["_key"]) != set(claves_objetivo):
            errores.append("Cobertura recuperada diferente")

        # ----------------------------------------------------
        # 6. COMPARACION DE LOS 1878 DISTRITOS RESTANTES
        # ----------------------------------------------------

        original_no = original[
            ~original["ubigeo"].isin(UBIGEOS)
        ].reset_index(drop=True)

        integrado_no = integrado[
            ~integrado["ubigeo"].isin(UBIGEOS)
        ].reset_index(drop=True)

        cambios_no_recuperados = 0

        for col in original.columns:

            if col == "_key":
                continue

            if col not in integrado.columns:
                continue

            iguales = comparar(
                original_no[col],
                integrado_no[col]
            )

            cambios_no_recuperados += int(
                (~iguales).sum()
            )

        if cambios_no_recuperados > 0:
            errores.append(
                "Cambios en distritos no recuperados"
            )

        # ----------------------------------------------------
        # 7. COLUMNAS QUE NO DEBIAN MODIFICARSE
        # ----------------------------------------------------

        protegidas = [
            c for c in original.columns
            if c not in CLIMA + GEOGRAFIA + ["_key"]
        ]

        cambios_protegidos = 0

        if set(original["_key"]) == set(integrado["_key"]):

            oi = original.set_index("_key")
            ii = integrado.set_index("_key")

            ii = ii.loc[oi.index]

            for col in protegidas:

                iguales = comparar(
                    oi[col],
                    ii[col]
                )

                cambios_protegidos += int(
                    (~iguales).sum()
                )

        if cambios_protegidos:
            errores.append(
                "Cambios en columnas protegidas"
            )

        # ----------------------------------------------------
        # 8. VALIDACION DE LOS 13 DISTRITOS
        # ----------------------------------------------------

        oi = original.set_index("_key")
        ii = integrado.set_index("_key")
        ri = recuperado.set_index("_key")

        claves = claves_objetivo

        oi = oi.loc[claves]
        ii = ii.loc[claves]
        ri = ri.loc[claves]

        recuperados = len(claves)

        if recuperados != 13 * semanas:
            errores.append("Cantidad de registros recuperados incorrecta")

        # ----------------------------------------------------
        # 9. VALIDACION CLIMATICA
        # ----------------------------------------------------

        celdas_nulas = 0
        diferencias_climaticas = 0

        for col in CLIMA:

            if col not in ri.columns:
                errores.append(f"Falta variable recuperada: {col}")
                continue

            if col not in oi.columns:
                errores.append(f"Falta variable original: {col}")
                continue

            esperado = pd.to_numeric(
                oi[col], errors="coerce"
            ).fillna(
                pd.to_numeric(ri[col], errors="coerce")
            )

            actual = pd.to_numeric(
                ii[col], errors="coerce"
            )

            celdas_nulas += int(actual.isna().sum())

            iguales = comparar(esperado, actual)

            diferencias_climaticas += int(
                (~iguales).sum()
            )

        if celdas_nulas:
            errores.append("Existen nulos climaticos en recuperados")

        if diferencias_climaticas:
            errores.append("Diferencias en variables climaticas")

        # ----------------------------------------------------
        # 10. VALIDACION GEOGRAFICA
        # ----------------------------------------------------

        diferencias_geo = 0

        for col in GEOGRAFIA:

            original_geo = normalizar_geografia(
                oi[col]
            )

            recuperado_geo = normalizar_geografia(
                ri[col]
            )

            integrado_geo = normalizar_geografia(
                ii[col]
            )

            original_geo = original_geo.mask(
                original_geo.eq("")
            )

            esperado = original_geo.fillna(
                recuperado_geo
            )

            iguales = comparar(
                esperado,
                integrado_geo
            )

            diferencias_geo += int(
                (~iguales).sum()
            )

        if diferencias_geo:
            errores.append("Diferencias geograficas")

        # ----------------------------------------------------
        # 11. RESULTADO ANUAL
        # ----------------------------------------------------

        estado = "OK" if not errores else "ERROR"

        resultados.append({

            "anio": anio,
            "registros_originales": len(original),
            "registros_integrados": len(integrado),
            "distritos": integrado["ubigeo"].nunique(),
            "semanas": semanas,
            "registros_recuperados": recuperados,
            "duplicados": (
                duplicados_original
                + duplicados_integrado
                + duplicados_recuperado
            ),
            "nulos_climaticos_recuperados": celdas_nulas,
            "diferencias_climaticas": diferencias_climaticas,
            "diferencias_geograficas": diferencias_geo,
            "cambios_otros_distritos": cambios_no_recuperados,
            "cambios_columnas_protegidas": cambios_protegidos,
            "estado": estado,
            "observaciones": "; ".join(errores)

        })

        print(f"Registros integrados: {len(integrado):,}")
        print(f"Distritos: {integrado['ubigeo'].nunique()}")
        print(f"Recuperados: {recuperados}")
        print(f"Nulos climaticos: {celdas_nulas}")
        print(f"Diferencias climaticas: {diferencias_climaticas}")
        print(f"Diferencias geograficas: {diferencias_geo}")
        print(f"Cambios en otros distritos: {cambios_no_recuperados}")
        print(f"Estado: {estado}")

        if errores:
            for error in errores:
                print("ERROR:", error)

    # ========================================================
    # 12. REPORTE GENERAL
    # ========================================================

    df = pd.DataFrame(resultados)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    destino = (
        REPORT_DIR /
        "80_auditoria_independiente.csv"
    )

    df.to_csv(
        destino,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n" + "=" * 65)
    print("RESULTADO GENERAL")
    print("=" * 65)

    print(df.to_string(index=False))

    total_ok = int(df["estado"].eq("OK").sum())

    print("\nAÑOS AUDITADOS:", len(df))
    print("AÑOS CORRECTOS:", total_ok)
    print("AÑOS CON ERRORES:", len(df) - total_ok)

    print("\nREPORTE:")
    print(destino)

    if total_ok == 26:
        print("\nAUDITORIA INDEPENDIENTE SUPERADA.")
    else:
        print("\nAUDITORIA CON OBSERVACIONES.")
        print("No continuar con la integracion predictiva.")

    print("\nNO SE MODIFICARON ARCHIVOS.")
    print("=" * 65)


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\nAUDITORIA INTERRUMPIDA")
        print("MOTIVO:", error)
        raise
