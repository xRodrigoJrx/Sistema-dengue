import json
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

PROJECT = ROOT / "powerbi" / "Dengue_Analytics"
PAGES = PROJECT / "Dengue_Analytics.Report" / "definition" / "pages"

BACKUP = (
    ROOT / "backups" / "powerbi" /
    ("mapas_geo_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
)

TARGETS = {
    "c972c794043f4f58a8a4": {
        "size": "vw_historico_dengue.Casos Reportados",
        "title": "Distribución histórica por distrito"
    },
    "d731ee5c3a5a4167b821": {
        "size": "vw_ranking_distritos_pronostico.Pronostico Distrital",
        "title": "Pronóstico acumulado por distrito"
    }
}


def projection(entity, prop):
    return {
        "field": {
            "Column": {
                "Expression": {
                    "SourceRef": {"Entity": entity}
                },
                "Property": prop
            }
        },
        "queryRef": f"{entity}.{prop}",
        "nativeQueryRef": prop,
        "active": True
    }


def update_map(data, config):

    visual = data["visual"]

    if visual["visualType"] != "azureMap":
        raise ValueError("El visual no es Azure Maps")

    query_state = visual["query"]["queryState"]

    # Verificar que la medida original exista
    size = query_state.get("Size", {}).get("projections", [])

    if not size:
        raise ValueError("No se encontro la medida Size")

    if size[0].get("queryRef") != config["size"]:
        raise ValueError(
            "La medida original no coincide: " +
            str(size[0].get("queryRef"))
        )

    # Ubicación única por distrito
    query_state["Category"] = {
        "projections": [
            projection("dim_distrito", "ubigeo")
        ]
    }

    # Y = Latitud
    query_state["Y"] = {
        "projections": [
            projection("dim_distrito", "latitud")
        ]
    }

    # X = Longitud
    query_state["X"] = {
        "projections": [
            projection("dim_distrito", "longitud")
        ]
    }

    # Series = Departamento (colores)
    query_state["Series"] = {
        "projections": [
            projection("dim_distrito", "departamento")
        ]
    }

    # Conservar la medida Size original
    # Centrar el mapa en el Peru
    objects = visual.setdefault("objects", {})

    controls = objects.setdefault(
        "mapControls",
        [{"properties": {}}]
    )

    if not controls:
        controls.append({"properties": {}})

    properties = controls[0].setdefault("properties", {})

    properties["zoom"] = {
        "expr": {"Literal": {"Value": "4.2D"}}
    }

    properties["centerLatitude"] = {
        "expr": {"Literal": {"Value": "-9.48D"}}
    }

    properties["centerLongitude"] = {
        "expr": {"Literal": {"Value": "-75.04D"}}
    }

    # Actualizar titulo para reflejar nivel distrital
    titles = (
        visual.get("visualContainerObjects", {})
        .get("title", [])
    )

    if titles:
        titles[0]["properties"]["text"]["expr"]["Literal"]["Value"] = (
            "'" + config["title"] + "'"
        )


# =========================================
# VALIDACION PREVIA
# =========================================

print("\n====================================")
print("CORRECCION GEOGRAFICA POWER BI")
print("====================================")

if not PAGES.exists():
    raise FileNotFoundError(PAGES)

found = []

for visual_id, config in TARGETS.items():

    matches = [
        p for p in PAGES.rglob("visual.json")
        if p.parent.name == visual_id
    ]

    if len(matches) != 1:
        raise RuntimeError(
            f"Se esperaba un visual {visual_id}; "
            f"encontrados: {len(matches)}"
        )

    path = matches[0]

    data = json.loads(path.read_text(encoding="utf-8-sig"))

    # Validar antes de modificar
    visual = data["visual"]

    if visual["visualType"] != "azureMap":
        raise ValueError(f"Tipo incorrecto: {visual_id}")

    size = visual["query"]["queryState"].get(
        "Size", {}
    ).get("projections", [])

    if not size or size[0].get("queryRef") != config["size"]:
        raise ValueError(f"Medida inesperada: {visual_id}")

    found.append((visual_id, path, config, data))

    print("VALIDADO:", visual_id)


# =========================================
# RESPALDOS
# =========================================

BACKUP.mkdir(parents=True, exist_ok=True)

for visual_id, path, config, data in found:

    shutil.copy2(
        path,
        BACKUP / f"{visual_id}_original.json"
    )

print("\nRESPALDOS CREADOS:", BACKUP)


# =========================================
# ACTUALIZACION
# =========================================

for visual_id, path, config, data in found:

    update_map(data, config)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print("ACTUALIZADO:", visual_id)


# =========================================
# VERIFICACION FINAL
# =========================================

print("\n===== VERIFICACION FINAL =====")

for visual_id, path, config, _ in found:

    data = json.loads(path.read_text(encoding="utf-8"))

    qs = data["visual"]["query"]["queryState"]

    expected = {
        "Category": "dim_distrito.ubigeo",
        "Y": "dim_distrito.latitud",
        "X": "dim_distrito.longitud",
        "Series": "dim_distrito.departamento"
    }

    for role, query_ref in expected.items():

        actual = qs[role]["projections"][0]["queryRef"]

        if actual != query_ref:
            raise RuntimeError(
                f"Error en {visual_id}: {role}"
            )

    if qs["Size"]["projections"][0]["queryRef"] != config["size"]:
        raise RuntimeError("Se modifico accidentalmente Size")

    print("OK:", visual_id)
    print("  Latitud: dim_distrito.latitud")
    print("  Longitud: dim_distrito.longitud")
    print("  Ubicacion: UBIGEO")
    print("  Medida conservada:", config["size"])

print("\n====================================")
print("DOS MAPAS ACTUALIZADOS CORRECTAMENTE")
print("RESPALDOS DISPONIBLES")
print("====================================")
