from pathlib import Path
import os
import re
import sqlite3
import sys
import gzip

import pandas as pd


# ============================================================
# 1. CONFIGURACION
# ============================================================

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

CLIMA_ORIGINAL = BASE / "data/raw/clima/era5_land"
CLIMA_RECUPERADO = (
    BASE / "data/processed/clima/"
    "recuperado_13_distritos_fecha_corregida"
)
MINSA = BASE / "data/raw/epidemiologia/data1.csv"
POBLACION = BASE / "data/raw/poblacion/Limpia.xlsx"
GEOGRAFIA = BASE / "data/raw/geografia/DISTRITO.gpkg"

SALIDA = BASE / "data/processed/dataset_maestro"
REPORTES = BASE / "reports/integracion_dataset_maestro"

ARCHIVO_FINAL = SALIDA / "dataset_maestro_dengue_2000_2025.csv.gz"
ARCHIVO_TEMPORAL = SALIDA / "dataset_maestro_2000_2025.tmp.gz"

ANIOS = list(range(2000, 2026))
KEYS = ["ubigeo", "ano", "semana"]

VARIABLES_CLIMATICAS = [
    "tmean", "tmax", "tmin", "humr",
    "ptot", "ptot_raw", "n_dias", "n_horas"
]

VARIABLES_CASOS = [
    "casos_dengue_reportados",
    "casos_tipo_dx_C",
    "casos_tipo_dx_P",
    "casos_tipo_dx_otro",
    "casos_sexo_M",
    "casos_sexo_F",
    "casos_sexo_otro",
]


# ============================================================
# 2. FUNCIONES GENERALES
# ============================================================

def limpiar_ubigeo(serie):
    """Normaliza UBIGEO como texto de seis digitos."""
    serie = serie.astype("string").str.strip()
    serie = serie.str.replace(r"\.0$", "", regex=True)
    serie = serie.replace({
        "": pd.NA,
        "nan": pd.NA,
        "None": pd.NA,
        "<NA>": pd.NA,
    })
    return serie.str.zfill(6)


def limpiar_ubigeo_individual(valor):
    if pd.isna(valor):
        return None

    texto = str(valor).strip()
    texto = re.sub(r"\.0$", "", texto)

    if not texto.isdigit():
        return None

    texto = texto.zfill(6)

    if len(texto) != 6:
        return None

    return texto


