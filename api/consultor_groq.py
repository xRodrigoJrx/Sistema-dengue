from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from pydantic import BaseModel, Field
from sqlalchemy import text

from scripts.dengue_common import ROOT, get_sql_engine

load_dotenv(ROOT / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
engine = get_sql_engine()

app = FastAPI(title="Consultor Inteligente de Dengue", version="1.0.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)


class Consulta(BaseModel):
    pregunta: str = Field(min_length=3, max_length=350)


SYSTEM_PROMPT = """Clasifica la pregunta de un usuario sobre dengue en Perú. Devuelve SOLO JSON con: intent, ubicacion, horizonte, top_n. intent debe ser uno de: resumen_nacional, ranking_distritos, pronostico_ubicacion, tendencia_historica, comparar_horizontes. horizonte entero 1-4 (por defecto 4), top_n entero 5-20 (por defecto 10), ubicacion texto o cadena vacía. No generes SQL, no inventes datos ni respondas la pregunta."""
CACHE = {}


def local_classify(question: str) -> dict:
    q = question.lower()
    intent = "resumen_nacional"
    if any(k in q for k in ["ranking", "mayor cantidad", "más casos", "mas casos", "top distritos", "distritos con más"]):
        intent = "ranking_distritos"
    elif any(k in q for k in ["comparar", "compara", "horizontes", "semanas futuras"]):
        intent = "comparar_horizontes"
    elif any(k in q for k in ["histórico", "historico", "evolución", "evolucion", "años anteriores", "tendencia"]):
        intent = "tendencia_historica"
    elif any(k in q for k in ["pronóstico", "pronostico", "previsión", "prevision", "distrito", "provincia", "departamento"]):
        intent = "pronostico_ubicacion"

    horizon_match = re.search(r"(?:\+|semana\s+|horizonte\s+)([1-4])", q)
    horizon = int(horizon_match.group(1)) if horizon_match else 4
    top_match = re.search(r"\b(5|10|15|20)\b", q)
    top_n = int(top_match.group(1)) if top_match else 10
    location = ""
    match = re.search(r"\b(?:en|de|del|para)\s+([a-záéíóúñ][a-záéíóúñ\s-]{2,50})", q)
    if match:
        location = match.group(1).strip(" .?!")
        location = re.sub(r"\s+(?:para|durante|en la semana|en semana|a la semana|a|semana|horizonte).*", "", location)
    return {"intent": intent, "ubicacion": location[:80], "horizonte": horizon, "top_n": top_n}


@lru_cache(maxsize=300)
def classify_question(question: str) -> dict:
    local_plan = local_classify(question)
    q = question.casefold()
    explicit_summary = any(k in q for k in ["panorama nacional", "resumen nacional", "resumen general", "situación general", "situacion general"])
    # Common intents are routed locally. Groq is reserved for ambiguous wording.
    if client is None or local_plan["intent"] != "resumen_nacional" or explicit_summary:
        return local_plan
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question[:350]}
            ],
            temperature=0,
            max_completion_tokens=100,
            response_format={"type": "json_object"}
        )
        plan = json.loads(response.choices[0].message.content)
    except Exception:
        # If Groq is temporarily unavailable, use deterministic local routing.
        return local_classify(question)

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
    plan["ubicacion"] = str(plan.get("ubicacion", "")).strip()[:80]
    return plan


def latest_forecast_date():
    with engine.connect() as conn:
        value = conn.execute(text("SELECT MAX(fecha_generacion) FROM dbo.fact_pronosticos")).scalar()
    if value is None:
        raise HTTPException(status_code=409, detail="Todavía no hay pronósticos en SQL Server.")
    return value


def execute_query(plan: dict, forecast_date):
    intent = plan["intent"]
    location = plan.get("ubicacion", "")
    params = {
        "fecha": forecast_date,
        "horizonte": plan["horizonte"],
        "patron": f"%{location}%",
        "ubicacion": location,
        "top_n": plan["top_n"]
    }

    if intent == "ranking_distritos":
        sql = text("""
            SELECT d.ubigeo, d.departamento, d.provincia, d.distrito,
                   p.prediccion_final AS casos_pronosticados,
                   p.horizonte_semanas, p.fecha_objetivo
            FROM dbo.fact_pronosticos AS p
            INNER JOIN dbo.dim_distrito AS d ON d.ubigeo = p.ubigeo
            WHERE p.fecha_generacion = :fecha
              AND p.horizonte_semanas = :horizonte
              AND (:ubicacion = '' OR d.departamento LIKE :patron OR d.provincia LIKE :patron)
            ORDER BY p.prediccion_final DESC
            OFFSET 0 ROWS FETCH NEXT :top_n ROWS ONLY
        """)
    elif intent == "pronostico_ubicacion":
        sql = text("""
            SELECT d.ubigeo, d.departamento, d.provincia, d.distrito,
                   p.fecha_objetivo, p.ano_objetivo, p.semana_objetivo,
                   p.horizonte_semanas, p.prediccion_final, p.modelo_seleccionado
            FROM dbo.fact_pronosticos AS p
            INNER JOIN dbo.dim_distrito AS d ON d.ubigeo = p.ubigeo
            WHERE p.fecha_generacion = :fecha
              AND p.horizonte_semanas = :horizonte
              AND (:ubicacion = '' OR d.distrito LIKE :patron OR d.provincia LIKE :patron
                   OR d.departamento LIKE :patron OR d.ubigeo = :ubicacion)
            ORDER BY p.prediccion_final DESC
            OFFSET 0 ROWS FETCH NEXT :top_n ROWS ONLY
        """)
    elif intent == "tendencia_historica":
        sql = text("""
            SELECT f.ano, SUM(f.casos_reportados) AS casos_totales
            FROM dbo.fact_semanal_dengue AS f
            INNER JOIN dbo.dim_distrito AS d ON d.ubigeo = f.ubigeo
            WHERE f.registro_minsa = 1
              AND (:ubicacion = '' OR d.departamento LIKE :patron OR d.provincia LIKE :patron)
            GROUP BY f.ano ORDER BY f.ano
        """)
    elif intent == "comparar_horizontes":
        sql = text("""
            SELECT horizonte_semanas,
                   SUM(prediccion_final) AS casos_pronosticados,
                   AVG(prediccion_final) AS promedio_distrital,
                   COUNT(DISTINCT ubigeo) AS distritos
            FROM dbo.fact_pronosticos
            WHERE fecha_generacion = :fecha
            GROUP BY horizonte_semanas ORDER BY horizonte_semanas
        """)
    else:
        sql = text("""
            SELECT horizonte_semanas,
                   SUM(prediccion_final) AS casos_pronosticados,
                   AVG(prediccion_final) AS promedio_distrital,
                   COUNT(DISTINCT ubigeo) AS distritos
            FROM dbo.fact_pronosticos
            WHERE fecha_generacion = :fecha AND horizonte_semanas = :horizonte
            GROUP BY horizonte_semanas
        """)

    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [dict(row) for row in rows]


