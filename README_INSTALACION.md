# Sistema Dengue — SQL Server Express + SSMS + Power BI + Groq

## Entorno detectado
- Instancia SQL Server: `SQLEXPRESS`
- Servidor local: `localhost\SQLEXPRESS`
- Driver ODBC: `ODBC Driver 18 for SQL Server` (también se detectó el 17)
- Autenticación recomendada: Windows Authentication

## Instalación
1. Extrae el ZIP en Descargas.
2. Abre PowerShell y ejecuta:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd C:\Users\xxter\Documents\Data_Dengue\Sistema
& "$env:USERPROFILE\Downloads\paquete_dengue_sqlserver\INSTALAR.ps1"
```

Si extraes el ZIP en otra carpeta, cambia la ruta de `INSTALAR.ps1`.

El instalador respalda los archivos de código que reemplaza, conserva el `.env` existente y no modifica los datasets ni los modelos previos.

## Crear la base de datos
1. Abre SSMS 22.
2. Conéctate al servidor `localhost\SQLEXPRESS` usando Windows Authentication.
3. Abre `sql\schema.sql` desde la carpeta del proyecto.
4. Ejecuta el script completo con F5.
5. En PowerShell, desde la raíz del proyecto, ejecuta:

```powershell
.\.venv\Scripts\python.exe .\scripts\24_probar_sqlserver.py
```

## Ejecución del flujo predictivo
El paquete no vuelve a limpiar ni reconstruir el dataset maestro. Utiliza el dataset de modelamiento existente. Para obtener modelos específicos de horizontes 1, 2, 3 y 4 semanas:

```powershell
.\.venv\Scripts\python.exe .\scripts\20_entrenar_pronosticos_dengue.py
.\.venv\Scripts\python.exe .\scripts\21_evaluar_pronosticos.py
.\.venv\Scripts\python.exe .\scripts\22_generar_pronosticos_dengue.py
.\.venv\Scripts\python.exe .\scripts\23_exportar_sqlserver.py
```

El script 20 limita por defecto el entrenamiento a una muestra aleatoria de 100,000 filas por horizonte para contener el tiempo de ejecución. Puedes cambiarlo antes de ejecutar con:

```powershell
$env:DENGUE_MAX_TRAIN_ROWS = "150000"
```

La selección final se realiza por MAE de VALIDATION, comparando persistencia, baseline estacional, Random Forest e HistGradientBoosting. TEST solo se informa como evaluación final. El entrenamiento y la evaluación consideran como objetivo únicamente las semanas con `registro_minsa = 1`; una semana sin registro MINSA no se interpreta como cero casos.

Para actualizar únicamente pronósticos y métricas después de generar un nuevo archivo, sin recargar las 2.56 millones de filas históricas:

```powershell
.\.venv\Scripts\python.exe .\scripts\23_exportar_sqlserver.py --solo-pronosticos
```

Para volver a cargar absolutamente todo, de forma destructiva y explícita:

```powershell
.\.venv\Scripts\python.exe .\scripts\23_exportar_sqlserver.py --replace
```

## Consultor Groq
1. Abre `.env` y pega tu clave en `GROQ_API_KEY=`.
2. No compartas ni subas `.env` a GitHub.
3. Inicia la API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.consultor_groq:app --host 127.0.0.1 --port 8000 --reload
```

4. Prueba `http://127.0.0.1:8000/docs` y `http://127.0.0.1:8000/health`.

Groq solo clasifica la pregunta en una intención y parámetros pequeños. SQL Server obtiene los datos y Python construye la respuesta y la configuración de visualización. No se envían filas del dataset ni resultados completos a Groq. Hay caché local de consultas repetidas y clasificación local de respaldo si no se configura la API key.

## Conexión con Power BI
En Power BI Desktop:
1. Obtener datos → Base de datos SQL Server.
2. Servidor: `localhost\SQLEXPRESS`.
3. Base de datos: `dengue_analytics`.
4. Modo: Importar.
5. Autenticación: Windows.
6. Selecciona `dbo.dim_distrito`, `dbo.fact_semanal_dengue`, `dbo.fact_pronosticos`, `dbo.fact_metricas_modelo` o las vistas `vw_*`.

Relaciones recomendadas:
- `dim_distrito[ubigeo]` 1:* `fact_semanal_dengue[ubigeo]`
- `dim_distrito[ubigeo]` 1:* `fact_pronosticos[ubigeo]`

**Importante sobre epidemiología:** en `fact_semanal_dengue`, `registro_minsa = 0` significa que esa semana no tuvo registro MINSA en la fuente; no equivale a cero casos confirmados. Para gráficos de casos reportados, filtra `registro_minsa = 1`.

## Alcance de la integración Groq/Power BI
La API devuelve datos y un objeto `visualizacion` (tipo de gráfico, eje y serie) para que la aplicación web pueda cambiar el gráfico mostrado según la consulta. Power BI Desktop no cambia automáticamente sus visuales nativos al recibir una respuesta de Groq; para esa interacción dinámica se necesita que la interfaz web consuma `/consultar` y renderice el gráfico con esos metadatos, o desarrollar una integración específica de Power BI.

## Advertencia metodológica
El pronóstico futuro utiliza las últimas variables climáticas observadas porque el proyecto no incorporará por ahora una fuente adicional de clima futuro. El pronóstico parte de la última semana disponible en el dataset; no representa una actualización a 2026 si el dataset termina en 2025.
