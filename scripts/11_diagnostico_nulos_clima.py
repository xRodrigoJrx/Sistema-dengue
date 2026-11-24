from pathlib import Path
import pandas as pd
import re

# ==============================================
# CONFIGURACION
# ==============================================

BASE = Path(
    r"C:\Users\xxter\Documents\Data_Dengue\Sistema"
)

CARPETA = BASE / "data/raw/clima/era5_land"

SALIDA = BASE / "reports/diagnostico_nulos_clima"

SALIDA.mkdir(parents=True, exist_ok=True)

CLIMA = [
    "tmean", "tmax", "tmin", "humr",
    "ptot", "ptot_raw", "n_dias", "n_horas"
]

RESUMEN = []
UBIGEOS = []
MUESTRAS = []

# ==============================================
# BUSCAR ARCHIVOS
# ==============================================

archivos = sorted(
    CARPETA.glob("clima_dengue_peru_*.csv")
)

print("\n" + "=" * 65)
print("DIAGNOSTICO DETALLADO DE NULOS CLIMATICOS")
print("=" * 65)

print("Archivos encontrados:", len(archivos))

if len(archivos) == 0:
    raise FileNotFoundError("No se encontraron CSV climaticos.")

# ==============================================
# PROCESAR CADA ARCHIVO
# ==============================================

