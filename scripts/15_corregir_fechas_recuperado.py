
import csv
import re
import shutil
import tempfile

from datetime import date, timedelta
from pathlib import Path


# ============================================================
# 1. CONFIGURACION
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

CARPETA_ORIGINAL = (
    ROOT / "data" / "raw" / "clima" /
    "recuperado_13_distritos"
)

CARPETA_CORREGIDA = (
    ROOT / "data" / "processed" / "clima" /
    "recuperado_13_distritos_fecha_corregida"
)

CARPETA_REPORTES = (
    ROOT / "reports" / "recuperacion_clima"
)

ANIOS = range(2000, 2026)

UBIGEOS_ESPERADOS = {
    "150136", "150124", "150121",
    "150805", "150803", "150138",
    "150120", "070105", "070104",
    "070102", "150108", "140114",
    "110501"
}

COLUMNAS_REQUERIDAS = {
    "ano", "semana", "fecha_inicio",
    "fecha_fin", "ubigeo"
}


# ============================================================
# 2. FUNCIONES
# ============================================================

def detener(mensaje):
    raise SystemExit(
        "\nINTEGRIDAD NO GARANTIZADA\n" + mensaje
    )


def convertir_entero(valor, campo):
    try:
        return int(float(valor))
    except (ValueError, TypeError):
        detener(f"Valor invalido en {campo}: {valor}")


def convertir_fecha(valor, campo):
    try:
        return date.fromisoformat(valor.strip())
    except (ValueError, TypeError):
        detener(f"Fecha invalida en {campo}: {valor}")


# ============================================================
# 3. COMPROBAR CARPETAS
# ============================================================

print("=" * 65)
print("CORRECCION CONTROLADA DE FECHAS CLIMATICAS")
print("=" * 65)

if not CARPETA_ORIGINAL.exists():
    detener(f"No existe la carpeta original:\n{CARPETA_ORIGINAL}")

if CARPETA_ORIGINAL.resolve() == CARPETA_CORREGIDA.resolve():
    detener("La carpeta de salida no puede ser la carpeta original.")

archivos = {}

for archivo in CARPETA_ORIGINAL.glob("CLIMA_RECUPERADO_*.csv"):

    coincidencia = re.fullmatch(
        r"CLIMA_RECUPERADO_(\d{4})\.csv",
        archivo.name
    )

    if coincidencia:
        anio = int(coincidencia.group(1))
        archivos[anio] = archivo

if len(archivos) != 26:
    detener(
        f"Se esperaban 26 archivos. Encontrados: {len(archivos)}"
    )

if set(archivos) != set(ANIOS):
    detener("Los archivos no contienen exactamente los años 2000-2025.")

print("ARCHIVOS ENCONTRADOS:", len(archivos))


# ============================================================
# 4. AUDITORIA PREVIA Y CORRECCION EN MEMORIA
# ============================================================

archivos_preparados = []
resumen = []

total_registros = 0
total_corregidos = 0

