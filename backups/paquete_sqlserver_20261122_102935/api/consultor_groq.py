import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from groq import Groq
from sqlalchemy import text
from scripts.dengue_common import get_mysql_engine, ROOT

load_dotenv(ROOT / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
if not GROQ_API_KEY:
    raise RuntimeError("Falta GROQ_API_KEY en el archivo .env")

client = Groq(api_key=GROQ_API_KEY)
engine = get_mysql_engine()
app = FastAPI(title="Consultor Inteligente de Dengue", version="1.0.0")
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in origins],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)

class Consulta(BaseModel):
    pregunta: str = Field(min_length=3, max_length=500)

CACHE = {}
SYSTEM_PROMPT = """
Eres un clasificador de preguntas para un sistema epidemiolÃ³gico de dengue en PerÃº.
Devuelve solamente un JSON vÃ¡lido con estos campos:
intent, ubicacion, horizonte, top_n.
Intenciones permitidas: resumen_nacional, ranking_distritos, pronostico_ubicacion,
tendencia_historica, comparar_horizontes.
Si preguntan por distritos con mÃ¡s casos: ranking_distritos.
Si preguntan por un distrito, provincia o departamento: pronostico_ubicacion.
Si preguntan por evoluciÃ³n histÃ³rica: tendencia_historica.
Si comparan semanas futuras: comparar_horizontes.
Si preguntan por panorama general: resumen_nacional.
Si no especifican horizonte, usa 4. horizonte debe estar entre 1 y 4.
top_n debe estar entre 5 y 20. ubicacion debe ser texto o cadena vacÃ­a.
No inventes cifras ni escribas SQL.
"""


def classify_question(question):
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question}
        ],
        temperature=0,
        max_completion_tokens=180,
        response_format={"type": "json_object"}
    )
    import json
    plan = json.loads(response.choices[0].message.content)
    allowed = {
        "resumen_nacional", "ranking_distritos", "pronostico_ubicacion",
        "tendencia_historica", "comparar_horizontes"
    }
    if plan.get("intent") not in allowed:
        plan["intent"] = "resumen_nacional"
    try:
        plan["horizonte"] = max(1, min(4, int(plan.get("horizonte", 4))))
    except (TypeError, ValueError):
        plan["horizonte"] = 4
    try:
        plan["top_n"] = max(5, min(20, int(plan.get("top_n", 10))))
    except (TypeError, ValueError):
        plan["top_n"] = 10
    plan["ubicacion"] = str(plan.get("ubicacion", "")).strip()[:100]
    return plan


def latest_forecast_date():
    with engine.connect() as conn:
        value = conn.execute(text("SELECT MAX(fecha_generacion) FROM fact_pronosticos")).scalar()
    if value is None:
        raise HTTPException(status_code=409, detail="TodavÃ­a no hay pronÃ³sticos en MySQL.")
    return value