def normalizar_claves(df):
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]

    faltantes = set(KEYS) - set(df.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas clave: {sorted(faltantes)}")

    df["ubigeo"] = limpiar_ubigeo(df["ubigeo"])
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce")
    df["semana"] = pd.to_numeric(df["semana"], errors="coerce")

    if df[KEYS].isna().any().any():
        raise ValueError("Hay claves UBIGEO, ano o semana vacias.")

    df["ano"] = df["ano"].astype(int)
    df["semana"] = df["semana"].astype(int)
    return df


def verificar_archivos():
    for archivo in [MINSA, POBLACION, GEOGRAFIA]:
        if not archivo.exists():
            raise FileNotFoundError(f"No se encontro: {archivo}")

    originales = {
        int(re.search(r"(20\d{2})", f.name).group(1))
        for f in CLIMA_ORIGINAL.glob("clima_dengue_peru_*.csv")
    }
    recuperados = {
        int(re.search(r"(20\d{2})", f.name).group(1))
        for f in CLIMA_RECUPERADO.glob("CLIMA_RECUPERADO_*.csv")
    }

    esperados = set(ANIOS)

    if originales != esperados:
        raise ValueError(
            f"Archivos climaticos originales incompletos. "
            f"Faltan: {sorted(esperados - originales)}"
        )

    if recuperados != esperados:
        raise ValueError(
            f"Archivos climaticos recuperados incompletos. "
            f"Faltan: {sorted(esperados - recuperados)}"
        )


# ============================================================
# 3. CARGAR GEOGRAFIA
# ============================================================

def cargar_geografia():
    print("\nCARGANDO GEOGRAFIA...")

    with sqlite3.connect(str(GEOGRAFIA)) as conexion:
        geo = pd.read_sql_query(
            """
            SELECT ubigeo, nombdep, nombprov, nombdist
            FROM DISTRITO
            """,
            conexion
        )

    geo["ubigeo"] = limpiar_ubigeo(geo["ubigeo"])
    geo = geo.rename(columns={
        "nombdep": "nombre_departamento_geografico",
        "nombprov": "nombre_provincia_geografico",
        "nombdist": "nombre_distrito_geografico",
    })

    if geo["ubigeo"].isna().any():
        raise ValueError("La geografia contiene UBIGEO vacios.")

    if geo["ubigeo"].duplicated().any():
        raise ValueError("La geografia contiene UBIGEO duplicados.")

    # El GeoPackage disponible contiene 1,890 UBIGEO.
    # El clima contiene 1,891. No detenemos la integracion:
    # el distrito faltante conservara los nombres del clima.
    print("DISTRITOS GEOGRAFICOS EN GEOPACKAGE:", len(geo))
    return geo


# ============================================================
# 4. CARGAR POBLACION INEI
# ============================================================

def cargar_poblacion():
    print("\nPROCESANDO POBLACION INEI...")

    raw = pd.read_excel(
        POBLACION,
        sheet_name=0,
        header=None,
        dtype=object,
    )

    fila_encabezado = None
    columna_ubigeo = None

    for i in range(min(25, len(raw))):
        valores = [
            str(x).strip().upper()
            for x in raw.iloc[i].tolist()
        ]
        if "UBIGEO" in valores:
            fila_encabezado = i
            columna_ubigeo = valores.index("UBIGEO")
            break

    if fila_encabezado is None:
        raise ValueError("No se encontro el encabezado UBIGEO en poblacion.")

    fila_anios = fila_encabezado + 1
    columnas_anios = {}

    for j, valor in enumerate(raw.iloc[fila_anios].tolist()):
        try:
            anio = int(float(str(valor).strip()))
            if 2018 <= anio <= 2025:
                columnas_anios[j] = anio
        except (ValueError, TypeError):
            continue

    if not columnas_anios:
        raise ValueError("No se encontraron columnas de poblacion 2018-2025.")

    registros = []

    for _, fila in raw.iloc[fila_anios + 1:].iterrows():
        ubigeo = limpiar_ubigeo_individual(fila.iloc[columna_ubigeo])

        if ubigeo is None:
            continue

        # Excluir Peru, departamentos y provincias.
        if ubigeo == "000000" or ubigeo.endswith("00"):
            continue

        for columna, anio in columnas_anios.items():
            valor = pd.to_numeric(
                pd.Series([fila.iloc[columna]]),
                errors="coerce"
            ).iloc[0]

            if pd.isna(valor):
                continue

            registros.append({
                "ubigeo": ubigeo,
                "ano": anio,
                "poblacion_proyectada": float(valor),
            })

    poblacion = pd.DataFrame(registros)

    if poblacion.empty:
        raise ValueError("La tabla de poblacion quedo vacia.")

    # La poblacion es anual: su clave es UBIGEO + ANO.
    # No tiene columna semana.
    if poblacion.duplicated(["ubigeo", "ano"]).any():
        raise ValueError("La poblacion contiene UBIGEO-anio duplicados.")

    print("REGISTROS DE POBLACION:", f"{len(poblacion):,}")
    print("ANIOS DISPONIBLES:", sorted(poblacion["ano"].unique()))
    return poblacion


# ============================================================
# 5. AGREGAR EPIDEMIOLOGIA MINSA
# ============================================================

def cargar_epidemiologia():
    print("\nPROCESANDO EPIDEMIOLOGIA MINSA...")
    print("LECTURA POR BLOQUES DE 250,000 FILAS.")

    partes = []
    estadisticas = {
        "registros_dengue_total": 0,
        "registros_dengue_validos": 0,
        "registros_fuera_periodo": 0,
        "registros_sin_ubigeo": 0,
    }

    lector = pd.read_csv(
        MINSA,
        sep=",",
        encoding="utf-8-sig",
        dtype="string",
        chunksize=250000,
        keep_default_na=False,
    )

    for numero, bloque in enumerate(lector, start=1):
        bloque.columns = [str(c).strip().lower() for c in bloque.columns]

        requeridas = [
            "enfermedad", "ano", "semana",
            "ubigeo", "tipo_dx", "sexo"
        ]
        faltantes = [c for c in requeridas if c not in bloque.columns]

        if faltantes:
            raise ValueError(f"Columnas faltantes en MINSA: {faltantes}")

        mascara = bloque["enfermedad"].str.contains(
            "DENGUE", case=False, na=False
        )
        dengue = bloque.loc[mascara].copy()

        if dengue.empty:
            continue

        estadisticas["registros_dengue_total"] += len(dengue)

        dengue["ubigeo"] = limpiar_ubigeo(dengue["ubigeo"])
        dengue["ano"] = pd.to_numeric(dengue["ano"], errors="coerce")
        dengue["semana"] = pd.to_numeric(
            dengue["semana"], errors="coerce"
        )

        periodo_ok = (
            dengue["ano"].between(2000, 2025)
            & dengue["semana"].between(1, 53)
        )
        ubigeo_ok = dengue["ubigeo"].str.fullmatch(
            r"\d{6}", na=False
        )

        estadisticas["registros_fuera_periodo"] += int((~periodo_ok).sum())
        estadisticas["registros_sin_ubigeo"] += int(
            (periodo_ok & ~ubigeo_ok).sum()
        )

        validos = dengue.loc[periodo_ok & ubigeo_ok].copy()
        if validos.empty:
            continue

        validos["ano"] = validos["ano"].astype(int)
        validos["semana"] = validos["semana"].astype(int)

        tipo = validos["tipo_dx"].str.strip().str.upper()
        sexo = validos["sexo"].str.strip().str.upper()

        validos["_uno"] = 1
        validos["_C"] = (tipo == "C").astype("int8")
        validos["_P"] = (tipo == "P").astype("int8")
        validos["_OTRO"] = (~tipo.isin(["C", "P"])).astype("int8")
        validos["_M"] = (sexo == "M").astype("int8")
        validos["_F"] = (sexo == "F").astype("int8")
        validos["_SEXO_OTRO"] = (~sexo.isin(["M", "F"])).astype("int8")

        agrupado = validos.groupby(KEYS, as_index=False).agg(
            casos_dengue_reportados=("_uno", "sum"),
            casos_tipo_dx_C=("_C", "sum"),
            casos_tipo_dx_P=("_P", "sum"),
            casos_tipo_dx_otro=("_OTRO", "sum"),
            casos_sexo_M=("_M", "sum"),
            casos_sexo_F=("_F", "sum"),
            casos_sexo_otro=("_SEXO_OTRO", "sum"),
        )

        partes.append(agrupado)
        estadisticas["registros_dengue_validos"] += len(validos)

        print(
            f"Bloque {numero}: {len(dengue):,} filas de dengue; "
            f"{len(validos):,} validas."
        )

    if not partes:
        raise ValueError("No se encontraron registros de dengue validos.")

    casos = pd.concat(partes, ignore_index=True)
    casos = casos.groupby(KEYS, as_index=False)[VARIABLES_CASOS].sum()

    print("\nAGREGACION MINSA COMPLETADA")
    print("FILAS MINSA CON DENGUE:", f"{estadisticas['registros_dengue_total']:,}")
    print("FILAS MINSA VALIDAS:", f"{estadisticas['registros_dengue_validos']:,}")
    print("GRUPOS UBIGEO-ANIO-SEMANA:", f"{len(casos):,}")

    return casos, estadisticas


# ============================================================
# 6. INTEGRAR CLIMA, GEOGRAFIA, POBLACION Y MINSA POR ANIO
# ============================================================

def integrar_anio(anio, geo, poblacion, casos, ubigeos_recuperados):
    archivo_original = CLIMA_ORIGINAL / f"clima_dengue_peru_{anio}.csv"
    archivo_recuperado = CLIMA_RECUPERADO / f"CLIMA_RECUPERADO_{anio}.csv"

    original = pd.read_csv(
        archivo_original,
        encoding="utf-8-sig",
        dtype={"ubigeo": "string"},
    )
    recuperado = pd.read_csv(
        archivo_recuperado,
        encoding="utf-8-sig",
        dtype={"ubigeo": "string"},
    )

    original = normalizar_claves(original)
    recuperado = normalizar_claves(recuperado)

    if not (original["ano"] == anio).all():
        raise ValueError(f"{anio}: anio incorrecto en clima original.")
    if not (recuperado["ano"] == anio).all():
        raise ValueError(f"{anio}: anio incorrecto en recuperado.")

    for df in (original, recuperado):
        for fecha in ("fecha_inicio", "fecha_fin"):
            if fecha not in df.columns:
                raise ValueError(f"{anio}: falta la columna {fecha}.")
            df[fecha] = df[fecha].astype("string").str.slice(0, 10)

    if original.duplicated(KEYS).any():
        raise ValueError(f"{anio}: claves duplicadas en clima original.")
    if recuperado.duplicated(KEYS).any():
        raise ValueError(f"{anio}: claves duplicadas en recuperado.")

    semanas = original["semana"].nunique()

    if original["ubigeo"].nunique() != 1891:
        raise ValueError(f"{anio}: el clima original no contiene 1,891 distritos.")
    if len(original) != 1891 * semanas:
        raise ValueError(f"{anio}: cobertura incompleta del clima original.")

    codigos_anio = set(recuperado["ubigeo"].dropna().unique())
    if len(codigos_anio) != 13 or codigos_anio != ubigeos_recuperados:
        raise ValueError(f"{anio}: los 13 UBIGEO recuperados no coinciden.")
    if len(recuperado) != 13 * semanas:
        raise ValueError(f"{anio}: cantidad incorrecta de filas recuperadas.")

    fechas = recuperado[KEYS + ["fecha_inicio", "fecha_fin"]].merge(
        original[KEYS + ["fecha_inicio", "fecha_fin"]],
        on=KEYS,
        how="left",
        suffixes=("_rec", "_orig"),
        indicator=True,
        validate="one_to_one",
    )

    if (fechas["_merge"] != "both").any():
        raise ValueError(f"{anio}: hay semanas recuperadas sin correspondencia.")

    for fecha in ("fecha_inicio", "fecha_fin"):
        if (fechas[f"{fecha}_rec"] != fechas[f"{fecha}_orig"]).any():
            raise ValueError(f"{anio}: diferencias en {fecha}.")

    columnas_rec = VARIABLES_CLIMATICAS + [
        "n_horas_ptot", "pixeles_tmean", "pixeles_humr",
        "pixeles_ptot", "fuente_climatica",
        "metodo_extraccion", "buffer_m",
    ]
    faltantes = [c for c in columnas_rec if c not in recuperado.columns]
    if faltantes:
        raise ValueError(f"{anio}: faltan columnas recuperadas: {faltantes}")

    columnas_numericas = [
        "tmean", "tmax", "tmin", "humr", "ptot", "ptot_raw",
        "n_dias", "n_horas", "n_horas_ptot",
        "pixeles_tmean", "pixeles_humr", "pixeles_ptot", "buffer_m",
    ]
    for columna in columnas_numericas:
        recuperado[columna] = pd.to_numeric(
            recuperado[columna], errors="coerce"
        )
        if recuperado[columna].isna().any():
            raise ValueError(f"{anio}: valores vacios en {columna} recuperada.")

    if not (recuperado["n_horas"] == 168).all():
        raise ValueError(f"{anio}: n_horas no es 168.")
    if not (recuperado["n_horas_ptot"] == 168).all():
        raise ValueError(f"{anio}: n_horas_ptot no es 168.")
    if not (recuperado["n_dias"] == 7).all():
        raise ValueError(f"{anio}: n_dias no es 7.")
    if not (
        (recuperado["tmin"] <= recuperado["tmean"])
        & (recuperado["tmean"] <= recuperado["tmax"])
    ).all():
        raise ValueError(f"{anio}: inconsistencia entre temperaturas.")
    if not recuperado["humr"].between(0, 100).all():
        raise ValueError(f"{anio}: humedad fuera de rango.")
    if (recuperado["ptot"] < 0).any():
        raise ValueError(f"{anio}: precipitacion negativa.")

    recuperado = recuperado[KEYS + columnas_rec].rename(
        columns={c: f"rec_{c}" for c in columnas_rec}
    )

    df = original.merge(
        recuperado,
        on=KEYS,
        how="left",
        validate="one_to_one",
    )

    mascara = df["rec_metodo_extraccion"].notna()
    if int(mascara.sum()) != len(recuperado):
        raise ValueError(f"{anio}: no se integraron todos los registros recuperados.")

    # Reemplazar variables climaticas solo en los 13 distritos recuperados.
    for variable in VARIABLES_CLIMATICAS:
        df.loc[mascara, variable] = df.loc[
            mascara, f"rec_{variable}"
        ].to_numpy()

    df["clima_recuperado"] = mascara.astype("int8")
    df["clima_grupo"] = "OTROS_DISTRITOS"
    df.loc[mascara, "clima_grupo"] = "13_RECUPERADOS"

    df["clima_metodo_extraccion"] = "ORIGINAL_ERA5_LAND"
    df.loc[mascara, "clima_metodo_extraccion"] = (
        df.loc[mascara, "rec_metodo_extraccion"]
    )

    df["clima_fuente_detalle"] = df["fuente"].astype("string")
    df.loc[mascara, "clima_fuente_detalle"] = (
        df.loc[mascara, "rec_fuente_climatica"]
    )

    for origen, destino in [
        ("rec_buffer_m", "clima_buffer_m"),
        ("rec_n_horas_ptot", "clima_n_horas_ptot"),
        ("rec_pixeles_tmean", "clima_pixeles_tmean"),
        ("rec_pixeles_humr", "clima_pixeles_humr"),
        ("rec_pixeles_ptot", "clima_pixeles_ptot"),
    ]:
        df[destino] = df[origen]

    df.drop(
        columns=[c for c in df.columns if c.startswith("rec_")],
        inplace=True,
    )

    # Geografia: se permiten 1,890 UBIGEO. El faltante conserva
    # departamento/provincia/distrito desde el archivo climatico.
    df = df.merge(geo, on="ubigeo", how="left", validate="many_to_one")
    df["geografia_disponible"] = (
        df["nombre_departamento_geografico"].notna().astype("int8")
    )

    for columna, columna_geo in [
        ("departamento", "nombre_departamento_geografico"),
        ("provincia", "nombre_provincia_geografico"),
        ("distrito", "nombre_distrito_geografico"),
    ]:
        if columna not in df.columns:
            df[columna] = pd.NA
        df[columna] = (
            df[columna].astype("string").str.strip()
            .replace("", pd.NA)
            .fillna(df[columna_geo])
        )

    # Poblacion: clave anual UBIGEO + ANO, sin semana.
    df = df.merge(
        poblacion,
        on=["ubigeo", "ano"],
        how="left",
        validate="many_to_one",
    )

    casos_anio = casos.loc[casos["ano"] == anio].copy()

    if not casos_anio.empty:
        comparacion = casos_anio[KEYS].merge(
            df[KEYS],
            on=KEYS,
            how="left",
            indicator=True,
            validate="one_to_one",
        )
        claves_sin_match = comparacion.loc[
            comparacion["_merge"] == "left_only", KEYS
        ]
        casos_sin_match = casos_anio.merge(
            claves_sin_match,
            on=KEYS,
            how="inner",
            validate="one_to_one",
        )
    else:
        casos_sin_match = pd.DataFrame(columns=KEYS + VARIABLES_CASOS)

    df = df.merge(
        casos_anio,
        on=KEYS,
        how="left",
        validate="one_to_one",
    )

    for variable in VARIABLES_CASOS:
        df[variable] = pd.to_numeric(
            df[variable], errors="coerce"
        ).fillna(0).astype("int64")

    df["registro_minsa"] = (
        df["casos_dengue_reportados"] > 0
    ).astype("int8")

    df["tasa_semanal_reportada_100mil"] = (
        df["casos_dengue_reportados"]
        / df["poblacion_proyectada"]
        * 100000
    )

    if len(df) != 1891 * semanas:
        raise ValueError(f"{anio}: la integracion altero el numero de filas.")
    if df.duplicated(KEYS).any():
        raise ValueError(f"{anio}: hay claves duplicadas tras integrar.")

    resumen = {
        "anio": anio,
        "registros": len(df),
        "distritos": df["ubigeo"].nunique(),
        "semanas": semanas,
        "registros_recuperados": int(mascara.sum()),
        "casos_dengue_integrados": int(df["casos_dengue_reportados"].sum()),
        "casos_sin_correspondencia": (
            int(casos_sin_match["casos_dengue_reportados"].sum())
            if not casos_sin_match.empty else 0
        ),
        "registros_sin_geografia": int(
            (df["geografia_disponible"] == 0).sum()
        ),
        "registros_sin_poblacion": int(
            df["poblacion_proyectada"].isna().sum()
        ),
    }

    return df, resumen, casos_sin_match


# ============================================================
# 7. EJECUCION PRINCIPAL
# ============================================================

def main():
    print("=" * 65)
    print("CONSTRUCCION DEL DATASET MAESTRO DE DENGUE")
    print("PERIODO 2000-2025")
    print("=" * 65)

    SALIDA.mkdir(parents=True, exist_ok=True)
    REPORTES.mkdir(parents=True, exist_ok=True)

    verificar_archivos()

    if ARCHIVO_FINAL.exists():
        raise FileExistsError(
            f"Ya existe el dataset final y no se sobrescribira:\n{ARCHIVO_FINAL}"
        )

    geo = cargar_geografia()
    poblacion = cargar_poblacion()
    casos, estadisticas_minsa = cargar_epidemiologia()

    muestra = pd.read_csv(
        CLIMA_ORIGINAL / "clima_dengue_peru_2000.csv",
        encoding="utf-8-sig",
        dtype={"ubigeo": "string"},
        usecols=["ubigeo"],
    )
    ubigeos_clima = set(limpiar_ubigeo(muestra["ubigeo"]).dropna())
    ubigeos_geo = set(geo["ubigeo"].dropna())
    ubigeos_sin_geo = sorted(ubigeos_clima - ubigeos_geo)

    print("\nCONTROL GEOGRAFICO")
    print("UBIGEO EN CLIMA:", len(ubigeos_clima))
    print("UBIGEO EN GEOPACKAGE:", len(ubigeos_geo))
    print("UBIGEO SIN REFERENCIA GEOGRAFICA:", len(ubigeos_sin_geo))

    pd.DataFrame({
        "ubigeo_sin_geografia": ubigeos_sin_geo
    }).to_csv(
        REPORTES / "104_ubigeos_sin_geografia.csv",
        index=False,
        encoding="utf-8-sig",
    )

    ubigeos_recuperados = None
    resumenes = []
    casos_sin_match_partes = []

    ARCHIVO_TEMPORAL.unlink(missing_ok=True)

    try:
        with gzip.open(
            ARCHIVO_TEMPORAL,
            mode="wt",
            encoding="utf-8",
            newline="",
        ) as salida:

            escribir_encabezado = True

            for anio in ANIOS:
                print("\n" + "=" * 55)
                print("INTEGRANDO ANIO:", anio)
                print("=" * 55)

                if ubigeos_recuperados is None:
                    muestra_rec = pd.read_csv(
                        CLIMA_RECUPERADO / f"CLIMA_RECUPERADO_{anio}.csv",
                        encoding="utf-8-sig",
                        dtype={"ubigeo": "string"},
                        usecols=["ubigeo"],
                    )
                    ubigeos_recuperados = set(
                        limpiar_ubigeo(muestra_rec["ubigeo"]).dropna()
                    )
                    if len(ubigeos_recuperados) != 13:
                        raise ValueError(
                            "El primer archivo recuperado no contiene "
                            "exactamente 13 UBIGEO."
                        )

                df, resumen, casos_sin_match = integrar_anio(
                    anio,
                    geo,
                    poblacion,
                    casos,
                    ubigeos_recuperados,
                )

                df.to_csv(
                    salida,
                    index=False,
                    header=escribir_encabezado,
                )
                escribir_encabezado = False

                resumenes.append(resumen)
                if not casos_sin_match.empty:
                    casos_sin_match_partes.append(casos_sin_match)

                print("REGISTROS INTEGRADOS:", f"{resumen['registros']:,}")
                print("REGISTROS RECUPERADOS:", f"{resumen['registros_recuperados']:,}")
                print("REGISTROS MINSA INTEGRADOS:", f"{resumen['casos_dengue_integrados']:,}")
                print("REGISTROS MINSA SIN CORRESPONDENCIA:", f"{resumen['casos_sin_correspondencia']:,}")
                print("REGISTROS SIN GEOGRAFIA:", f"{resumen['registros_sin_geografia']:,}")
                print("ESTADO: OK")

                del df

        resumen_df = pd.DataFrame(resumenes)

        total_registros = int(resumen_df["registros"].sum())
        total_recuperados = int(resumen_df["registros_recuperados"].sum())
        total_casos_integrados = int(
            resumen_df["casos_dengue_integrados"].sum()
        )
        total_sin_match = int(
            resumen_df["casos_sin_correspondencia"].sum()
        )

        if casos_sin_match_partes:
            sin_match_df = pd.concat(
                casos_sin_match_partes,
                ignore_index=True,
            )
        else:
            sin_match_df = pd.DataFrame(
                columns=KEYS + VARIABLES_CASOS
            )

        if (
            total_casos_integrados + total_sin_match
            != estadisticas_minsa["registros_dengue_validos"]
        ):
            raise ValueError(
                "Los registros MINSA integrados y sin correspondencia "
                "no coinciden con el total valido."
            )

        resumen_df.to_csv(
            REPORTES / "100_resumen_integracion.csv",
            index=False,
            encoding="utf-8-sig",
        )

        sin_match_df.to_csv(
            REPORTES / "101_casos_sin_correspondencia.csv",
            index=False,
            encoding="utf-8-sig",
        )

        pd.DataFrame([
            {"fuente": "CLIMA_ERA5_LAND", "archivos": 26, "registros": total_registros},
            {"fuente": "CLIMA_RECUPERADO", "archivos": 26, "registros": total_recuperados},
            {"fuente": "MINSA", "archivos": 1, "registros": estadisticas_minsa["registros_dengue_total"]},
            {"fuente": "POBLACION_INEI", "archivos": 1, "registros": len(poblacion)},
            {"fuente": "GEOGRAFIA", "archivos": 1, "registros": len(geo)},
        ]).to_csv(
            REPORTES / "102_resumen_fuentes.csv",
            index=False,
            encoding="utf-8-sig",
        )

        pd.DataFrame([
            {"indicador": clave, "valor": valor}
            for clave, valor in estadisticas_minsa.items()
        ]).to_csv(
            REPORTES / "103_auditoria_minsa.csv",
            index=False,
            encoding="utf-8-sig",
        )

        # Publicar solo despues de completar todas las validaciones.
        os.replace(ARCHIVO_TEMPORAL, ARCHIVO_FINAL)

        print("\n" + "=" * 65)
        print("DATASET MAESTRO CONSTRUIDO CORRECTAMENTE")
        print("=" * 65)
        print("ANIOS PROCESADOS:", len(resumen_df))
        print("REGISTROS TOTALES:", f"{total_registros:,}")
        print("REGISTROS CLIMATICOS RECUPERADOS:", f"{total_recuperados:,}")
        print("REGISTROS MINSA INTEGRADOS:", f"{total_casos_integrados:,}")
        print("REGISTROS MINSA SIN CORRESPONDENCIA:", f"{total_sin_match:,}")
        print("UBIGEO SIN REFERENCIA GEOGRAFICA:", len(ubigeos_sin_geo))
        print("\nDATASET FINAL:")
        print(ARCHIVO_FINAL)
        print("\nREPORTES:")
        print(REPORTES)
        print("\nNO SE MODIFICARON LOS ARCHIVOS ORIGINALES.")

    except Exception:
        ARCHIVO_TEMPORAL.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\n" + "=" * 65)
        print("INTEGRACION CANCELADA")
        print("=" * 65)
        print("MOTIVO:")
        print(error)
        print("\nNO SE PUBLICO EL DATASET MAESTRO.")
        print("LOS ARCHIVOS ORIGINALES NO FUERON MODIFICADOS.")
        sys.exit(1)
