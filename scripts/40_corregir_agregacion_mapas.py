import json
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

PAGES = ROOT / "powerbi" / "Dengue_Analytics" / "Dengue_Analytics.Report" / "definition" / "pages"

TARGETS = {
    "c972c794043f4f58a8a4": "vw_historico_dengue.Casos Reportados",
    "d731ee5c3a5a4167b821": "vw_ranking_distritos_pronostico.Pronostico Distrital"
}

def column_projection(entity, prop, active=False):
    result = {
        "field": {
            "Column": {
                "Expression": {
                    "SourceRef": {"Entity": entity}
                },
                "Property": prop
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop
    }

    if active:
        result["active"] = True

    return result


def average_projection(prop):
    entity = "dim_distrito"

    return {
        "field": {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {
                            "SourceRef": {"Entity": entity}
                        },
                        "Property": prop
                    }
                },
                "Function": 1
            }
        },
        "queryRef": f"Avg({entity}.{prop})",
        "nativeQueryRef": f"Average of {prop}"
    }


print("\n========================================")
print("REPARACION DEFINITIVA DE AZURE MAPS")
print("========================================")

prepared = []

for visual_id, expected_size in TARGETS.items():

    matches = [
        p for p in PAGES.rglob("visual.json")
        if p.parent.name == visual_id
    ]

    if len(matches) != 1:
        raise RuntimeError(f"Visual no encontrado: {visual_id}")

    path = matches[0]
    data = json.loads(path.read_text(encoding="utf-8-sig"))

    visual = data["visual"]

    if visual.get("visualType") != "azureMap":
        raise RuntimeError("Tipo de visual incorrecto")

    qs = visual["query"]["queryState"]

    size = qs.get("Size", {}).get("projections", [])

    if not size or size[0].get("queryRef") != expected_size:
        raise RuntimeError(f"Medida Size inesperada: {visual_id}")

    for role, prop in [("X", "longitud"), ("Y", "latitud")]:

        projections = qs.get(role, {}).get("projections", [])

        if not projections:
            raise RuntimeError(f"Falta el rol {role}")

        field = projections[0].get("field", {})

        if "Column" not in field and "Aggregation" not in field:
            raise RuntimeError(f"Campo inesperado en {role}")

    prepared.append((visual_id, path, data, expected_size))

    print("VALIDADO:", visual_id)


# Respaldos
backup = (
    ROOT / "backups" / "powerbi" /
    ("mapas_promedio_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
)

backup.mkdir(parents=True, exist_ok=True)

for visual_id, path, data, size in prepared:
    shutil.copy2(path, backup / f"{visual_id}_original.json")

print("\nRESPALDOS:", backup)


# Modificaciones
for visual_id, path, data, expected_size in prepared:

    qs = data["visual"]["query"]["queryState"]

    # Ubicacion obligatoria: UBIGEO
    qs["Category"] = {
        "projections": [
            column_projection("dim_distrito", "ubigeo", True)
        ]
    }

    # Promedio de coordenadas
    qs["X"] = {
        "projections": [average_projection("longitud")]
    }

    qs["Y"] = {
        "projections": [average_projection("latitud")]
    }

    # Leyenda por departamento
    qs["Series"] = {
        "projections": [
            column_projection("dim_distrito", "departamento", True)
        ]
    }

    # Confirmar que Size no cambio
    assert qs["Size"]["projections"][0]["queryRef"] == expected_size

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print("ACTUALIZADO:", visual_id)


# Verificacion
print("\n===== VERIFICACION FINAL =====")

for visual_id, path, _, expected_size in prepared:

    data = json.loads(path.read_text(encoding="utf-8"))
    qs = data["visual"]["query"]["queryState"]

    assert qs["Category"]["projections"][0]["queryRef"] == "dim_distrito.ubigeo"

    assert qs["X"]["projections"][0]["queryRef"] == "Avg(dim_distrito.longitud)"
    assert qs["X"]["projections"][0]["field"]["Aggregation"]["Function"] == 1

    assert qs["Y"]["projections"][0]["queryRef"] == "Avg(dim_distrito.latitud)"
    assert qs["Y"]["projections"][0]["field"]["Aggregation"]["Function"] == 1

    assert qs["Size"]["projections"][0]["queryRef"] == expected_size

    print("OK:", visual_id)
    print("  Category: UBIGEO")
    print("  X: Promedio de longitud")
    print("  Y: Promedio de latitud")
    print("  Size: Medida original")

print("\n========================================")
print("DOS MAPAS CONFIGURADOS CON PROMEDIO")
print("========================================")
