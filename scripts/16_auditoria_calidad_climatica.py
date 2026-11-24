
from pathlib import Path
import pandas as pd
import numpy as np

# ============================================================
# AUDITORIA DE CALIDAD CLIMATICA 2000-2025
# SOLO LECTURA - NO MODIFICA LOS DATOS
# ============================================================

BASE = Path(__file__).resolve().parents[1]

CARPETA = BASE / "data/processed/clima_integrado"
REPORTES = BASE / "reports/auditoria_calidad_climatica"

ANIOS = range(2000, 2026)

UBIGEOS_RECUPERADOS = {
    "070102", "070104", "070105",
    "110501", "140114",
    "150108", "150120", "150121",
    "150124", "150136", "150138",
    "150803", "150805"
}

VARIABLES = [
    "tmean", "tmax", "tmin",
    "humr", "ptot", "ptot_raw",
    "n_dias", "n_horas"
]

CLAVES = ["ano", "ubigeo", "semana"]

perfiles = []
resumenes = []
resumen_alertas = []
muestras_alertas = []


# ============================================================
# FUNCIONES
# ============================================================

def cargar_archivo(anio):

    ruta = CARPETA / f"clima_dengue_peru_{anio}.csv"

    if not ruta.exists():
        raise FileNotFoundError(ruta)

    df = pd.read_csv(
        ruta,
        dtype={"ubigeo": "string"},
        low_memory=False
    )

    df.columns = df.columns.str.strip()

    requeridas = CLAVES + VARIABLES

    faltantes = [
        c for c in requeridas
        if c not in df.columns
    ]

    if faltantes:
        raise ValueError(
            f"{anio}: faltan columnas {faltantes}"
        )

    df["ubigeo"] = (
        df["ubigeo"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    conversiones = {}

    for variable in VARIABLES:

        original = df[variable]

        convertido = pd.to_numeric(
            original,
            errors="coerce"
        )

        conversiones[variable] = int(
            (original.notna() & convertido.isna()).sum()
        )

        df[variable] = convertido

    return df, conversiones


def generar_perfil(df, anio, grupo):

    for variable in VARIABLES:

        serie = df[variable].dropna()

        if len(serie) == 0:
            continue

        q01 = serie.quantile(0.01)
        q05 = serie.quantile(0.05)
        q25 = serie.quantile(0.25)
        q50 = serie.quantile(0.50)
        q75 = serie.quantile(0.75)
        q95 = serie.quantile(0.95)
        q99 = serie.quantile(0.99)

        iqr = q75 - q25

        inferior = q25 - 1.5 * iqr
        superior = q75 + 1.5 * iqr

        perfiles.append({

            "anio": anio,
            "grupo": grupo,
            "variable": variable,

            "registros": len(df),
            "valores_validos": len(serie),
            "nulos": int(df[variable].isna().sum()),

            "media": serie.mean(),
            "desviacion_std": serie.std(),

            "minimo": serie.min(),
            "p01": q01,
            "p05": q05,
            "q25": q25,
            "mediana": q50,
            "q75": q75,
            "p95": q95,
            "p99": q99,
            "maximo": serie.max(),

            "ceros": int((serie == 0).sum()),
            "negativos": int((serie < 0).sum()),

            "atipicos_iqr": int(
                ((serie < inferior) | (serie > superior)).sum()
            )

        })


def registrar_regla(
    df,
    anio,
    codigo,
    variable,
    descripcion,
    mascara,
    columnas
):

    mascara = pd.Series(
        mascara,
        index=df.index
    ).fillna(False).astype(bool)

    cantidad = int(mascara.sum())

    resumen_alertas.append({

        "anio": anio,
        "codigo": codigo,
        "variable": variable,
        "descripcion": descripcion,
        "registros_afectados": cantidad,
        "ejemplos_guardados": min(cantidad, 100)

    })

    if cantidad == 0:
        return cantidad

    columnas = [
        c for c in CLAVES + columnas
        if c in df.columns
    ]

    muestra = df.loc[
        mascara,
        columnas
    ].head(100)

    for _, fila in muestra.iterrows():

        registro = fila.to_dict()

        registro["anio_auditoria"] = anio
        registro["codigo_alerta"] = codigo
        registro["variable"] = variable
        registro["descripcion"] = descripcion

        muestras_alertas.append(registro)

    return cantidad


# ============================================================
# EJECUCION PRINCIPAL
# ============================================================

def main():

    print("=" * 65)
    print("AUDITORIA DE CALIDAD CLIMATICA")
    print("PERIODO 2000-2025")
    print("=" * 65)

    REPORTES.mkdir(
        parents=True,
        exist_ok=True
    )

    for anio in ANIOS:

        print("\n" + "=" * 60)
        print("ANALIZANDO:", anio)
        print("=" * 60)

        df, conversiones = cargar_archivo(anio)

        incidencias = 0

        semanas = int(df["semana"].nunique())

        duplicados = int(
            df.duplicated(
                subset=CLAVES
            ).sum()
        )

        distritos = int(
            df["ubigeo"].nunique()
        )

        # ----------------------------------------------------
        # 1. ESTRUCTURA
        # ----------------------------------------------------

        if semanas not in (52, 53):
            incidencias += 1

        if distritos != 1891:
            incidencias += 1

        if duplicados:
            incidencias += 1

        if len(df) != 1891 * semanas:
            incidencias += 1

        # ----------------------------------------------------
        # 2. GRUPOS DE ANALISIS
        # ----------------------------------------------------

        recuperados = df[
            df["ubigeo"].isin(UBIGEOS_RECUPERADOS)
        ]

        otros = df[
            ~df["ubigeo"].isin(UBIGEOS_RECUPERADOS)
        ]

        generar_perfil(df, anio, "TODOS")

        generar_perfil(
            recuperados,
            anio,
            "13_RECUPERADOS"
        )

        generar_perfil(
            otros,
            anio,
            "OTROS_DISTRITOS"
        )

        # ----------------------------------------------------
        # 3. CONVERSIONES NUMERICAS
        # ----------------------------------------------------

        errores_conversion = sum(
            conversiones.values()
        )

        for variable, cantidad in conversiones.items():

            if cantidad:

                incidencias += cantidad

                resumen_alertas.append({

                    "anio": anio,
                    "codigo": "CONVERSION",
                    "variable": variable,
                    "descripcion": "Valores no numericos",
                    "registros_afectados": cantidad,
                    "ejemplos_guardados": 0

                })

        # ----------------------------------------------------
        # 4. TEMPERATURAS
        # ----------------------------------------------------

        completas = df[
            ["tmin", "tmean", "tmax"]
        ].notna().all(axis=1)

        temperatura_incorrecta = completas & (
            (df["tmax"] < df["tmin"]) |
            (df["tmean"] < df["tmin"]) |
            (df["tmean"] > df["tmax"])
        )

        n = registrar_regla(
            df, anio,
            "TEMP_ORDEN",
            "tmin,tmean,tmax",
            "La temperatura media no esta entre minima y maxima",
            temperatura_incorrecta,
            ["tmin", "tmean", "tmax"]
        )

        incidencias += n

        # ----------------------------------------------------
        # 5. HUMEDAD RELATIVA
        # ----------------------------------------------------

        humedad_incorrecta = (
            df["humr"].notna() &
            ~df["humr"].between(0, 100)
        )

        n = registrar_regla(
            df, anio,
            "HUMEDAD_RANGO",
            "humr",
            "Humedad fuera del rango 0-100",
            humedad_incorrecta,
            ["humr"]
        )

        incidencias += n

        # ----------------------------------------------------
        # 6. PRECIPITACION
        # ----------------------------------------------------

        for variable in ["ptot", "ptot_raw"]:

            precipitacion_incorrecta = (
                df[variable].notna() &
                (df[variable] < 0)
            )

            n = registrar_regla(
                df, anio,
                "PRECIP_NEGATIVA",
                variable,
                "Precipitacion negativa",
                precipitacion_incorrecta,
                [variable]
            )

            incidencias += n

        # ----------------------------------------------------
        # 7. HORAS Y DIAS
        # ----------------------------------------------------

        dias_incorrectos = (
            df["n_dias"].notna() &
            (df["n_dias"] != 7)
        )

        n = registrar_regla(
            df, anio,
            "DIAS_SEMANA",
            "n_dias",
            "Cantidad de dias diferente de 7",
            dias_incorrectos,
            ["n_dias"]
        )

        incidencias += n

        horas_incorrectas = (
            df["n_horas"].notna() &
            (df["n_horas"] != 168)
        )

        n = registrar_regla(
            df, anio,
            "HORAS_SEMANA",
            "n_horas",
            "Cantidad de horas diferente de 168",
            horas_incorrectas,
            ["n_horas"]
        )

        incidencias += n

        # ----------------------------------------------------
        # 8. COMPLETITUD DE LOS 13 DISTRITOS
        # ----------------------------------------------------

        if set(recuperados["ubigeo"].unique()) != UBIGEOS_RECUPERADOS:
            incidencias += 1

        if len(recuperados) != 13 * semanas:
            incidencias += 1

        nulos_recuperados = 0

        for variable in VARIABLES:

            cantidad = int(
                recuperados[variable].isna().sum()
            )

            nulos_recuperados += cantidad

            if cantidad:

                incidencias += cantidad

                resumen_alertas.append({

                    "anio": anio,
                    "codigo": "NULOS_RECUPERADOS",
                    "variable": variable,
                    "descripcion": "Datos faltantes en distritos recuperados",
                    "registros_afectados": cantidad,
                    "ejemplos_guardados": 0

                })

        # ----------------------------------------------------
        # 9. RESUMEN ANUAL
        # ----------------------------------------------------

        resumenes.append({

            "anio": anio,
            "registros": len(df),
            "distritos": distritos,
            "semanas": semanas,
            "duplicados": duplicados,
            "registros_recuperados": len(recuperados),
            "registros_otros_distritos": len(otros),
            "nulos_recuperados": nulos_recuperados,
            "errores_conversion": errores_conversion,
            "incidencias": incidencias,
            "estado": "REVISAR" if incidencias else "OK"

        })

        print("REGISTROS:", len(df))
        print("DISTRITOS:", distritos)
        print("SEMANAS:", semanas)
        print("DUPLICADOS:", duplicados)
        print("REGISTROS RECUPERADOS:", len(recuperados))
        print("NULOS RECUPERADOS:", nulos_recuperados)
        print("ERRORES DE CONVERSION:", errores_conversion)
        print("INCIDENCIAS:", incidencias)

    # ========================================================
    # 10. EXPORTAR REPORTES
    # ========================================================

    df_perfil = pd.DataFrame(perfiles)
    df_resumen = pd.DataFrame(resumenes)
    df_alertas = pd.DataFrame(resumen_alertas)
    df_muestras = pd.DataFrame(muestras_alertas)

    df_perfil.to_csv(
        REPORTES / "81_perfil_variables_climaticas.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df_resumen.to_csv(
        REPORTES / "82_resumen_anual_calidad.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df_alertas.to_csv(
        REPORTES / "83_resumen_alertas_climaticas.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df_muestras.to_csv(
        REPORTES / "84_muestra_registros_anomalos.csv",
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # 11. RESULTADO FINAL
    # ========================================================

    correctos = int(
        df_resumen["estado"].eq("OK").sum()
    )

    total = len(df_resumen)

    print("\n" + "=" * 65)
    print("RESULTADO FINAL DE CALIDAD CLIMATICA")
    print("=" * 65)

    print(df_resumen.to_string(index=False))

    print("\nANIOS ANALIZADOS:", total)
    print("ANIOS SIN INCIDENCIAS:", correctos)
    print("ANIOS PARA REVISION:", total - correctos)

    print("\nREPORTES GENERADOS:")

    print(REPORTES / "81_perfil_variables_climaticas.csv")
    print(REPORTES / "82_resumen_anual_calidad.csv")
    print(REPORTES / "83_resumen_alertas_climaticas.csv")
    print(REPORTES / "84_muestra_registros_anomalos.csv")

    print("\nLOS ARCHIVOS ORIGINALES NO FUERON MODIFICADOS.")
    print("LOS ARCHIVOS CONSOLIDADOS NO FUERON MODIFICADOS.")

    print("=" * 65)


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("\nAUDITORIA INTERRUMPIDA")
        print("MOTIVO:", error)

        raise