for anio in ANIOS:

    archivo = archivos[anio]

    print(f"\nPROCESANDO: {anio}")

    with open(
        archivo,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as entrada:

        lector = csv.DictReader(entrada)

        columnas = lector.fieldnames

        if not columnas:
            detener(f"{archivo.name}: no tiene encabezados.")

        faltantes = COLUMNAS_REQUERIDAS - set(columnas)

        if faltantes:
            detener(
                f"{archivo.name}: faltan columnas {faltantes}"
            )

        filas = list(lector)

    if not filas:
        detener(f"{archivo.name}: archivo vacio.")

    semanas = sorted({
        convertir_entero(f["semana"], "semana")
        for f in filas
    })

    if len(semanas) not in (52, 53):
        detener(
            f"{anio}: cantidad de semanas incorrecta: {len(semanas)}"
        )

    if semanas != list(range(1, len(semanas) + 1)):
        detener(f"{anio}: existen semanas faltantes o incorrectas.")

    if len(filas) != 13 * len(semanas):
        detener(
            f"{anio}: cantidad de registros incorrecta: {len(filas)}"
        )

    ubigeos = {
        str(f["ubigeo"]).strip().zfill(6)
        for f in filas
    }

    if ubigeos != UBIGEOS_ESPERADOS:
        detener(
            f"{anio}: los UBIGEO no coinciden con los 13 distritos."
        )

    claves = set()
    fechas_semanales = {}
    filas_corregidas = []

    for fila in filas:

        if convertir_entero(fila["ano"], "ano") != anio:
            detener(f"{anio}: se encontro un registro de otro año.")

        semana = convertir_entero(fila["semana"], "semana")
        ubigeo = str(fila["ubigeo"]).strip().zfill(6)

        clave = (semana, ubigeo)

        if clave in claves:
            detener(
                f"{anio}: registro duplicado semana {semana}, "
                f"UBIGEO {ubigeo}"
            )

        claves.add(clave)

        inicio = convertir_fecha(
            fila["fecha_inicio"],
            "fecha_inicio"
        )

        fin_original = convertir_fecha(
            fila["fecha_fin"],
            "fecha_fin"
        )

        # Comprobar que el fin original es el limite
        # exclusivo de los siete dias de extraccion.

        if fin_original != inicio + timedelta(days=7):
            detener(
                f"{anio}, semana {semana}, UBIGEO {ubigeo}: "
                "fecha_fin no coincide con inicio + 7 dias. "
                "No se aplico ninguna correccion."
            )

        if semana not in fechas_semanales:

            fechas_semanales[semana] = {
                "inicio": inicio,
                "fin": fin_original,
                "ubigeos": set()
            }

        control = fechas_semanales[semana]

        if (
            control["inicio"] != inicio or
            control["fin"] != fin_original
        ):
            detener(
                f"{anio}: fechas inconsistentes entre distritos "
                f"en la semana {semana}."
            )

        control["ubigeos"].add(ubigeo)

        # Correccion: domingo exclusivo -> sabado inclusivo.

        nueva_fecha_fin = inicio + timedelta(days=6)

        nueva_fila = dict(fila)

        nueva_fila["fecha_fin"] = nueva_fecha_fin.isoformat()

        filas_corregidas.append(nueva_fila)

    # Comprobar los 13 distritos por semana.

    for semana in semanas:

        control = fechas_semanales[semana]

        if control["ubigeos"] != UBIGEOS_ESPERADOS:
            detener(
                f"{anio}: cobertura incompleta en semana {semana}."
            )

    # Comprobar continuidad del calendario.

    primera_fecha = fechas_semanales[1]["inicio"]

    for semana in semanas:

        fecha_esperada = (
            primera_fecha +
            timedelta(days=(semana - 1) * 7)
        )

        if fechas_semanales[semana]["inicio"] != fecha_esperada:
            detener(
                f"{anio}: discontinuidad temporal en semana {semana}."
            )

    archivos_preparados.append(
        (archivo.name, columnas, filas_corregidas)
    )

    registros = len(filas)

    total_registros += registros
    total_corregidos += registros

    resumen.append({
        "anio": anio,
        "registros": registros,
        "distritos": len(ubigeos),
        "semanas": len(semanas),
        "filas_corregidas": registros,
        "duplicados": 0,
        "estado": "OK"
    })

    print("  Registros:", registros)
    print("  Semanas:", len(semanas))
    print("  Distritos:", len(ubigeos))
    print("  Fechas validadas: OK")


# ============================================================
# 5. PUBLICAR COPIAS CORREGIDAS
# ============================================================

CARPETA_CORREGIDA.parent.mkdir(
    parents=True,
    exist_ok=True
)

with tempfile.TemporaryDirectory(
    prefix="correccion_clima_",
    dir=str(CARPETA_CORREGIDA.parent)
) as temporal:

    carpeta_temporal = Path(temporal)

    # Primero generar todos los archivos temporalmente.

    for nombre, columnas, filas in archivos_preparados:

        destino = carpeta_temporal / nombre

        with open(
            destino,
            "w",
            encoding="utf-8",
            newline=""
        ) as salida:

            escritor = csv.DictWriter(
                salida,
                fieldnames=columnas,
                lineterminator="\n"
            )

            escritor.writeheader()
            escritor.writerows(filas)

    # Solo después de preparar los 26 archivos,
    # copiar las versiones corregidas al destino.

    CARPETA_CORREGIDA.mkdir(
        parents=True,
        exist_ok=True
    )

    for nombre, _, _ in archivos_preparados:

        shutil.copy2(
            carpeta_temporal / nombre,
            CARPETA_CORREGIDA / nombre
        )


# ============================================================
# 6. VALIDACION DE LOS ARCHIVOS PUBLICADOS
# ============================================================

print("\n" + "=" * 65)
print("VALIDACION FINAL")
print("=" * 65)

for anio in ANIOS:

    archivo = (
        CARPETA_CORREGIDA /
        f"CLIMA_RECUPERADO_{anio}.csv"
    )

    with open(
        archivo,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as entrada:

        lector = csv.DictReader(entrada)

        filas = list(lector)

    for fila in filas:

        inicio = convertir_fecha(
            fila["fecha_inicio"],
            "fecha_inicio"
        )

        fin = convertir_fecha(
            fila["fecha_fin"],
            "fecha_fin"
        )

        if fin != inicio + timedelta(days=6):
            detener(
                f"Error de validacion en {archivo.name}"
            )

print("Archivos corregidos: 26")
print("Registros revisados:", total_registros)
print("Registros corregidos:", total_corregidos)
print("Errores de fechas: 0")


# ============================================================
# 7. GUARDAR REPORTE
# ============================================================

CARPETA_REPORTES.mkdir(
    parents=True,
    exist_ok=True
)

reporte = (
    CARPETA_REPORTES /
    "90_correccion_fechas_recuperados.csv"
)

with open(
    reporte,
    "w",
    encoding="utf-8-sig",
    newline=""
) as salida:

    campos = [
        "anio",
        "registros",
        "distritos",
        "semanas",
        "filas_corregidas",
        "duplicados",
        "estado"
    ]

    escritor = csv.DictWriter(
        salida,
        fieldnames=campos
    )

    escritor.writeheader()
    escritor.writerows(resumen)


# ============================================================
# 8. RESULTADO FINAL
# ============================================================

print("\n" + "=" * 65)
print("CORRECCION CLIMATICA FINALIZADA")
print("=" * 65)

print("ANIOS: 2000-2025")
print("ARCHIVOS:", len(archivos))
print("REGISTROS:", total_registros)
print("FECHAS CORREGIDAS:", total_corregidos)

print("\nDESTINO:")
print(CARPETA_CORREGIDA)

print("\nREPORTE:")
print(reporte)

print("\nARCHIVOS ORIGINALES: SIN MODIFICACIONES")
print("ARCHIVOS CONSOLIDADOS: SIN MODIFICACIONES")
print("=" * 65)
