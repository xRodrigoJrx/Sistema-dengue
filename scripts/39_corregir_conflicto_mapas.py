import json
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(r"C:\Users\xxter\Documents\Data_Dengue\Sistema")

PAGES = (
    ROOT / "powerbi" / "Dengue_Analytics" /
    "Dengue_Analytics.Report" / "definition" / "pages"
)

BACKUP = (
    ROOT / "backups" / "powerbi" /
    ("mapas_sin_location_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
)

TARGETS = {
    "c972c794043f4f58a8a4":
        "vw_historico_dengue.Casos Reportados",

    "d731ee5c3a5a4167b821":
        "vw_ranking_distritos_pronostico.Pronostico Distrital"
}

prepared = []

print("\n===== VALIDANDO MAPAS =====")

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

    if visual["visualType"] != "azureMap":
        raise RuntimeError("El visual no es Azure Maps")

    qs = visual["query"]["queryState"]

    expected = {
        "Y": "dim_distrito.latitud",
        "X": "dim_distrito.longitud"
    }

    for role, reference in expected.items():

        projections = qs.get(role, {}).get("projections", [])

        if len(projections) != 1:
            raise RuntimeError(f"Proyeccion incorrecta: {role}")

        if projections[0].get("queryRef") != reference:
            raise RuntimeError(f"Campo incorrecto: {role}")

    size = qs.get("Size", {}).get("projections", [])

    if not size or size[0].get("queryRef") != expected_size:
        raise RuntimeError("La medida Size no coincide")

    prepared.append((visual_id, path, data))

    print("VALIDADO:", visual_id)


print("\n===== CREANDO RESPALDOS =====")

BACKUP.mkdir(parents=True, exist_ok=True)

for visual_id, path, data in prepared:

    shutil.copy2(
        path,
        BACKUP / f"{visual_id}_antes_correccion.json"
    )

print("RESPALDOS:", BACKUP)


print("\n===== ELIMINANDO CONFLICTO =====")

for visual_id, path, data in prepared:

    qs = data["visual"]["query"]["queryState"]

    # Category equivale al campo Ubicacion
    qs.pop("Category", None)

    # Eliminar tambien una eventual clave Location
    qs.pop("Location", None)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )

    print("CORREGIDO:", visual_id)


print("\n===== VERIFICACION FINAL =====")

for visual_id, path, _ in prepared:

    data = json.loads(path.read_text(encoding="utf-8"))

    qs = data["visual"]["query"]["queryState"]

    assert "Category" not in qs
    assert "Location" not in qs

    assert (
        qs["Y"]["projections"][0]["queryRef"]
        == "dim_distrito.latitud"
    )

    assert (
        qs["X"]["projections"][0]["queryRef"]
        == "dim_distrito.longitud"
    )

    assert "Size" in qs

    print("OK:", visual_id)
    print("  Ubicacion: eliminada")
    print("  Latitud y longitud: conservadas")
    print("  Medida de casos: conservada")

print("\n====================================")
print("CONFLICTO LOCATION/LATITUDE/LONGITUDE CORREGIDO")
print("DOS MAPAS ACTUALIZADOS")
print("====================================")
