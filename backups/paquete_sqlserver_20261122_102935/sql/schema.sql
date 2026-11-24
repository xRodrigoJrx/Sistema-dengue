CREATE DATABASE IF NOT EXISTS dengue_analytics
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE dengue_analytics;

CREATE TABLE IF NOT EXISTS dim_distrito (
    ubigeo CHAR(6) NOT NULL,
    departamento VARCHAR(100) NULL,
    provincia VARCHAR(100) NULL,
    distrito VARCHAR(100) NULL,
    PRIMARY KEY (ubigeo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fact_casos_semanales (
    ubigeo CHAR(6) NOT NULL,
    ano SMALLINT NOT NULL,
    semana SMALLINT NOT NULL,
    fecha_inicio DATE NOT NULL,
    casos_reportados BIGINT NOT NULL DEFAULT 0,
    poblacion_proyectada DECIMAL(15,2) NULL,
    PRIMARY KEY (ubigeo, ano, semana),
    CONSTRAINT fk_casos_distrito FOREIGN KEY (ubigeo)
      REFERENCES dim_distrito(ubigeo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fact_pronosticos (
    id BIGINT NOT NULL AUTO_INCREMENT,
    ubigeo CHAR(6) NOT NULL,
    fecha_generacion DATE NOT NULL,
    fecha_origen DATE NOT NULL,
    fecha_objetivo DATE NOT NULL,
    ano_objetivo SMALLINT NOT NULL,
    semana_objetivo SMALLINT NOT NULL,
    horizonte_semanas TINYINT NOT NULL,
    pred_baseline_persistencia DECIMAL(15,4) NULL,
    pred_baseline_estacional DECIMAL(15,4) NULL,
    pred_random_forest DECIMAL(15,4) NULL,
    pred_hist_gradient_boosting DECIMAL(15,4) NULL,
    modelo_seleccionado VARCHAR(60) NOT NULL,
    prediccion_final DECIMAL(15,4) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_pronostico (ubigeo, fecha_generacion, horizonte_semanas),
    KEY idx_pronostico_fecha (fecha_generacion),
    KEY idx_pronostico_horizonte (horizonte_semanas),
    KEY idx_pronostico_ubigeo (ubigeo),
    CONSTRAINT chk_horizonte CHECK (horizonte_semanas BETWEEN 1 AND 4),
    CONSTRAINT fk_pronostico_distrito FOREIGN KEY (ubigeo)
      REFERENCES dim_distrito(ubigeo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS fact_metricas_modelo (
    id BIGINT NOT NULL AUTO_INCREMENT,
    horizonte TINYINT NOT NULL,
    periodo VARCHAR(20) NOT NULL,
    modelo VARCHAR(60) NOT NULL,
    registros_evaluados INT NULL,
    mae DECIMAL(15,6) NULL,
    rmse DECIMAL(15,6) NULL,
    r2 DECIMAL(15,6) NULL,
    mae_positivos DECIMAL(15,6) NULL,
    casos_reales DECIMAL(18,2) NULL,
    casos_predichos DECIMAL(18,2) NULL,
    error_total_pct DECIMAL(15,6) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_metrica (horizonte, periodo, modelo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;