def _clean_rows(rows):
    clean_rows = []
    for row in rows:
        clean = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, (date, datetime)):
                value = value.isoformat()
            clean[key] = value
        clean_rows.append(clean)
    return clean_rows


def build_response_text(plan, rows):
    if not rows:
        return "No se encontraron resultados con esos criterios. Prueba con otro distrito, provincia o departamento."
    intent = plan["intent"]
    if intent == "ranking_distritos":
        lines = ["Distritos con mayor pronóstico:"]
        for i, row in enumerate(rows, 1):
            lines.append(f"{i}. {row['distrito']} ({row['departamento']}): {row['casos_pronosticados']:,.1f} casos estimados.")
        return "\n".join(lines)
    if intent == "pronostico_ubicacion":
        lines = ["Pronósticos encontrados:"]
        for row in rows:
            lines.append(
                f"{row['distrito']}, {row['departamento']}: "
                f"{row['prediccion_final']:,.1f} casos estimados para la semana "
                f"{row['semana_objetivo']} (horizonte +{row['horizonte_semanas']})."
            )
        return "\n".join(lines)
    if intent == "tendencia_historica":
        return "\n".join(["Evolución de casos con registro MINSA:"] + [f"{r['ano']}: {r['casos_totales']:,.0f} casos" for r in rows])
    if intent == "comparar_horizontes":
        return "\n".join(["Comparación de horizontes:"] + [f"Semana +{r['horizonte_semanas']}: {r['casos_pronosticados']:,.1f} casos estimados." for r in rows])
    row = rows[0]
    return (
        f"Para el horizonte de {row['horizonte_semanas']} semanas se estiman "
        f"{row['casos_pronosticados']:,.1f} casos en {row['distritos']} distritos."
    )


def visualization_config(intent: str, rows: list[dict]) -> dict:
    if intent == "ranking_distritos":
        return {"tipo": "bar", "eje_x": "distrito", "serie": "casos_pronosticados", "titulo": "Distritos con mayor pronóstico"}
    if intent == "tendencia_historica":
        return {"tipo": "line", "eje_x": "ano", "serie": "casos_totales", "titulo": "Evolución histórica de casos"}
    if intent == "comparar_horizontes":
        return {"tipo": "bar", "eje_x": "horizonte_semanas", "serie": "casos_pronosticados", "titulo": "Comparación de horizontes"}
    if intent == "pronostico_ubicacion":
        return {"tipo": "bar", "eje_x": "distrito", "serie": "prediccion_final", "titulo": "Pronóstico por ubicación"}
    return {"tipo": "kpi", "serie": "casos_pronosticados", "titulo": "Panorama nacional"}


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"estado": "ok", "base_datos": "SQL Server", "consultor": "Groq" if client else "clasificador_local"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No se pudo conectar con SQL Server: {exc}")


@app.post("/consultar")
def consultar(request: Consulta):
    question = request.pregunta.strip()
    try:
        forecast_date = latest_forecast_date()
        cache_key = (question.casefold(), str(forecast_date))
        if cache_key in CACHE:
            return CACHE[cache_key]

        plan = classify_question(question)
        rows = _clean_rows(execute_query(plan, forecast_date))
        response = {
            "respuesta": build_response_text(plan, rows),
            "intencion": plan["intent"],
            "horizonte": plan["horizonte"],
            "fecha_generacion": str(forecast_date),
            "datos": rows,
            "visualizacion": visualization_config(plan["intent"], rows),
            "fuente_numerica": "SQL Server"
        }
        if len(CACHE) >= 250:
            CACHE.pop(next(iter(CACHE)))
        CACHE[cache_key] = response
        return response
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Error del consultor: {exc}")
        raise HTTPException(status_code=500, detail="No se pudo procesar la consulta. Revisa la conexión y las tablas SQL Server.")
