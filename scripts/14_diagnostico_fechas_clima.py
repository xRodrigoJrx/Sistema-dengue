
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

ORIGINAL = ROOT / "data/raw/clima/era5_land"
RECUPERADO = ROOT / "data/raw/clima/recuperado_13_distritos"

REPORTES = ROOT / "reports/recuperacion_clima"

ANIOS = range(2000, 2026)

CLAVES = ["ubigeo", "ano", "semana"]

FECHAS = ["fecha_inicio", "fecha_fin"]


def leer_archivo(path):

    df = pd.read_csv(
        path,
        sep=None,
        engine="python",
        dtype=str,
        encoding="utf-8-sig"
    )

    df.columns = [
        str(c).strip().lower()
        for c in df.columns
    ]

    df["ubigeo"] = (
        df["ubigeo"]
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.zfill(6)
    )

    df["ano"] = pd.to_numeric(
        df["ano"], errors="coerce"
    ).astype("Int64")

    df["semana"] = pd.to_numeric(
        df["semana"], errors="coerce"
    ).astype("Int64")

    return df


def convertir_fecha(serie):

    valores = serie.astype("string").str.strip()

    resultado = pd.Series(
        pd.NaT,
        index=serie.index,
        dtype="datetime64[ns]"
    )

    formato_iso = valores.str.match(
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    ).fillna(False)

    resultado.loc[formato_iso] = pd.to_datetime(
        valores.loc[formato_iso],
        errors="coerce"
    )

    resultado.loc[~formato_iso] = pd.to_datetime(
        valores.loc[~formato_iso],
        errors="coerce",
        dayfirst=True
    )

    return resultado.dt.normalize()


def main():

    REPORTES.mkdir(
        parents=True,
        exist_ok=True
    )

    resumen = []
    detalles = []

    print("=" * 60)
    print("DIAGNOSTICO DE FECHAS CLIMATICAS")
    print("=" * 60)

    for anio in ANIOS:

        print(f"\nANALIZANDO ANIO: {anio}")

        original_path = (
            ORIGINAL / f"clima_dengue_peru_{anio}.csv"
        )

        recuperado_path = (
            RECUPERADO / f"CLIMA_RECUPERADO_{anio}.csv"
        )

        if not original_path.exists():
            raise FileNotFoundError(original_path)

        if not recuperado_path.exists():
            raise FileNotFoundError(recuperado_path)

        original = leer_archivo(original_path)
        recuperado = leer_archivo(recuperado_path)

        for columna in FECHAS:

            if columna not in original.columns:
                raise ValueError(
                    f"{anio}: falta {columna} en original"
                )

            if columna not in recuperado.columns:
                raise ValueError(
                    f"{anio}: falta {columna} en recuperado"
                )

        original_reducido = original[
            CLAVES + FECHAS
        ].copy()

        recuperado_reducido = recuperado[
            CLAVES + FECHAS
        ].copy()

        if original_reducido.duplicated(CLAVES).any():
            raise ValueError(
                f"{anio}: claves duplicadas en original"
            )

        if recuperado_reducido.duplicated(CLAVES).any():
            raise ValueError(
                f"{anio}: claves duplicadas en recuperado"
            )

        comparacion = recuperado_reducido.merge(
            original_reducido,
            on=CLAVES,
            how="left",
            suffixes=("_rec", "_orig"),
            indicator=True,
            validate="one_to_one"
        )

        sin_correspondencia = int(
            (comparacion["_merge"] != "both").sum()
        )

        errores_por_fecha = {}

        for columna in FECHAS:

            rec = convertir_fecha(
                comparacion[f"{columna}_rec"]
            )

            orig = convertir_fecha(
                comparacion[f"{columna}_orig"]
            )

            no_parseables = (
                rec.isna() | orig.isna()
            )

            diferentes = (
                rec.notna() &
                orig.notna() &
                rec.ne(orig)
            )

            errores_por_fecha[columna] = int(
                diferentes.sum()
            )

            comparacion[f"{columna}_rec_parseada"] = rec

            comparacion[f"{columna}_orig_parseada"] = orig

            comparacion[f"{columna}_diferente"] = diferentes

            comparacion[f"{columna}_no_parseable"] = no_parseables

        comparacion["alguna_diferencia"] = (
            comparacion["fecha_inicio_diferente"] |
            comparacion["fecha_fin_diferente"] |
            comparacion["fecha_inicio_no_parseable"] |
            comparacion["fecha_fin_no_parseable"] |
            (comparacion["_merge"] != "both")
        )

        afectados = comparacion[
            comparacion["alguna_diferencia"]
        ].copy()

        print("REGISTROS RECUPERADOS:", len(recuperado))
        print("SIN CORRESPONDENCIA:", sin_correspondencia)

        print(
            "DIFERENCIAS FECHA INICIO:",
            errores_por_fecha["fecha_inicio"]
        )

        print(
            "DIFERENCIAS FECHA FIN:",
            errores_por_fecha["fecha_fin"]
        )

        print(
            "REGISTROS AFECTADOS:",
            len(afectados)
        )

        resumen.append({
            "anio": anio,
            "registros_recuperados": len(recuperado),
            "sin_correspondencia": sin_correspondencia,
            "diferencias_inicio": errores_por_fecha["fecha_inicio"],
            "diferencias_fin": errores_por_fecha["fecha_fin"],
            "registros_afectados": len(afectados)
        })

        for _, fila in afectados.iterrows():

            detalles.append({
                "anio": anio,
                "ubigeo": fila["ubigeo"],
                "semana": fila["semana"],
                "fecha_inicio_recuperada": fila["fecha_inicio_rec"],
                "fecha_inicio_original": fila["fecha_inicio_orig"],
                "fecha_fin_recuperada": fila["fecha_fin_rec"],
                "fecha_fin_original": fila["fecha_fin_orig"],
                "inicio_rec_parseada": fila["fecha_inicio_rec_parseada"],
                "inicio_orig_parseada": fila["fecha_inicio_orig_parseada"],
                "fin_rec_parseada": fila["fecha_fin_rec_parseada"],
                "fin_orig_parseada": fila["fecha_fin_orig_parseada"],
                "correspondencia": fila["_merge"]
            })

    resumen_df = pd.DataFrame(resumen)
    detalle_df = pd.DataFrame(detalles)

    resumen_df.to_csv(
        REPORTES / "63_resumen_diferencias_fechas.csv",
        index=False,
        encoding="utf-8-sig"
    )

    detalle_df.to_csv(
        REPORTES / "64_detalle_diferencias_fechas.csv",
        index=False,
        encoding="utf-8-sig"
    )

    print("\n" + "=" * 60)
    print("DIAGNOSTICO FINALIZADO")
    print("=" * 60)

    print(resumen_df.to_string(index=False))

    print("\nREPORTES GENERADOS:")
    print(REPORTES / "63_resumen_diferencias_fechas.csv")
    print(REPORTES / "64_detalle_diferencias_fechas.csv")

    print("\nNO SE MODIFICARON LOS DATOS ORIGINALES.")


if __name__ == "__main__":
    main()
