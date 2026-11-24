from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import re
import sys

# =====================================================
# 1. CONFIGURACION
# =====================================================

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

CARPETA = BASE / "data/raw/clima/era5_land"

SALIDA = BASE / "reports/auditoria_clima"

SALIDA.mkdir(parents=True, exist_ok=True)

ANIOS = list(range(2000, 2026))

DISTRITOS_ESPERADOS = 1891

COLUMNAS = [
    "ubigeo", "departamento", "provincia", "distrito",
    "ano", "semana", "fecha_inicio", "fecha_fin",
    "tmean", "tmax", "tmin", "humr",
    "ptot", "ptot_raw", "n_dias", "n_horas",
    "fuente", "zona_horaria", "resolucion_m"
]

NUMERICAS = [
    "ano", "semana", "tmean", "tmax", "tmin",
    "humr", "ptot", "ptot_raw", "n_dias",
    "n_horas", "resolucion_m"
]

CRITICAS = [
    "ubigeo", "departamento", "provincia", "distrito",
    "ano", "semana", "fecha_inicio", "fecha_fin",
    "tmean", "tmax", "tmin", "humr",
    "ptot", "ptot_raw", "n_dias", "n_horas"
]

CLAVES = ["ubigeo", "ano", "semana"]

resumen = []
nulos = []
anomalias = []
duplicados = []
cobertura = []


# =====================================================
# 2. FUNCIONES DE CALENDARIO
# =====================================================

def primer_domingo(anio):

    enero4 = date(anio, 1, 4)

    desplazamiento = (enero4.weekday() + 1) % 7

    return enero4 - timedelta(days=desplazamiento)


def calcular_semanas(anio):

    inicio = primer_domingo(anio)

    siguiente = primer_domingo(anio + 1)

    return (siguiente - inicio).days // 7


def registrar_anomalia(anio, archivo, tipo, cantidad, detalle=""):

    if cantidad > 0:

        anomalias.append({
            "anio": anio,
            "archivo": archivo,
            "anomalia": tipo,
            "cantidad": int(cantidad),
            "detalle": str(detalle)
        })


# =====================================================
# 3. VERIFICAR ARCHIVOS
# =====================================================

print("\n" + "=" * 65)
print("AUDITORIA CLIMATICA - DENGUE INTELLIGENCE PERU")
print("=" * 65)

if not CARPETA.exists():

    print("ERROR: No existe la carpeta de datos.")
    sys.exit(1)

archivos = list(
    CARPETA.glob("clima_dengue_peru_*.csv")
)

por_anio = {}

for archivo in archivos:

    coincidencia = re.fullmatch(
        r"clima_dengue_peru_(\d{4})",
        archivo.stem
    )

    if coincidencia:

        anio = int(coincidencia.group(1))

        por_anio.setdefault(anio, []).append(archivo)


print("CSV encontrados:", len(archivos))

print("Años identificados:", len(por_anio))


# =====================================================
# 4. PROCESAR LOS 26 AÑOS
# =====================================================

