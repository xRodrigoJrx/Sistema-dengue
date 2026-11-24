/*
  SISTEMA DENGUE - SQL SERVER EXPRESS
  Ejecutar completo en SSMS 22 conectado a .\SQLEXPRESS con autenticación Windows.
*/
IF DB_ID(N'dengue_analytics') IS NULL
BEGIN
    CREATE DATABASE dengue_analytics;
END;
GO

USE dengue_analytics;
GO

IF OBJECT_ID(N'dbo.dim_distrito', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.dim_distrito (
        ubigeo CHAR(6) NOT NULL,
        departamento NVARCHAR(100) NULL,
        provincia NVARCHAR(100) NULL,
        distrito NVARCHAR(100) NULL,
        CONSTRAINT PK_dim_distrito PRIMARY KEY CLUSTERED (ubigeo)
    );
END;
GO

IF OBJECT_ID(N'dbo.fact_semanal_dengue', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.fact_semanal_dengue (
        ubigeo CHAR(6) NOT NULL,
        ano SMALLINT NOT NULL,
        semana SMALLINT NOT NULL,
        fecha_inicio DATE NOT NULL,
        fecha_fin DATE NULL,
        casos_reportados BIGINT NOT NULL CONSTRAINT DF_fact_casos DEFAULT (0),
        registro_minsa BIT NULL,
        poblacion_proyectada FLOAT NULL,
        tmean FLOAT NULL,
        tmax FLOAT NULL,
        tmin FLOAT NULL,
        humr FLOAT NULL,
        ptot FLOAT NULL,
        clima_recuperado BIT NULL,
        clima_grupo NVARCHAR(50) NULL,
        clima_metodo_extraccion NVARCHAR(80) NULL,
        CONSTRAINT PK_fact_semanal_dengue PRIMARY KEY CLUSTERED (ubigeo, ano, semana),
        CONSTRAINT FK_fact_semanal_distrito FOREIGN KEY (ubigeo) REFERENCES dbo.dim_distrito(ubigeo)
    );
    CREATE INDEX IX_fact_semanal_fecha ON dbo.fact_semanal_dengue(fecha_inicio) INCLUDE (casos_reportados, tmean, tmax, tmin, humr, ptot);
    CREATE INDEX IX_fact_semanal_ano_semana ON dbo.fact_semanal_dengue(ano, semana) INCLUDE (ubigeo, casos_reportados, registro_minsa);
END;
GO

IF OBJECT_ID(N'dbo.fact_pronosticos', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.fact_pronosticos (
        id BIGINT IDENTITY(1,1) NOT NULL,
        ubigeo CHAR(6) NOT NULL,
        fecha_generacion DATE NOT NULL,
        fecha_origen DATE NOT NULL,
        fecha_objetivo DATE NOT NULL,
        ano_objetivo SMALLINT NOT NULL,
        semana_objetivo SMALLINT NOT NULL,
        horizonte_semanas TINYINT NOT NULL,
        pred_baseline_persistencia FLOAT NULL,
        pred_baseline_estacional FLOAT NULL,
        pred_random_forest FLOAT NULL,
        pred_hist_gradient_boosting FLOAT NULL,
        modelo_seleccionado NVARCHAR(60) NOT NULL,
        prediccion_final FLOAT NOT NULL,
        CONSTRAINT PK_fact_pronosticos PRIMARY KEY CLUSTERED (id),
        CONSTRAINT FK_fact_pronosticos_distrito FOREIGN KEY (ubigeo) REFERENCES dbo.dim_distrito(ubigeo),
        CONSTRAINT CK_fact_pronosticos_horizonte CHECK (horizonte_semanas BETWEEN 1 AND 4)
    );
    CREATE UNIQUE INDEX UX_fact_pronosticos_unico ON dbo.fact_pronosticos(ubigeo, fecha_generacion, horizonte_semanas);
    CREATE INDEX IX_fact_pronosticos_fecha_horizonte ON dbo.fact_pronosticos(fecha_generacion, horizonte_semanas) INCLUDE (prediccion_final, modelo_seleccionado);
END;
GO

IF OBJECT_ID(N'dbo.fact_metricas_modelo', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.fact_metricas_modelo (
        id BIGINT IDENTITY(1,1) NOT NULL,
        horizonte TINYINT NOT NULL,
        periodo NVARCHAR(20) NOT NULL,
        modelo NVARCHAR(60) NOT NULL,
        registros_evaluados INT NULL,
        mae FLOAT NULL,
        rmse FLOAT NULL,
        r2 FLOAT NULL,
        mae_positivos FLOAT NULL,
        casos_reales FLOAT NULL,
        casos_predichos FLOAT NULL,
        error_total_pct FLOAT NULL,
        CONSTRAINT PK_fact_metricas_modelo PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_fact_metricas_modelo UNIQUE (horizonte, periodo, modelo)
    );
END;
GO

/* Vistas listas para conectar desde Power BI */
CREATE OR ALTER VIEW dbo.vw_resumen_nacional_pronostico AS
SELECT
    fecha_generacion,
    fecha_objetivo,
    ano_objetivo,
    semana_objetivo,
    horizonte_semanas,
    SUM(prediccion_final) AS casos_pronosticados,
    COUNT(DISTINCT ubigeo) AS distritos
FROM dbo.fact_pronosticos
GROUP BY fecha_generacion, fecha_objetivo, ano_objetivo, semana_objetivo, horizonte_semanas;
GO

CREATE OR ALTER VIEW dbo.vw_ranking_distritos_pronostico AS
SELECT
    p.fecha_generacion,
    p.fecha_objetivo,
    p.horizonte_semanas,
    d.ubigeo,
    d.departamento,
    d.provincia,
    d.distrito,
    p.prediccion_final,
    p.modelo_seleccionado
FROM dbo.fact_pronosticos AS p
INNER JOIN dbo.dim_distrito AS d ON d.ubigeo = p.ubigeo;
GO

CREATE OR ALTER VIEW dbo.vw_historico_dengue AS
SELECT
    f.ubigeo, d.departamento, d.provincia, d.distrito,
    f.ano, f.semana, f.fecha_inicio, f.fecha_fin,
    f.casos_reportados, f.registro_minsa, f.poblacion_proyectada,
    f.tmean, f.tmax, f.tmin, f.humr, f.ptot,
    f.clima_recuperado, f.clima_grupo
FROM dbo.fact_semanal_dengue AS f
INNER JOIN dbo.dim_distrito AS d ON d.ubigeo = f.ubigeo;
GO