for archivo in archivos:

    match = re.search(r"_(\d{4})$", archivo.stem)

    if not match:
        continue

    anio = int(match.group(1))

    print("\nProcesando:", anio)

    df = pd.read_csv(
        archivo,
        encoding="utf-8-sig",
        dtype={
            "ubigeo": "string",
            "departamento": "string",
            "provincia": "string",
            "distrito": "string"
        },
        low_memory=False
    )

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
    )

    faltantes = [
        c for c in CLIMA + [
            "ubigeo", "departamento",
            "provincia", "distrito",
            "ano", "semana"
        ]
        if c not in df.columns
    ]

    if faltantes:
        print("Columnas faltantes:", faltantes)
        continue

    # ==========================================
    # NORMALIZAR UBIGEO
    # ==========================================

    df["ubigeo"] = (
        df["ubigeo"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    df["ubigeo"] = df["ubigeo"].mask(
        df["ubigeo"].eq(""),
        pd.NA
    ).str.zfill(6)

    # ==========================================
    # CONVERTIR VARIABLES CLIMATICAS
    # ==========================================

    for col in CLIMA:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    # ==========================================
    # IDENTIFICAR NULOS
    # ==========================================

    mascara = df[CLIMA].isna()

    # Todas las variables climaticas nulas
    df["_todo_clima_nulo"] = mascara.all(axis=1)

    # Al menos una variable climatica nula
    df["_algun_clima_nulo"] = mascara.any(axis=1)

    # Solo algunas variables climaticas nulas
    df["_clima_parcial"] = (
        df["_algun_clima_nulo"]
        & ~df["_todo_clima_nulo"]
    )

    # Departamento vacio
    departamento = (
        df["departamento"]
        .astype("string")
        .str.strip()
    )

    df["_departamento_nulo"] = (
        departamento.isna()
        | departamento.eq("")
    )

    # ==========================================
    # COMPROBAR SI LOS NULOS SON IDENTICOS
    # ==========================================

    primera = mascara[CLIMA[0]]

    mascaras_iguales = all(
        mascara[col].equals(primera)
        for col in CLIMA[1:]
    )

    # ==========================================
    # RESUMEN DE CADA AÑO
    # ==========================================

    total = len(df)

    todos_nulos = int(
        df["_todo_clima_nulo"].sum()
    )

    alguno_nulo = int(
        df["_algun_clima_nulo"].sum()
    )

    parcial = int(
        df["_clima_parcial"].sum()
    )

    depto_nulos = int(
        df["_departamento_nulo"].sum()
    )

    registro = {
        "anio": anio,
        "registros": total,
        "filas_todas_variables_nulas": todos_nulos,
        "filas_alguna_variable_nula": alguno_nulo,
        "filas_nulos_parciales": parcial,
        "mascaras_nulos_identicas": mascaras_iguales,
        "departamento_nulos": depto_nulos,
        "departamentos_diferentes": int(
            departamento.dropna().loc[
                departamento.ne("")
            ].nunique()
        )
    }

    for col in CLIMA:
        registro["nulos_" + col] = int(
            mascara[col].sum()
        )

    RESUMEN.append(registro)

    # ==========================================
    # ANALIZAR CADA UBIGEO
    # ==========================================

    df["_semana_con_clima"] = (
        ~df["_todo_clima_nulo"]
    )

    grupos = df.groupby(
        "ubigeo",
        dropna=False
    )

    estadisticas = grupos.agg(
        registros=("semana", "size"),
        semanas_registradas=("semana", "nunique"),
        filas_todas_nulas=("_todo_clima_nulo", "sum"),
        filas_parciales=("_clima_parcial", "sum"),
        departamento_nulo=("_departamento_nulo", "sum"),
        distrito=("distrito", "first"),
        provincia=("provincia", "first")
    )

    semanas_con_datos = (
        df.loc[df["_semana_con_clima"]]
        .groupby("ubigeo")["semana"]
        .nunique()
    )

    estadisticas["semanas_con_clima"] = (
        estadisticas.index.map(semanas_con_datos)
    )

    estadisticas["semanas_con_clima"] = (
        estadisticas["semanas_con_clima"]
        .fillna(0)
        .astype(int)
    )

    estadisticas["semanas_sin_clima"] = (
        estadisticas["semanas_registradas"]
        - estadisticas["semanas_con_clima"]
    )

    estadisticas["todas_las_semanas_sin_clima"] = (
        estadisticas["filas_todas_nulas"]
        == estadisticas["registros"]
    )

    estadisticas["anio"] = anio

    estadisticas = estadisticas.reset_index()

    estadisticas.insert(
        0, "archivo", archivo.name
    )

    UBIGEOS.append(estadisticas)

    distritos_afectados = int(
        (estadisticas["filas_todas_nulas"] > 0).sum()
    )

    distritos_sin_clima = int(
        estadisticas[
            "todas_las_semanas_sin_clima"
        ].sum()
    )

    distritos_parciales = int(
        (
            (estadisticas["filas_todas_nulas"] > 0)
            &
            ~estadisticas[
                "todas_las_semanas_sin_clima"
            ]
        ).sum()
    )

    RESUMEN[-1].update({
        "distritos_afectados": distritos_afectados,
        "distritos_sin_clima_todo_el_anio": distritos_sin_clima,
        "distritos_con_afectacion_parcial": distritos_parciales,
        "ubigeos_unicos": int(
            df["ubigeo"].nunique()
        )
    })

    # ==========================================
    # GUARDAR MUESTRA DE REGISTROS AFECTADOS
    # ==========================================

    columnas_muestra = [
        "ubigeo",
        "departamento",
        "provincia",
        "distrito",
        "ano",
        "semana",
        "fecha_inicio",
        "fecha_fin"
    ]

    columnas_muestra = [
        c for c in columnas_muestra
        if c in df.columns
    ]

    muestra = df.loc[
        df["_todo_clima_nulo"],
        columnas_muestra
    ].head(30).copy()

    muestra.insert(0, "archivo", archivo.name)

    MUESTRAS.append(muestra)

    # ==========================================
    # MOSTRAR RESULTADOS
    # ==========================================

    print("Registros:", f"{total:,}")

    print("Todas las variables nulas:", f"{todos_nulos:,}")

    print("Nulos parciales:", f"{parcial:,}")

    print("Mascaras identicas:", mascaras_iguales)

    print("Departamento nulo:", f"{depto_nulos:,}")

    print("Distritos afectados:", distritos_afectados)

    print("Distritos sin clima todo el año:", distritos_sin_clima)

    print("Distritos con afectacion parcial:", distritos_parciales)

    del df

# ==============================================
# EXPORTAR RESULTADOS
# ==============================================

resumen_df = pd.DataFrame(RESUMEN)

ubigeos_df = (
    pd.concat(UBIGEOS, ignore_index=True)
    if UBIGEOS else pd.DataFrame()
)

muestras_df = (
    pd.concat(MUESTRAS, ignore_index=True)
    if MUESTRAS else pd.DataFrame()
)

resumen_df.to_csv(
    SALIDA / "55_resumen_diagnostico_nulos.csv",
    index=False,
    encoding="utf-8-sig"
)

ubigeos_df.to_csv(
    SALIDA / "56_ubigeos_afectados.csv",
    index=False,
    encoding="utf-8-sig"
)

muestras_df.to_csv(
    SALIDA / "57_muestra_registros_sin_clima.csv",
    index=False,
    encoding="utf-8-sig"
)

# ==============================================
# INFORME FINAL
# ==============================================

lineas = [
    "DIAGNOSTICO DETALLADO DE NULOS CLIMATICOS",
    "=" * 65
]

for _, fila in resumen_df.iterrows():

    lineas.append("")
    lineas.append(f"ANIO: {fila['anio']}")
    lineas.append(
        f"Registros: {fila['registros']:,}"
    )
    lineas.append(
        f"Todas las variables climaticas nulas: "
        f"{fila['filas_todas_variables_nulas']:,}"
    )
    lineas.append(
        f"Nulos parciales: {fila['filas_nulos_parciales']:,}"
    )
    lineas.append(
        f"Mascaras identicas: {fila['mascaras_nulos_identicas']}"
    )
    lineas.append(
        f"Departamento nulo: {fila['departamento_nulos']:,}"
    )
    lineas.append(
        f"Distritos afectados: {fila['distritos_afectados']}"
    )
    lineas.append(
        f"Distritos sin clima todo el anio: "
        f"{fila['distritos_sin_clima_todo_el_anio']}"
    )
    lineas.append(
        f"Distritos con afectacion parcial: "
        f"{fila['distritos_con_afectacion_parcial']}"
    )

(SALIDA / "resumen_diagnostico_nulos.txt").write_text(
    "\n".join(lineas),
    encoding="utf-8"
)

print("\n" + "=" * 65)
print("DIAGNOSTICO TERMINADO")
print("=" * 65)

print("Años analizados:", len(resumen_df))

print("\nRESULTADOS GENERADOS:")
print(SALIDA)

print("\n55_resumen_diagnostico_nulos.csv")
print("56_ubigeos_afectados.csv")
print("57_muestra_registros_sin_clima.csv")
print("resumen_diagnostico_nulos.txt")

print("\nNo se modificaron los datos originales.")