for anio in ANIOS:

    candidatos = por_anio.get(anio, [])

    if len(candidatos) == 0:

        registrar_anomalia(
            anio, "NO ENCONTRADO",
            "archivo_faltante", 1
        )

        resumen.append({
            "anio": anio,
            "registros": 0,
            "esperados": 0,
            "distritos": 0,
            "semanas_esperadas": calcular_semanas(anio),
            "semanas_encontradas": 0,
            "claves_duplicadas": 0,
            "nulos_criticos": 0,
            "estado": "ARCHIVO FALTANTE"
        })

        continue

    if len(candidatos) > 1:

        registrar_anomalia(
            anio, "MULTIPLES ARCHIVOS",
            "archivos_duplicados", len(candidatos)
        )

        resumen.append({
            "anio": anio,
            "registros": 0,
            "esperados": 0,
            "distritos": 0,
            "semanas_esperadas": calcular_semanas(anio),
            "semanas_encontradas": 0,
            "claves_duplicadas": 0,
            "nulos_criticos": 0,
            "estado": "ARCHIVOS DUPLICADOS"
        })

        continue

    archivo = candidatos[0]

    semanas_esperadas = calcular_semanas(anio)

    registros_esperados = (
        DISTRITOS_ESPERADOS * semanas_esperadas
    )

    print("\n" + "-" * 60)
    print("PROCESANDO:", anio)
    print("ARCHIVO:", archivo.name)
    print("-" * 60)

    try:

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

    except Exception as e:

        print("ERROR DE LECTURA:", e)

        registrar_anomalia(
            anio, archivo.name,
            "error_lectura", 1, str(e)
        )

        resumen.append({
            "anio": anio,
            "registros": 0,
            "esperados": registros_esperados,
            "distritos": 0,
            "semanas_esperadas": semanas_esperadas,
            "semanas_encontradas": 0,
            "claves_duplicadas": 0,
            "nulos_criticos": 0,
            "estado": "ERROR DE LECTURA"
        })

        continue

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
    )

    filas = len(df)

    # -------------------------------------------------
    # 4.1 COLUMNAS
    # -------------------------------------------------

    faltantes_columnas = [
        c for c in COLUMNAS
        if c not in df.columns
    ]

    if faltantes_columnas:

        registrar_anomalia(
            anio, archivo.name,
            "columnas_faltantes",
            len(faltantes_columnas),
            faltantes_columnas
        )

        resumen.append({
            "anio": anio,
            "registros": filas,
            "esperados": registros_esperados,
            "distritos": 0,
            "semanas_esperadas": semanas_esperadas,
            "semanas_encontradas": 0,
            "claves_duplicadas": 0,
            "nulos_criticos": 0,
            "estado": "COLUMNAS FALTANTES"
        })

        continue

    # -------------------------------------------------
    # 4.2 UBIGEO
    # -------------------------------------------------

    df["ubigeo"] = (
        df["ubigeo"]
        .astype("string")
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    df["ubigeo"] = df["ubigeo"].mask(
        df["ubigeo"].eq(""),
        pd.NA
    )

    df["ubigeo"] = df["ubigeo"].str.zfill(6)

    # -------------------------------------------------
    # 4.3 CONVERSION NUMERICA
    # -------------------------------------------------

    for columna in NUMERICAS:

        df[columna] = pd.to_numeric(
            df[columna],
            errors="coerce"
        )

    # -------------------------------------------------
    # 4.4 VALORES NULOS
    # -------------------------------------------------

    nulos_criticos = 0

    for columna in CRITICAS:

        cantidad = int(df[columna].isna().sum())

        nulos_criticos += cantidad

        nulos.append({
            "anio": anio,
            "archivo": archivo.name,
            "columna": columna,
            "nulos": cantidad,
            "porcentaje": round(
                cantidad / filas * 100, 4
            ) if filas else 0
        })

        registrar_anomalia(
            anio, archivo.name,
            "nulos_" + columna,
            cantidad
        )

    # -------------------------------------------------
    # 4.5 VALIDACION DE UBIGEO
    # -------------------------------------------------

    distritos = int(df["ubigeo"].nunique())

    ubigeo_invalido = int((
        df["ubigeo"].notna()
        &
        ~df["ubigeo"].str.fullmatch(
            r"\d{6}", na=False
        )
    ).sum())

    registrar_anomalia(
        anio, archivo.name,
        "ubigeo_invalido",
        ubigeo_invalido
    )

    # -------------------------------------------------
    # 4.6 VALIDACION DE AÑO Y SEMANA
    # -------------------------------------------------

    anio_incorrecto = int((
        df["ano"].notna()
        &
        df["ano"].ne(anio)
    ).sum())

    semana_valida = (
        df["semana"].notna()
        &
        df["semana"].between(1, semanas_esperadas)
        &
        df["semana"].mod(1).eq(0)
    )

    semanas_encontradas = sorted(
        int(x)
        for x in df.loc[
            semana_valida, "semana"
        ].unique()
    )

    semanas_faltantes = sorted(
        set(range(1, semanas_esperadas + 1))
        - set(semanas_encontradas)
    )

    semanas_invalidas = int(
        (df["semana"].notna() & ~semana_valida).sum()
    )

    registrar_anomalia(
        anio, archivo.name,
        "anio_incorrecto", anio_incorrecto
    )

    registrar_anomalia(
        anio, archivo.name,
        "semanas_faltantes",
        len(semanas_faltantes),
        semanas_faltantes
    )

    registrar_anomalia(
        anio, archivo.name,
        "semanas_invalidas",
        semanas_invalidas
    )

    # -------------------------------------------------
    # 4.7 CLAVES Y DUPLICADOS
    # -------------------------------------------------

    clave_valida = (
        df[CLAVES].notna().all(axis=1)
        &
        semana_valida
    )

    df_claves = df.loc[clave_valida].copy()

    mascara_duplicados = df_claves.duplicated(
        subset=CLAVES,
        keep=False
    )

    filas_duplicadas = int(
        mascara_duplicados.sum()
    )

    repeticiones_adicionales = int(
        df_claves.duplicated(
            subset=CLAVES,
            keep="first"
        ).sum()
    )

    grupos_duplicados = int(
        df_claves.loc[
            mascara_duplicados, CLAVES
        ].drop_duplicates().shape[0]
    )

    if filas_duplicadas > 0:

        detalle = (
            df_claves.loc[
                mascara_duplicados, CLAVES
            ]
            .groupby(CLAVES)
            .size()
            .reset_index(name="frecuencia")
        )

        detalle.insert(0, "archivo", archivo.name)

        duplicados.append(detalle)

    registrar_anomalia(
        anio, archivo.name,
        "filas_con_claves_duplicadas",
        filas_duplicadas
    )

    # -------------------------------------------------
    # 4.8 COBERTURA POR SEMANA Y DISTRITO
    # -------------------------------------------------

    cobertura_semana = (
        df_claves
        .groupby("semana")["ubigeo"]
        .nunique()
    )

    for semana in range(1, semanas_esperadas + 1):

        encontrados = int(
            cobertura_semana.get(semana, 0)
        )

        cobertura.append({
            "anio": anio,
            "semana": semana,
            "distritos_encontrados": encontrados,
            "distritos_esperados": DISTRITOS_ESPERADOS,
            "distritos_faltantes": (
                DISTRITOS_ESPERADOS - encontrados
            )
        })

    semanas_incompletas = int(
        (cobertura_semana.reindex(
            range(1, semanas_esperadas + 1),
            fill_value=0
        ) != DISTRITOS_ESPERADOS).sum()
    )

    distritos_por_semana = (
        df_claves.groupby("ubigeo")["semana"].nunique()
    )

    distritos_incompletos = int(
        (distritos_por_semana != semanas_esperadas).sum()
    )

    # -------------------------------------------------
    # 4.9 TEMPERATURAS
    # -------------------------------------------------

    temperaturas_completas = df[
        ["tmin", "tmean", "tmax"]
    ].notna().all(axis=1)

    temperatura_incorrecta = int((
        temperaturas_completas
        &
        (
            (df["tmax"] < df["tmean"])
            |
            (df["tmean"] < df["tmin"])
        )
    ).sum())

    registrar_anomalia(
        anio, archivo.name,
        "orden_temperaturas_incorrecto",
        temperatura_incorrecta
    )

    # -------------------------------------------------
    # 4.10 HUMEDAD
    # -------------------------------------------------

    humedad_incorrecta = int((
        df["humr"].notna()
        &
        (
            (df["humr"] < 0)
            |
            (df["humr"] > 100)
        )
    ).sum())

    registrar_anomalia(
        anio, archivo.name,
        "humedad_fuera_de_rango",
        humedad_incorrecta
    )

    # -------------------------------------------------
    # 4.11 PRECIPITACION
    # -------------------------------------------------

    ptot_negativo = int((
        df["ptot"].notna()
        &
        (df["ptot"] < 0)
    ).sum())

    ptot_raw_negativo = int((
        df["ptot_raw"].notna()
        &
        (df["ptot_raw"] < 0)
    ).sum())

    registrar_anomalia(
        anio, archivo.name,
        "precipitacion_negativa",
        ptot_negativo
    )

    registrar_anomalia(
        anio, archivo.name,
        "precipitacion_original_negativa",
        ptot_raw_negativo
    )

    # -------------------------------------------------
    # 4.12 DIAS Y HORAS
    # -------------------------------------------------

    dias_incorrectos = int((
        df["n_dias"].notna()
        &
        ((df["n_dias"] - 7).abs() > 0.01)
    ).sum())

    horas_incorrectas = int((
        df["n_horas"].notna()
        &
        ((df["n_horas"] - 168).abs() > 0.01)
    ).sum())

    registrar_anomalia(
        anio, archivo.name,
        "n_dias_distinto_de_7",
        dias_incorrectos
    )

    registrar_anomalia(
        anio, archivo.name,
        "n_horas_distinto_de_168",
        horas_incorrectas
    )

    # -------------------------------------------------
    # 4.13 FECHAS EPIDEMIOLOGICAS
    # -------------------------------------------------

    fecha_inicio = pd.to_datetime(
        df["fecha_inicio"],
        errors="coerce"
    )

    fecha_fin = pd.to_datetime(
        df["fecha_fin"],
        errors="coerce"
    )

    inicio_anual = primer_domingo(anio)

    fechas_esperadas = {
        semana: pd.Timestamp(
            inicio_anual + timedelta(weeks=semana - 1)
        )
        for semana in range(1, semanas_esperadas + 1)
    }

    inicio_esperado = df["semana"].map(fechas_esperadas)

    fin_esperado = inicio_esperado + pd.Timedelta(days=6)

    fechas_invalidas = int((
        fecha_inicio.isna()
        |
        fecha_fin.isna()
        |
        fecha_inicio.dt.normalize().ne(inicio_esperado)
        |
        fecha_fin.dt.normalize().ne(fin_esperado)
    ).fillna(True).sum())

    registrar_anomalia(
        anio, archivo.name,
        "fechas_invalidas",
        fechas_invalidas
    )

    # -------------------------------------------------
    # 4.14 DUPLICADOS EXACTOS
    # -------------------------------------------------

    duplicados_exactos = int(df.duplicated().sum())

    registrar_anomalia(
        anio, archivo.name,
        "duplicados_exactos",
        duplicados_exactos
    )

    # -------------------------------------------------
    # 4.15 RESULTADO ANUAL
    # -------------------------------------------------

    problemas = [

        filas != registros_esperados,

        distritos != DISTRITOS_ESPERADOS,

        len(semanas_faltantes) > 0,

        semanas_invalidas > 0,

        filas_duplicadas > 0,

        duplicados_exactos > 0,

        nulos_criticos > 0,

        ubigeo_invalido > 0,

        anio_incorrecto > 0,

        temperatura_incorrecta > 0,

        humedad_incorrecta > 0,

        ptot_negativo > 0,

        ptot_raw_negativo > 0,

        dias_incorrectos > 0,

        horas_incorrectas > 0,

        fechas_invalidas > 0,

        semanas_incompletas > 0,

        distritos_incompletos > 0

    ]

    estado = "REVISAR" if any(problemas) else "OK"

    resumen.append({

        "anio": anio,
        "archivo": archivo.name,
        "registros": filas,
        "registros_esperados": registros_esperados,
        "diferencia_registros": filas - registros_esperados,
        "distritos": distritos,
        "semanas_esperadas": semanas_esperadas,
        "semanas_encontradas": len(semanas_encontradas),
        "semanas_faltantes": len(semanas_faltantes),
        "semanas_incompletas_por_distritos": semanas_incompletas,
        "distritos_incompletos": distritos_incompletos,
        "filas_con_claves_duplicadas": filas_duplicadas,
        "repeticiones_adicionales": repeticiones_adicionales,
        "grupos_duplicados": grupos_duplicados,
        "duplicados_exactos": duplicados_exactos,
        "nulos_criticos": nulos_criticos,
        "ubigeo_invalidos": ubigeo_invalido,
        "temperaturas_incorrectas": temperatura_incorrecta,
        "humedad_incorrecta": humedad_incorrecta,
        "ptot_negativo": ptot_negativo,
        "ptot_raw_negativo": ptot_raw_negativo,
        "dias_incorrectos": dias_incorrectos,
        "horas_incorrectas": horas_incorrectas,
        "fechas_invalidas": fechas_invalidas,
        "estado": estado

    })

    print("Registros:", f"{filas:,}")
    print("Esperados:", f"{registros_esperados:,}")
    print("Distritos:", distritos)
    print("Semanas:", len(semanas_encontradas), "/", semanas_esperadas)
    print("Duplicados:", filas_duplicadas)
    print("Nulos críticos:", nulos_criticos)
    print("Estado:", estado)

    del df
    del df_claves


# =====================================================
# 5. EXPORTAR RESULTADOS
# =====================================================

resumen_df = pd.DataFrame(resumen)

nulos_df = pd.DataFrame(nulos)

anomalias_df = pd.DataFrame(anomalias)

cobertura_df = pd.DataFrame(cobertura)

duplicados_df = (
    pd.concat(duplicados, ignore_index=True)
    if duplicados else
    pd.DataFrame(columns=[
        "archivo", "ubigeo", "ano",
        "semana", "frecuencia"
    ])
)

resumen_df.to_csv(
    SALIDA / "50_resumen_clima_por_anio.csv",
    index=False,
    encoding="utf-8-sig"
)

nulos_df.to_csv(
    SALIDA / "51_nulos_climaticos.csv",
    index=False,
    encoding="utf-8-sig"
)

anomalias_df.to_csv(
    SALIDA / "52_anomalias_climaticas.csv",
    index=False,
    encoding="utf-8-sig"
)

duplicados_df.to_csv(
    SALIDA / "53_duplicados_climaticos.csv",
    index=False,
    encoding="utf-8-sig"
)

cobertura_df.to_csv(
    SALIDA / "54_cobertura_semanal.csv",
    index=False,
    encoding="utf-8-sig"
)


# =====================================================
# 6. GENERAR INFORME DE TEXTO
# =====================================================

lineas = []

lineas.append("AUDITORIA CLIMATICA - DENGUE INTELLIGENCE PERU")
lineas.append("=" * 65)

lineas.append(f"Archivos encontrados: {len(archivos)}")
lineas.append(f"Años esperados: {len(ANIOS)}")

anios_procesados = [
    x["anio"] for x in resumen
    if x["estado"] not in [
        "ARCHIVO FALTANTE",
        "ARCHIVOS DUPLICADOS",
        "ERROR DE LECTURA"
    ]
]

faltantes = sorted(set(ANIOS) - set(anios_procesados))

lineas.append(f"Años faltantes: {faltantes}")
lineas.append("")

lineas.append("RESULTADOS POR AÑO")
lineas.append("=" * 65)

for _, fila in resumen_df.iterrows():

    lineas.append(f"\nAÑO: {fila['anio']}")

    lineas.append(
        f"Registros: {fila['registros']:,} / "
        f"{fila['registros_esperados']:,}"
    )

    lineas.append(f"Distritos: {fila['distritos']}")

    lineas.append(
        f"Semanas: {fila['semanas_encontradas']} / "
        f"{fila['semanas_esperadas']}"
    )

    lineas.append(
        f"Semanas incompletas: "
        f"{fila.get('semanas_incompletas_por_distritos', 0)}"
    )

    lineas.append(
        f"Claves duplicadas: "
        f"{fila['filas_con_claves_duplicadas']}"
    )

    lineas.append(
        f"Nulos críticos: {fila['nulos_criticos']}"
    )

    lineas.append(f"Estado: {fila['estado']}")

lineas.append("")
lineas.append("ARCHIVOS GENERADOS")
lineas.append("50_resumen_clima_por_anio.csv")
lineas.append("51_nulos_climaticos.csv")
lineas.append("52_anomalias_climaticas.csv")
lineas.append("53_duplicados_climaticos.csv")
lineas.append("54_cobertura_semanal.csv")

lineas.append("")
lineas.append("Los CSV originales no fueron modificados.")

lineas.append(
    "La validación de calendario comprueba la consistencia "
    "con el calendario usado por el extractor. La equivalencia "
    "con las semanas oficiales CDC-MINSA debe comprobarse "
    "antes de integrar las fuentes."
)

(SALIDA / "resumen_auditoria_clima.txt").write_text(
    "\n".join(lineas),
    encoding="utf-8"
)


# =====================================================
# 7. RESUMEN FINAL
# =====================================================

print("\n" + "=" * 65)
print("AUDITORIA CLIMATICA FINALIZADA")
print("=" * 65)

print("Años procesados:", len(anios_procesados))
print("Años faltantes:", faltantes)

if not resumen_df.empty:

    print(
        "Años OK:",
        int((resumen_df["estado"] == "OK").sum())
    )

    print(
        "Años para revisar:",
        int((resumen_df["estado"] != "OK").sum())
    )

print("\nResultados guardados en:")
print(SALIDA)

print("\nNo se modificaron los archivos originales.")
