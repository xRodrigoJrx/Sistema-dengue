from pathlib import Path
from collections import Counter, defaultdict
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")
ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"
SALIDA = BASE / "reports/auditoria_calidad"

SALIDA.mkdir(parents=True, exist_ok=True)

# Detectar codificacion
encoding = "utf-8-sig"

print("Iniciando segunda auditoria...")

# Contadores
anios = Counter()
departamentos = Counter()
sexo = Counter()
tipo_edad = Counter()
tipo_dx = Counter()
diagnosticos = Counter()
enfermedades = Counter()
semanas = Counter()
anio_departamento = Counter()
distritos = Counter()
cruce_diagnostico = Counter()
vacios = Counter()

ubigeo_mapa = defaultdict(set)

total = 0
semanas_invalidas = 0
anios_invalidos = 0
edades_invalidas = 0
edad_min = None
edad_max = None

for i, chunk in enumerate(pd.read_csv(
    ARCHIVO,
    chunksize=200_000,
    encoding=encoding,
    dtype={"ubigeo": "string", "localcod": "string"},
    low_memory=False
), start=1):

    chunk.columns = (
        chunk.columns.str.strip().str.lower()
    )

    total += len(chunk)

    # Revisar campos vacios
    for col in chunk.columns:
        s = chunk[col].astype("string")
        vacios[col] += int(
            (s.isna() | s.fillna("").str.strip().eq("")).sum()
        )

    # Categorias
    for col, contador in [
        ("departamento", departamentos),
        ("sexo", sexo),
        ("tipo_edad", tipo_edad),
        ("tipo_dx", tipo_dx),
        ("diagnostic", diagnosticos),
        ("enfermedad", enfermedades)
    ]:
        contador.update(
            chunk[col].fillna("SIN DATO")
            .astype(str).str.strip()
            .value_counts().to_dict()
        )

    # Año y semana
    ano = pd.to_numeric(chunk["ano"], errors="coerce")
    semana = pd.to_numeric(chunk["semana"], errors="coerce")

    anios_invalidos += int(
        (~ano.between(2000, 2025)).sum()
    )

    semanas_invalidas += int(
        (~semana.between(1, 53)).sum()
    )

    anios.update(
        ano.dropna().astype(int).value_counts().to_dict()
    )

    temporal = pd.DataFrame({
        "ano": ano,
        "semana": semana
    }).dropna()

    semanas.update(
        temporal.groupby(["ano", "semana"]).size().to_dict()
    )

    # Año por departamento
    temporal_dep = pd.DataFrame({
        "ano": ano,
        "departamento": chunk["departamento"]
    }).dropna()

    anio_departamento.update(
        temporal_dep.groupby(
            ["ano", "departamento"]
        ).size().to_dict()
    )

    # Edad
    edad = pd.to_numeric(chunk["edad"], errors="coerce")

    edades_invalidas += int(
        (chunk["edad"].notna() & edad.isna()).sum()
    )

    if edad.notna().any():
        minimo = edad.min()
        maximo = edad.max()

        edad_min = minimo if edad_min is None else min(edad_min, minimo)
        edad_max = maximo if edad_max is None else max(edad_max, maximo)

    # Cruce tipo de diagnostico y diagnostico clinico
    cruce_diagnostico.update(
        chunk.groupby(
            ["tipo_dx", "diagnostic", "enfermedad"],
            dropna=False
        ).size().to_dict()
    )

    # Registros por distrito
    distritos.update(
        chunk.groupby(
            ["ubigeo", "departamento", "provincia", "distrito"]
        ).size().to_dict()
    )

    # Verificar consistencia territorial de UBIGEO
    geo = chunk[
        ["ubigeo", "departamento", "provincia", "distrito"]
    ].drop_duplicates()

    for ub, dep, prov, dist in geo.itertuples(index=False, name=None):
        if pd.notna(ub) and str(ub).strip():
            ubigeo_mapa[str(ub).strip()].add(
                (str(dep), str(prov), str(dist))
            )

    print(f"Bloque {i} revisado: {total:,} registros")

# =====================================
# GUARDAR RESULTADOS
# =====================================

def guardar_contador(contador, nombre, columnas):
    datos = [
        dict(zip(columnas, k if isinstance(k, tuple) else (k,)))
        | {"registros": v}
        for k, v in contador.items()
    ]

    pd.DataFrame(datos).to_csv(
        SALIDA / nombre,
        index=False,
        encoding="utf-8-sig"
    )

guardar_contador(anios, "01_registros_por_anio.csv", ["ano"])
guardar_contador(departamentos, "02_departamentos.csv", ["departamento"])
guardar_contador(sexo, "03_sexo.csv", ["sexo"])
guardar_contador(tipo_edad, "04_tipo_edad.csv", ["tipo_edad"])
guardar_contador(tipo_dx, "05_tipo_dx.csv", ["tipo_dx"])
guardar_contador(diagnosticos, "06_diagnosticos.csv", ["diagnostic"])
guardar_contador(enfermedades, "07_enfermedades.csv", ["enfermedad"])

guardar_contador(
    semanas,
    "08_registros_por_semana.csv",
    ["ano", "semana"]
)

guardar_contador(
    anio_departamento,
    "09_anio_departamento.csv",
    ["ano", "departamento"]
)

guardar_contador(
    cruce_diagnostico,
    "10_cruce_diagnostico.csv",
    ["tipo_dx", "diagnostic", "enfermedad"]
)

guardar_contador(
    distritos,
    "11_registros_por_distrito.csv",
    ["ubigeo", "departamento", "provincia", "distrito"]
)

# Inconsistencias territoriales
conflictos = []

for ub, ubicaciones in ubigeo_mapa.items():
    if len(ubicaciones) > 1:
        conflictos.append({
            "ubigeo": ub,
            "combinaciones": str(sorted(ubicaciones))
        })

pd.DataFrame(conflictos).to_csv(
    SALIDA / "12_ubigeo_inconsistencias.csv",
    index=False,
    encoding="utf-8-sig"
)

# Valores vacios
pd.DataFrame(
    [{"columna": k, "vacios": v} for k, v in vacios.items()]
).to_csv(
    SALIDA / "13_valores_vacios.csv",
    index=False,
    encoding="utf-8-sig"
)

# Resumen
resumen = [
    "SEGUNDA AUDITORIA - MINSA",
    "=" * 45,
    f"Total registros: {total:,}",
    f"Años encontrados: {sorted(anios.keys())}",
    f"Departamentos: {len(departamentos)}",
    f"UBIGEO diferentes: {len(ubigeo_mapa)}",
    f"Años fuera del rango 2000-2025: {anios_invalidos}",
    f"Semanas fuera del rango 1-53: {semanas_invalidas}",
    f"Edades no numericas: {edades_invalidas}",
    f"Edad minima: {edad_min}",
    f"Edad maxima: {edad_max}",
    f"UBIGEO con multiples ubicaciones: {len(conflictos)}",
    "",
    "TIPOS DE EDAD:",
    str(tipo_edad.most_common()),
    "",
    "SEXO:",
    str(sexo.most_common()),
    "",
    "TIPOS DE DIAGNOSTICO:",
    str(tipo_dx.most_common()),
    "",
    "DIAGNOSTICOS:",
    str(diagnosticos.most_common()),
    "",
    "VALORES VACIOS:",
    str(vacios.most_common())
]

(SALIDA / "resumen_segunda_auditoria.txt").write_text(
    "\n".join(resumen),
    encoding="utf-8"
)

print("\nAUDITORIA COMPLETADA")
print("Total registros:", f"{total:,}")
print("Resultados guardados en:", SALIDA)