def execute_query(plan, forecast_date):
    intent = plan["intent"]
    location = plan["ubicacion"]
    params = {
        "fecha": forecast_date,
        "horizonte": plan["horizonte"],
        "patron": f"%{location.lower()}%",
        "ubicacion": location,
        "top_n": plan["top_n"]
    }

    if intent == "ranking_distritos":
        sql = """
        SELECT d.ubigeo, d.departamento, d.provincia, d.distrito,
               SUM(p.prediccion_final) AS casos_pronosticados
        FROM fact_pronosticos p
        JOIN dim_distrito d ON d.ubigeo = p.ubigeo
        WHERE p.fecha_generacion = :fecha
          AND p.horizonte_semanas = :horizonte
          AND (:ubicacion = '' OR LOWER(d.departamento) LIKE :patron
               OR LOWER(d.provincia) LIKE :patron)
        GROUP BY d.ubigeo, d.departamento, d.provincia, d.distrito
        ORDER BY casos_pronosticados DESC
        LIMIT :top_n
        """
    elif intent == "pronostico_ubicacion":
        sql = """
        SELECT d.ubigeo, d.departamento, d.provincia, d.distrito,
               p.fecha_objetivo, p.semana_objetivo, p.horizonte_semanas,
               p.prediccion_final, p.modelo_seleccionado
        FROM fact_pronosticos p
        JOIN dim_distrito d ON d.ubigeo = p.ubigeo
        WHERE p.fecha_generacion = :fecha
          AND p.horizonte_semanas = :horizonte
          AND (LOWER(d.distrito) LIKE :patron OR LOWER(d.provincia) LIKE :patron
               OR LOWER(d.departamento) LIKE :patron OR d.ubigeo = :ubicacion)
        ORDER BY p.prediccion_final DESC
        LIMIT :top_n
        """
    elif intent == "tendencia_historica":
        sql = """
        SELECT c.ano, SUM(c.casos_reportados) AS casos_totales
        FROM fact_casos_semanales c
        JOIN dim_distrito d ON d.ubigeo = c.ubigeo
        WHERE (:ubicacion = '' OR LOWER(d.departamento) LIKE :patron
               OR LOWER(d.provincia) LIKE :patron)
        GROUP BY c.ano ORDER BY c.ano
        """
    elif intent == "comparar_horizontes":
        sql = """
        SELECT p.horizonte_semanas,
               SUM(p.prediccion_final) AS casos_pronosticados,
               AVG(p.prediccion_final) AS promedio_distrital
        FROM fact_pronosticos p
        WHERE p.fecha_generacion = :fecha
        GROUP BY p.horizonte_semanas ORDER BY p.horizonte_semanas
        """
    else:
        sql = """
        SELECT p.horizonte_semanas,
               SUM(p.prediccion_final) AS casos_pronosticados,
               COUNT(DISTINCT p.ubigeo) AS distritos_evaluados,
               AVG(p.prediccion_final) AS promedio_distrital
        FROM fact_pronosticos p
        WHERE p.fecha_generacion = :fecha
          AND p.horizonte_semanas = :horizonte
        GROUP BY p.horizonte_semanas
        """

    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(row) for row in rows]


def serialize_rows(rows):
    output = []
    for row in rows:
        clean = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, (date, datetime)):
                value = value.isoformat()
            clean[key] = value
        output.append(clean)
    return output


def build_answer(plan, rows):
    if not rows:
        return "No se encontraron resultados para esa consulta."
    intent = plan["intent"]
    if intent == "ranking_distritos":
        lines = ["Distritos con mayor pronÃ³stico de dengue:"]
        for i, row in enumerate(rows, 1):
            lines.append(f"{i}. {row['distrito']} ({row['departamento']}): {row['casos_pronosticados']:,.1f} casos.")
        return "\n".join(lines)
    if intent == "pronostico_ubicacion":
        lines = ["PronÃ³sticos encontrados:"]
        for row in rows:
            lines.append(f"{row['distrito']}, {row['departamento']}: {row['prediccion_final']:,.1f} casos en semana {row['semana_objetivo']} (horizonte +{row['horizonte_semanas']}).")
        return "\n".join(lines)
    if intent == "tendencia_historica":
        return "\n".join(["EvoluciÃ³n histÃ³rica de casos:"] + [f"{r['ano']}: {r['casos_totales']:,.0f} casos" for r in rows])
    if intent == "comparar_horizontes":
        return "\n".join(["ComparaciÃ³n de horizontes:"] + [f"Semana +{r['horizonte_semanas']}: {r['casos_pronosticados']:,.1f} casos" for r in rows])
    row = rows[0]
    return f"Para el horizonte de {row['horizonte_semanas']} semanas se estiman {row['casos_pronosticados']:,.1f} casos en {row['distritos_evaluados']} distritos."


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "mysql", "service": "consultor_dengue"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo conectar con MySQL: {exc}")


@app.post("/consultar")
def consultar(request: Consulta):
    question = request.pregunta.strip()
    forecast_date = latest_forecast_date()
    key = (question.lower(), str(forecast_date))
    if key in CACHE:
        return CACHE[key]
    try:
        plan = classify_question(question)
        rows = serialize_rows(execute_query(plan, forecast_date))
        response = {
            "respuesta": build_answer(plan, rows),
            "intencion": plan["intent"],
            "horizonte": plan["horizonte"],
            "fecha_generacion": str(forecast_date),
            "datos": rows
        }
        if len(CACHE) >= 200:
            CACHE.pop(next(iter(CACHE)))
        CACHE[key] = response
        return response
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Error del consultor: {exc}")
        raise HTTPException(status_code=500, detail="No se pudo procesar la consulta.")