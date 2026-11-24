
from pathlib import Path
from datetime import datetime
import shutil
import sys
import pandas as pd

# ============================================================
# DENGUE INTELLIGENCE PERU
# INTEGRACION CLIMATICA DEFINITIVA 2000-2025
# ============================================================

BASE = Path(__file__).resolve().parents[1]

ORIGINAL_DIR = BASE / "data/raw/clima/era5_land"
RECUPERADO_DIR = BASE / "data/raw/clima/recuperado_13_distritos"

PROCESSED_DIR = BASE / "data/processed"
OUTPUT_DIR = PROCESSED_DIR / "clima_integrado"
STAGING_DIR = PROCESSED_DIR / "_clima_integrado_temporal"

REPORT_DIR = BASE / "reports/integracion_clima"

ANIOS = range(2000, 2026)
TOTAL_DISTRITOS = 1891
BUFFER = 5566

UBIGEOS = {
    "070102", "070104", "070105",
    "110501", "140114",
    "150108", "150120", "150121",
    "150124", "150136", "150138",
    "150803", "150805"
}

CLAVES = ["ano", "ubigeo", "semana"]

GEOGRAFICAS = [
    "departamento",
    "provincia",
    "distrito"
]

CLIMATICAS = [
    "tmean", "tmax", "tmin",
    "humr", "ptot", "ptot_raw",
    "n_dias", "n_horas"
]

NUMERICAS_RECUPERADAS = CLIMATICAS + [
    "n_horas_ptot"
]

COLUMNAS_ORIGINALES = [
    "ubigeo", "departamento", "provincia", "distrito",
    "ano", "semana", "fecha_inicio", "fecha_fin",
    "tmean", "tmax", "tmin", "humr",
    "ptot", "ptot_raw", "n_dias", "n_horas",
    "fuente", "zona_horaria", "resolucion_m"
]

COLUMNAS_RECUPERADAS = [
    "ano", "semana", "fecha_inicio", "fecha_fin",
    "ubigeo", "departamento", "provincia", "distrito",
    "tmean", "tmax", "tmin", "humr",
    "ptot", "ptot_raw", "n_horas", "n_dias",
    "n_horas_ptot", "metodo_extraccion",
    "buffer_m", "fuente_climatica"
]


# ============================================================
# 1. FUNCIONES
# ============================================================

def detener(mensaje):
    raise ValueError(mensaje)


def leer_csv(ruta):
    if not ruta.exists():
        detener(f"Archivo inexistente: {ruta}")

    df = pd.read_csv(
        ruta,
        dtype={"ubigeo": "string"},
        low_memory=False
    )

    df.columns = df.columns.str.strip()

    return df


