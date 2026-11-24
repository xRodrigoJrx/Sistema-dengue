from pathlib import Path
import pandas as pd
from sqlalchemy import text
from dengue_common import get_sql_engine, ROOT

engine = get_sql_engine()

consultas = {
    "RESUMEN HISTORICO": """
        SELECT
            COUNT_BIG(*) AS total_registros,
            SUM(CASE WHEN registro_minsa=1 THEN 1 ELSE 0 END)
                AS registros_minsa,
            SUM(CASE WHEN registro_minsa=1
                     THEN casos_reportados ELSE 0 END)
                AS casos_reportados,
            COUNT(DISTINCT CASE WHEN registro_minsa=1
                                THEN ubigeo END)
                AS distritos_con_registro,
            AVG(CASE WHEN registro_minsa=1
                     THEN CAST(casos_reportados AS FLOAT) END)
                AS promedio_casos_por_registro,
            SUM(CASE WHEN tmean IS NOT NULL THEN 1 ELSE 0 END)
                AS registros_con_tmean,
            AVG(CAST(tmean AS FLOAT)) AS temperatura_media,
            SUM(CASE WHEN tmax IS NOT NULL THEN 1 ELSE 0 END)
                AS registros_con_tmax,
            SUM(CASE WHEN humr IS NOT NULL THEN 1 ELSE 0 END)
                AS registros_con_humedad,
            SUM(CASE WHEN ptot IS NOT NULL THEN 1 ELSE 0 END)
                AS registros_con_precipitacion
        FROM dbo.fact_semanal_dengue;
    """,

    "CALIDAD DE DISTRITOS": """
        SELECT
            COUNT_BIG(*) AS total_distritos,
            COUNT(DISTINCT ubigeo) AS ubigeos_unicos,
            SUM(CASE WHEN departamento IS NULL
                OR LTRIM(RTRIM(departamento))=''
                THEN 1 ELSE 0 END) AS departamentos_vacios,
            SUM(CASE WHEN provincia IS NULL
                OR LTRIM(RTRIM(provincia))=''
                THEN 1 ELSE 0 END) AS provincias_vacias,
            SUM(CASE WHEN distrito IS NULL
                OR LTRIM(RTRIM(distrito))=''
                THEN 1 ELSE 0 END) AS distritos_vacios,
            COUNT(DISTINCT departamento) AS departamentos_unicos
        FROM dbo.dim_distrito;
    """,

    "DISPONIBILIDAD CLIMATICA POR ANIO": """
        SELECT
            YEAR(fecha_inicio) AS anio,
            COUNT_BIG(*) AS registros,
            SUM(CASE WHEN tmean IS NOT NULL THEN 1 ELSE 0 END)
                AS tmean_disponible,
            SUM(CASE WHEN tmin IS NOT NULL THEN 1 ELSE 0 END)
                AS tmin_disponible,
            SUM(CASE WHEN tmax IS NOT NULL THEN 1 ELSE 0 END)
                AS tmax_disponible,
            SUM(CASE WHEN humr IS NOT NULL THEN 1 ELSE 0 END)
                AS humedad_disponible,
            SUM(CASE WHEN ptot IS NOT NULL THEN 1 ELSE 0 END)
                AS precipitacion_disponible
        FROM dbo.fact_semanal_dengue
        GROUP BY YEAR(fecha_inicio)
        ORDER BY anio;
    """,

    "COLUMNAS DE DIM DISTRITO": """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo'
          AND TABLE_NAME='dim_distrito'
        ORDER BY ORDINAL_POSITION;
    """,

    "FECHAS DE PRONOSTICOS": """
        SELECT
            fecha_generacion,
            fecha_origen,
            MIN(fecha_objetivo) AS primera_fecha_objetivo,
            MAX(fecha_objetivo) AS ultima_fecha_objetivo,
            COUNT_BIG(*) AS registros,
            SUM(prediccion_final) AS casos_estimados
        FROM dbo.fact_pronosticos
        GROUP BY fecha_generacion, fecha_origen;
    """,

    "PRONOSTICOS POR HORIZONTE": """
        SELECT
            horizonte_semanas,
            modelo_seleccionado,
            COUNT_BIG(*) AS distritos,
            SUM(prediccion_final) AS casos_estimados,
            AVG(prediccion_final) AS promedio_distrital,
            MAX(prediccion_final) AS maximo_distrital
        FROM dbo.fact_pronosticos
        GROUP BY horizonte_semanas, modelo_seleccionado
        ORDER BY horizonte_semanas;
    """,

    "EVALUACION HORIZONTE 4": """
        SELECT
            horizonte,
            periodo,
            modelo,
            mae,
            rmse,
            r2,
            error_total_pct
        FROM dbo.fact_metricas_modelo
        WHERE horizonte=4
        ORDER BY periodo, mae;
    """
}

lineas = []

try:
    with engine.connect() as conn:
        print("\n========================================")
        print("DIAGNOSTICO DE CALIDAD DENGUE")
        print("========================================")

        for nombre, sql in consultas.items():
            df = pd.read_sql_query(text(sql), conn)

            print("\n========== " + nombre + " ==========")
            print(df.to_string(index=False))

            lineas.append("\n========== " + nombre + " ==========")
            lineas.append(df.to_string(index=False))

    destino = ROOT / "reports" / "powerbi"
    destino.mkdir(parents=True, exist_ok=True)

    archivo = destino / "diagnostico_dashboard.txt"
    archivo.write_text(
        "\n".join(lineas),
        encoding="utf-8"
    )

    print("\n========================================")
    print("DIAGNOSTICO COMPLETADO")
    print("Reporte:", archivo)
    print("No se modificaron tablas ni modelos.")
    print("========================================")

finally:
    engine.dispose()
