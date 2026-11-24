from pathlib import Path
from collections import Counter
import pandas as pd

BASE = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

ARCHIVO = BASE / "data/raw/epidemiologia/data1.csv"
SALIDA = BASE / "reports/auditoria_integridad"

SALIDA.mkdir(parents=True, exist_ok=True)

total = 0
duplicados = 0
vistos = set()

edades_cero = Counter()
diagnosticos = Counter()

muestra_ceros = []
muestra_duplicados = []

print("INICIANDO QUINTA AUDITORIA")
print("Revision de duplicados e integridad epidemiologica\n")

for i, chunk in enumerate(pd.read_csv(
    ARCHIVO,
    chunksize=100_000,
    encoding="utf-8-sig",
    dtype="string",
    low_memory=False
), start=1):

    chunk.columns = (
        chunk.columns.str.strip().str.lower()
    )

    total += len(chunk)

    # 1. Identificar edades iguales a cero
    edad = pd.to_numeric(
        chunk["edad"], errors="coerce"
    )

    ceros = chunk[edad.eq(0)]

    edades_cero.update(
        ceros["tipo_edad"]
        .fillna("SIN DATO")
        .value_counts().to_dict()
    )

    if len(muestra_ceros) < 1000 and not ceros.empty:
        disponibles = 1000 - len(muestra_ceros)

        muestra_ceros.extend(
            ceros.head(disponibles).to_dict("records")
        )

    # 2. Revisar combinaciones diagnosticas
    diagnosticos.update(
        chunk.groupby(
            ["tipo_dx", "diagnostic", "enfermedad"],
            dropna=False
        ).size().to_dict()
    )

    # 3. Buscar filas completamente identicas
    hashes = pd.util.hash_pandas_object(
        chunk, index=False
    ).to_numpy()

    for pos, valor in enumerate(hashes):

        h = int(valor)

        if h in vistos:

            duplicados += 1

            if len(muestra_duplicados) < 100:
                muestra_duplicados.append(
                    chunk.iloc[pos].to_dict()
                )

        else:
            vistos.add(h)

    print(f"Bloque {i} revisado | Total: {total:,}")

# =================================
# GUARDAR RESULTADOS
# =================================

pd.DataFrame(
    muestra_ceros
).to_csv(
    SALIDA / "21_registros_edad_cero.csv",
    index=False,
    encoding="utf-8-sig"
)

pd.DataFrame(
    muestra_duplicados
).to_csv(
    SALIDA / "22_muestra_duplicados.csv",
    index=False,
    encoding="utf-8-sig"
)

df_diagnosticos = pd.DataFrame([
    {
        "tipo_dx": k[0],
        "diagnostic": k[1],
        "enfermedad": k[2],
        "registros": v
    }
    for k, v in diagnosticos.items()
])

df_diagnosticos.to_csv(
    SALIDA / "23_cruce_diagnosticos.csv",
    index=False,
    encoding="utf-8-sig"
)

# =================================
# INFORME
# =================================

resumen = [
    "QUINTA AUDITORIA - INTEGRIDAD",
    "=" * 45,
    f"Total de registros: {total:,}",
    f"Filas duplicadas adicionales: {duplicados:,}",
    f"Filas unicas por hash: {len(vistos):,}",
    "",
    "EDADES IGUALES A CERO:",
    str(edades_cero.most_common()),
    "",
    "COMBINACIONES DIAGNOSTICAS:",
    df_diagnosticos.to_string(index=False),
    "",
    "NOTA: Los duplicados son coincidencias exactas",
    "en las columnas originales. No se eliminan automaticamente."
]

(SALIDA / "resumen_integridad.txt").write_text(
    "\n".join(resumen),
    encoding="utf-8"
)

print("\n" + "=" * 45)
print("AUDITORIA COMPLETADA")
print("=" * 45)
print("Registros:", f"{total:,}")
print("Duplicados adicionales:", f"{duplicados:,}")
print("Edades cero:", edades_cero.most_common())
print("Resultados:", SALIDA)