def preparar_claves(df, nombre):

    for columna in CLAVES:
        if columna not in df.columns:
            detener(f"{nombre}: falta columna {columna}")

    df["ubigeo"] = (
        df["ubigeo"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    df["ano"] = pd.to_numeric(
        df["ano"], errors="raise"
    ).astype(int)

    df["semana"] = pd.to_numeric(
        df["semana"], errors="raise"
    ).astype(int)

    if df[CLAVES].isna().any().any():
        detener(f"{nombre}: claves nulas.")

    df["_key"] = (
        df["ano"].astype(str)
        + "|"
        + df["ubigeo"]
        + "|"
        + df["semana"].astype(str)
    )

    if df["_key"].duplicated().any():
        detener(f"{nombre}: claves duplicadas.")

    return df


def fechas_validas(df, columna, nombre):

    fechas = pd.to_datetime(
        df[columna],
        errors="coerce"
    )

    if fechas.isna().any():
        detener(f"{nombre}: fechas invalidas en {columna}")

    return fechas.dt.normalize()


def normalizar_texto(serie):

    return (
        serie.astype("string")
        .fillna("")
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )


# ============================================================
# 2. VALIDAR QUE LOS OTROS 1878 DISTRITOS NO CAMBIEN
# ============================================================

def verificar_distritos_no_recuperados(original, resultado, mascara):

    a = original.loc[~mascara].reset_index(drop=True)
    b = resultado.loc[~mascara].reset_index(drop=True)

    for columna in original.columns:

        if columna in GEOGRAFICAS:

            # Comparamos los valores textuales y los nulos.
            # No importa si Pandas los interpreta como float,
            # object o string.

            valor_a = (
                a[columna]
                .astype("string")
                .fillna("__NULO__")
                .str.strip()
            )

            valor_b = (
                b[columna]
                .astype("string")
                .fillna("__NULO__")
                .str.strip()
            )

            if not valor_a.equals(valor_b):
                return False, columna

        else:

            # Para las demas columnas se comparan los valores
            # reales, ignorando exclusivamente el tipo de dato.

            try:

                pd.testing.assert_series_equal(
                    a[columna],
                    b[columna],
                    check_dtype=False,
                    check_exact=True,
                    check_names=False
                )

            except AssertionError:

                return False, columna

    return True, None


# ============================================================
# 3. PROCESAMIENTO PRINCIPAL
# ============================================================

def main():

    print("=" * 65)
    print("INTEGRACION CLIMATICA DEFINITIVA 2000-2025")
    print("=" * 65)

    archivos = []

    for anio in ANIOS:

        original = (
            ORIGINAL_DIR /
            f"clima_dengue_peru_{anio}.csv"
        )

        recuperado = (
            RECUPERADO_DIR /
            f"CLIMA_RECUPERADO_{anio}.csv"
        )

        if not original.exists():
            detener(f"Falta archivo original {anio}")

        if not recuperado.exists():
            detener(f"Falta archivo recuperado {anio}")

        archivos.append((anio, original, recuperado))

    print(f"\nArchivos originales: {len(archivos)}")
    print(f"Archivos recuperados: {len(archivos)}")

    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    resumen = []
    detalles = []

    try:

        # ====================================================
        # 4. RECORRER LOS 26 AÑOS
        # ====================================================

        for anio, ruta_original, ruta_recuperada in archivos:

            print("\n" + "=" * 60)
            print(f"PROCESANDO ANIO: {anio}")
            print("=" * 60)

            original = leer_csv(ruta_original)
            recuperado = leer_csv(ruta_recuperada)

            # -----------------------------------------------
            # 4.1 ESTRUCTURA
            # -----------------------------------------------

            faltantes_o = (
                set(COLUMNAS_ORIGINALES)
                - set(original.columns)
            )

            faltantes_r = (
                set(COLUMNAS_RECUPERADAS)
                - set(recuperado.columns)
            )

            if faltantes_o:
                detener(f"{anio}: faltan columnas originales {faltantes_o}")

            if faltantes_r:
                detener(f"{anio}: faltan columnas recuperadas {faltantes_r}")

            original = preparar_claves(
                original, f"ORIGINAL {anio}"
            )

            recuperado = preparar_claves(
                recuperado, f"RECUPERADO {anio}"
            )

            if not original["ano"].eq(anio).all():
                detener(f"{anio}: año incorrecto en original")

            if not recuperado["ano"].eq(anio).all():
                detener(f"{anio}: año incorrecto en recuperado")

            # -----------------------------------------------
            # 4.2 COBERTURA ORIGINAL
            # -----------------------------------------------

            distritos = original["ubigeo"].nunique()

            if distritos != TOTAL_DISTRITOS:
                detener(f"{anio}: no hay 1891 distritos")

            semanas = sorted(original["semana"].unique().tolist())

            if semanas not in [
                list(range(1, 53)),
                list(range(1, 54))
            ]:
                detener(f"{anio}: calendario incorrecto")

            total_semanas = len(semanas)

            esperados = TOTAL_DISTRITOS * total_semanas

            if len(original) != esperados:
                detener(f"{anio}: registros originales incompletos")

            cobertura = original.groupby("ubigeo")["semana"].apply(
                lambda x: set(x)
            )

            if not cobertura.apply(
                lambda x: x == set(semanas)
            ).all():
                detener(f"{anio}: cobertura original incompleta")

            # -----------------------------------------------
            # 4.3 COBERTURA RECUPERADA
            # -----------------------------------------------

            ubigeos = set(recuperado["ubigeo"].unique())

            if ubigeos != UBIGEOS:
                detener(f"{anio}: UBIGEO recuperados incorrectos")

            if len(recuperado) != 13 * total_semanas:
                detener(f"{anio}: registros recuperados incorrectos")

            cobertura_rec = recuperado.groupby("ubigeo")["semana"].apply(
                lambda x: set(x)
            )

            if not cobertura_rec.apply(
                lambda x: x == set(semanas)
            ).all():
                detener(f"{anio}: cobertura recuperada incompleta")

            # -----------------------------------------------
            # 4.4 EMPAREJAR REGISTROS
            # -----------------------------------------------

            indice = original.set_index("_key", drop=False)

            if not recuperado["_key"].isin(indice.index).all():
                detener(f"{anio}: registros sin correspondencia")

            alineado = (
                indice.loc[recuperado["_key"].tolist()]
                .reset_index(drop=True)
            )

            rec = recuperado.reset_index(drop=True)

            # -----------------------------------------------
            # 4.5 VALIDAR FECHAS
            # -----------------------------------------------

            inicio_o = fechas_validas(
                alineado, "fecha_inicio", "ORIGINAL"
            )

            inicio_r = fechas_validas(
                rec, "fecha_inicio", "RECUPERADO"
            )

            fin_o = fechas_validas(
                alineado, "fecha_fin", "ORIGINAL"
            )

            fin_r = fechas_validas(
                rec, "fecha_fin", "RECUPERADO"
            )

            diferencia_inicio = (
                inicio_r - inicio_o
            ).dt.days

            diferencia_fin = (
                fin_r - fin_o
            ).dt.days

            if not diferencia_inicio.eq(0).all():
                detener(f"{anio}: fechas de inicio diferentes")

            if not diferencia_fin.eq(1).all():
                detener(f"{anio}: diferencia inesperada en fecha final")

            fin_normalizado = (
                fin_r - pd.Timedelta(days=1)
            )

            if not fin_normalizado.equals(fin_o):
                detener(f"{anio}: normalizacion de fechas incorrecta")

            # -----------------------------------------------
            # 4.6 VALIDAR VARIABLES CLIMATICAS
            # -----------------------------------------------

            for columna in NUMERICAS_RECUPERADAS:

                rec[columna] = pd.to_numeric(
                    rec[columna],
                    errors="coerce"
                )

                if rec[columna].isna().any():
                    detener(f"{anio}: nulos en {columna}")

            if not (
                (rec["tmin"] <= rec["tmean"])
                & (rec["tmean"] <= rec["tmax"])
            ).all():
                detener(f"{anio}: temperaturas inconsistentes")

            if not rec["humr"].between(0, 100).all():
                detener(f"{anio}: humedad fuera de rango")

            if (rec["ptot"] < 0).any():
                detener(f"{anio}: precipitacion negativa")

            if not rec["n_dias"].eq(7).all():
                detener(f"{anio}: dias incompletos")

            if not rec["n_horas"].eq(168).all():
                detener(f"{anio}: horas de temperatura incompletas")

            if not rec["n_horas_ptot"].eq(168).all():
                detener(f"{anio}: horas de precipitacion incompletas")

            buffer = pd.to_numeric(
                rec["buffer_m"], errors="coerce"
            )

            if buffer.isna().any() or not buffer.eq(BUFFER).all():
                detener(f"{anio}: buffer incorrecto")

            # -----------------------------------------------
            # 4.7 VALIDAR DATOS GEOGRAFICOS
            # -----------------------------------------------

            for columna in GEOGRAFICAS:

                if (
                    rec[columna].isna().any()
                    or rec[columna].astype("string")
                    .str.strip().eq("").any()
                ):
                    detener(f"{anio}: datos geograficos vacios en {columna}")

                geo_original = normalizar_texto(
                    alineado[columna]
                )

                geo_recuperado = normalizar_texto(
                    rec[columna]
                )

                conflictos = (
                    geo_original.ne("")
                    & geo_recuperado.ne("")
                    & geo_original.ne(geo_recuperado)
                )

                if conflictos.any():
                    detener(
                        f"{anio}: conflicto geografico en {columna}"
                    )

            # -----------------------------------------------
            # 4.8 VALIDAR CONFLICTOS CLIMATICOS
            # -----------------------------------------------

            for columna in CLIMATICAS:

                valores_originales = pd.to_numeric(
                    alineado[columna],
                    errors="coerce"
                )

                invalidos = (
                    alineado[columna].notna()
                    & valores_originales.isna()
                )

                if invalidos.any():
                    detener(
                        f"{anio}: valores no numericos en {columna}"
                    )

                conflictos = (
                    valores_originales.notna()
                    & (
                        valores_originales - rec[columna]
                    ).abs().gt(0.000001)
                )

                if conflictos.any():
                    detener(
                        f"{anio}: conflicto climatico en {columna}"
                    )

            # -----------------------------------------------
            # 4.9 PREPARAR CONSOLIDACION
            # -----------------------------------------------

            salida = original.copy()

            mascara = salida["_key"].isin(
                set(rec["_key"])
            )

            if int(mascara.sum()) != len(rec):
                detener(f"{anio}: cantidad incorrecta de filas seleccionadas")

            indice_rec = rec.set_index("_key", drop=False)

            filas_nulas = int(
                alineado[CLIMATICAS].isna().all(axis=1).sum()
            )

            filas_completas = int(
                alineado[CLIMATICAS].notna().all(axis=1).sum()
            )

            celdas_completadas = 0

            # -----------------------------------------------
            # 4.10 RECUPERAR VARIABLES CLIMATICAS
            # -----------------------------------------------

            for columna in CLIMATICAS:

                valores_originales = pd.to_numeric(
                    salida.loc[mascara, columna],
                    errors="coerce"
                )

                valores_nuevos = (
                    salida.loc[mascara, "_key"]
                    .map(indice_rec[columna])
                )

                celdas_completadas += int(
                    valores_originales.isna().sum()
                )

                salida.loc[mascara, columna] = (
                    valores_originales
                    .fillna(valores_nuevos)
                    .to_numpy()
                )

            # -----------------------------------------------
            # 4.11 RECUPERAR GEOGRAFIA
            # -----------------------------------------------

            # IMPORTANTE:
            # Usamos object, no StringDtype para toda la columna.
            # Los valores de los distritos no seleccionados
            # permanecen intactos, incluidos sus valores nulos.

            for columna in GEOGRAFICAS:

                salida[columna] = salida[columna].astype(object)

                actuales = (
                    salida.loc[mascara, columna]
                    .astype("string")
                    .str.strip()
                )

                nuevos = (
                    salida.loc[mascara, "_key"]
                    .map(indice_rec[columna])
                    .astype("string")
                    .str.strip()
                )

                actuales = actuales.mask(actuales.eq(""))

                finales = actuales.fillna(nuevos)

                if finales.isna().any():
                    detener(
                        f"{anio}: no se pudo recuperar {columna}"
                    )

                salida.loc[mascara, columna] = (
                    finales.astype(object).to_numpy()
                )

            # -----------------------------------------------
            # 4.12 VALIDAR RESULTADO RECUPERADO
            # -----------------------------------------------

            if salida.loc[mascara, CLIMATICAS].isna().any().any():
                detener(f"{anio}: quedan nulos climaticos")

            for columna in GEOGRAFICAS:

                valores = (
                    salida.loc[mascara, columna]
                    .astype("string")
                    .str.strip()
                )

                if valores.isna().any() or valores.eq("").any():
                    detener(f"{anio}: quedan nulos geograficos")

            # -----------------------------------------------
            # 4.13 VERIFICAR LOS OTROS DISTRITOS
            # -----------------------------------------------

            correcto, columna = verificar_distritos_no_recuperados(
                original,
                salida,
                mascara
            )

            if not correcto:
                detener(
                    f"{anio}: cambio real detectado en "
                    f"distritos no recuperados. Columna: {columna}"
                )

            print("Verificacion de los otros 1878 distritos: OK")

            # -----------------------------------------------
            # 4.14 VERIFICAR COLUMNAS NO INTERVENIDAS
            # -----------------------------------------------

            columnas_protegidas = [
                c for c in original.columns
                if c not in CLIMATICAS + GEOGRAFICAS + ["_key"]
            ]

            for columna in columnas_protegidas:

                try:
                    pd.testing.assert_series_equal(
                        original[columna],
                        salida[columna],
                        check_dtype=False,
                        check_exact=True,
                        check_names=False
                    )
                except AssertionError:
                    detener(
                        f"{anio}: cambio no autorizado en {columna}"
                    )

            # -----------------------------------------------
            # 4.15 GUARDAR ARCHIVO TEMPORAL
            # -----------------------------------------------

            archivo_salida = (
                STAGING_DIR /
                f"clima_dengue_peru_{anio}.csv"
            )

            salida.drop(
                columns=["_key"]
            ).to_csv(
                archivo_salida,
                index=False,
                encoding="utf-8-sig"
            )

            # -----------------------------------------------
            # 4.16 AUDITORIA DETALLADA
            # -----------------------------------------------

            detalle = rec[
                [
                    "ano", "ubigeo", "semana",
                    "departamento", "provincia", "distrito"
                ] + CLIMATICAS + [
                    "metodo_extraccion",
                    "buffer_m",
                    "fuente_climatica"
                ]
            ].copy()

            detalle["fecha_inicio"] = (
                inicio_r.dt.strftime("%Y-%m-%d").to_numpy()
            )

            detalle["fecha_fin_original"] = (
                fin_o.dt.strftime("%Y-%m-%d").to_numpy()
            )

            detalle["fecha_fin_recuperada"] = (
                fin_r.dt.strftime("%Y-%m-%d").to_numpy()
            )

            detalle["fecha_fin_normalizada"] = (
                fin_normalizado.dt.strftime("%Y-%m-%d").to_numpy()
            )

            detalles.append(detalle)

            # -----------------------------------------------
            # 4.17 RESUMEN ANUAL
            # -----------------------------------------------

            resumen.append({

                "anio": anio,
                "registros_originales": len(original),
                "registros_recuperados": len(rec),
                "distritos_originales": distritos,
                "distritos_recuperados": len(ubigeos),
                "semanas": total_semanas,
                "filas_completamente_nulas_antes": filas_nulas,
                "filas_completas_antes": filas_completas,
                "celdas_completadas": celdas_completadas,
                "diferencias_inicio": int(
                    diferencia_inicio.ne(0).sum()
                ),
                "diferencias_fin_antes": int(
                    diferencia_fin.ne(0).sum()
                ),
                "diferencias_fin_normalizadas": int(
                    (fin_normalizado != fin_o).sum()
                ),
                "duplicados": 0,
                "estado": "OK"

            })

            print(f"Registros originales: {len(original):,}")
            print(f"Registros recuperados: {len(rec):,}")
            print(f"Distritos originales: {distritos}")
            print(f"Distritos recuperados: {len(ubigeos)}")
            print(f"Semanas: {total_semanas}")
            print(f"Filas climaticas completamente nulas: {filas_nulas}")
            print(f"Celdas completadas: {celdas_completadas}")
            print("Fechas: OK")
            print("Variables climaticas: OK")
            print("Geografia: OK")
            print("Duplicados: 0")
            print("ESTADO: OK")

        # ====================================================
        # 5. GENERAR REPORTES
        # ====================================================

        REPORT_DIR.mkdir(parents=True, exist_ok=True)

        df_resumen = pd.DataFrame(resumen)

        df_detalles = pd.concat(
            detalles,
            ignore_index=True
        )

        df_ubigeos = (
            df_detalles.groupby(
                ["ubigeo", "departamento", "provincia", "distrito"],
                as_index=False
            )
            .agg(
                registros_integrados=("semana", "size"),
                anios=("ano", "nunique"),
                semanas_distintas=("semana", "nunique"),
                primera_fecha=("fecha_inicio", "min"),
                ultima_fecha=("fecha_fin_normalizada", "max")
            )
        )

        df_resumen.to_csv(
            REPORT_DIR / "70_resumen_integracion.csv",
            index=False,
            encoding="utf-8-sig"
        )

        df_detalles.to_csv(
            REPORT_DIR / "71_detalle_integracion.csv",
            index=False,
            encoding="utf-8-sig"
        )

        df_ubigeos.to_csv(
            REPORT_DIR / "72_ubigeos_integrados.csv",
            index=False,
            encoding="utf-8-sig"
        )

        # ====================================================
        # 6. PUBLICACION CONTROLADA
        # ====================================================

        print("\n" + "=" * 65)
        print("PUBLICANDO ARCHIVOS CONSOLIDADOS")
        print("=" * 65)

        respaldo = None

        if OUTPUT_DIR.exists():

            marca = datetime.now().strftime(
                "%Y%m%d_%H%M%S_%f"
            )

            respaldo = (
                PROCESSED_DIR /
                f"clima_integrado_respaldo_{marca}"
            )

            OUTPUT_DIR.rename(respaldo)

            print(f"Respaldo anterior: {respaldo}")

        try:

            STAGING_DIR.rename(OUTPUT_DIR)

        except Exception:

            if (
                respaldo is not None
                and respaldo.exists()
                and not OUTPUT_DIR.exists()
            ):
                respaldo.rename(OUTPUT_DIR)

            raise

        # ====================================================
        # 7. RESUMEN FINAL
        # ====================================================

        print("\n" + "=" * 65)
        print("INTEGRACION CLIMATICA COMPLETADA")
        print("=" * 65)

        print(
            df_resumen[
                [
                    "anio",
                    "registros_originales",
                    "registros_recuperados",
                    "semanas",
                    "estado"
                ]
            ].to_string(index=False)
        )

        print("\nRESUMEN GENERAL")

        print(f"Años integrados: {len(df_resumen)}")

        print(
            f"Registros recuperados: {len(df_detalles):,}"
        )

        print(
            f"UBIGEO integrados: {df_ubigeos['ubigeo'].nunique()}"
        )

        print(
            f"Archivos consolidados: "
            f"{len(list(OUTPUT_DIR.glob('*.csv')))}"
        )

        print("\nCARPETA CONSOLIDADA:")
        print(OUTPUT_DIR)

        print("\nREPORTES:")
        print(REPORT_DIR)

        print("\nARCHIVOS ORIGINALES NO MODIFICADOS.")

        print("=" * 65)

    except Exception:

        if STAGING_DIR.exists():
            shutil.rmtree(STAGING_DIR)

        raise


# ============================================================
# 8. EJECUCION
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print("\n" + "=" * 65)
        print("INTEGRACION CANCELADA")
        print("=" * 65)

        print(f"MOTIVO:\n{error}")

        print("\nNo se modificaron los archivos originales.")
        print("No se publicaron archivos consolidados.")

        sys.exit(1)
