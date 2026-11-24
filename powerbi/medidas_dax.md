# Medidas DAX iniciales para Power BI

Crea estas medidas en Power BI después de importar las tablas SQL Server.

```DAX
Casos reportados =
CALCULATE(
    SUM(fact_semanal_dengue[casos_reportados]),
    fact_semanal_dengue[registro_minsa] = 1
)

Pronostico de dengue =
SUM(fact_pronosticos[prediccion_final])

Distritos pronosticados =
DISTINCTCOUNT(fact_pronosticos[ubigeo])

Promedio pronosticado por distrito =
AVERAGE(fact_pronosticos[prediccion_final])

Ultima fecha de pronostico =
MAX(fact_pronosticos[fecha_generacion])

Error absoluto medio =
AVERAGE(fact_metricas_modelo[mae])
```

## Relaciones

- `dim_distrito[ubigeo]` (1) → `fact_semanal_dengue[ubigeo]` (*)
- `dim_distrito[ubigeo]` (1) → `fact_pronosticos[ubigeo]` (*)

Usa filtro en una sola dirección desde la dimensión hacia las tablas de hechos.

## Visuales sugeridos

- Mapa: `dim_distrito` + medida `Pronostico de dengue`, con filtro de `horizonte_semanas`.
- Línea histórica: `fecha_inicio` y `Casos reportados`.
- Barras: `distrito` y `Pronostico de dengue`, orden descendente.
- Tarjetas: `Casos reportados`, `Pronostico de dengue`, `Distritos pronosticados`.
- Tabla de desempeño: `horizonte`, `periodo`, `modelo`, `mae`, `rmse`, `r2`.

**No interpretes `casos_reportados = 0` como cero confirmado cuando `registro_minsa = 0`; esa combinación representa ausencia de registro en la fuente.**
