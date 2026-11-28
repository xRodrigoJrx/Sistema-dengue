<#
.SYNOPSIS
Aplica un diseño de vigilancia del dengue a un informe de Power BI en formato PBIR mejorado.
.EXAMPLE
.\Aplicar-Diseno-Dengue.ps1 -VistaPrevia
.EXAMPLE
.\Aplicar-Diseno-Dengue.ps1 -Raiz "C:\Users\xxter\Documents\Data_Dengue"
#>
[CmdletBinding()]
param(
    [string]$Raiz = (Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Data_Dengue"),
    [string]$ProyectoPbip,
    [string]$Entorno,
    [ValidateRange(1, 100)]
    [int]$Paginas,
    [switch]$VistaPrevia
)

$ErrorActionPreference = "Stop"
$Raiz = (Resolve-Path -LiteralPath $Raiz).ProviderPath
if ($ProyectoPbip) {
    $ProyectoPbip = (Resolve-Path -LiteralPath $ProyectoPbip).ProviderPath
    if ([IO.Path]::GetExtension($ProyectoPbip) -ne ".pbip") {
        throw "ProyectoPbip debe apuntar a un archivo .pbip."
    }
}

if ($Entorno) {
    $candidatos = @((Resolve-Path -LiteralPath $Entorno).ProviderPath)
} elseif ($env:VIRTUAL_ENV) {
    $candidatos = @($env:VIRTUAL_ENV)
} else {
    $candidatos = @(
        (Join-Path $Raiz "Sistema/.venv"),
        (Join-Path $Raiz "Sistema-dengue/.venv"),
        (Join-Path $Raiz ".venv")
    )
}

$python = $null
foreach ($directorio in $candidatos) {
    if (Test-Path -LiteralPath (Join-Path $directorio "pyvenv.cfg") -PathType Leaf) {
        foreach ($rutaPython in @("Scripts/python.exe", "bin/python")) {
            $candidato = Join-Path $directorio $rutaPython
            if (Test-Path -LiteralPath $candidato -PathType Leaf) {
                $python = $candidato
                break
            }
        }
    }
    if ($python) { break }
}
if (-not $python) {
    throw "No se encontró un entorno virtual ejecutable. Indica la carpeta .venv con -Entorno."
}

if (-not $VistaPrevia -and (Get-Process -Name "PBIDesktop" -ErrorAction SilentlyContinue)) {
    throw "Cierra Power BI Desktop antes de aplicar el diseño."
}

$motor = @'
"""Update the presentation of an existing PBIR report using only the standard library."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import unicodedata
from uuid import uuid4

INK = "#123653"
NAVY = "#103F56"
PAGE = "#EDF4F5"
WHITE = "#FFFFFF"
BORDER = "#CBDDE3"
SUBTLE = "#456174"
TEAL = "#007E83"
LOW = "#82CBC3"
HIGH = "#A73A16"
DIM = "dim_distrito"
HIST = "vw_historico_dengue"
FORECAST = "vw_ranking_distritos_pronostico"
NATIONAL = "vw_resumen_nacional_pronostico"
METRICS = "fact_metricas_modelo"
MEASURES = {HIST: "Casos Reportados", FORECAST: "Pronostico Distrital", NATIONAL: "Casos Pronosticados"}
BARS = {"barChart", "clusteredBarChart", "columnChart", "clusteredColumnChart"}
MARGIN = 28
TOP = 116
SLICER_WIDTH = 306
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json"
PAGE_TITLES = {
    "panorama nacional": "Panorama nacional",
    "evolucion historica": "Evolución histórica",
    "pronosticos": "Pronósticos",
    "evaluacion modelos": "Evaluación de modelos",
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def title_for(name):
    label = re.sub(r"^\d+[_. -]+", "", name.replace("_", " ")).strip()
    normalized = "".join(ch for ch in unicodedata.normalize("NFD", label.lower()) if not unicodedata.combining(ch))
    return PAGE_TITLES.get(normalized, label or name)


def literal(value):
    if isinstance(value, bool):
        value = str(value).lower()
    elif isinstance(value, int):
        value = f"{value}D"
    else:
        value = "'" + value.replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": value}}}


def color(hex_color):
    return {"solid": {"color": literal(hex_color)}}


def properties(container, group, **values):
    items = container.setdefault(group, [])
    default = next((item for item in items if "selector" not in item), None)
    if default is None:
        default = {"properties": {}}
        items.insert(0, default)
    default["properties"].update(values)
    return default["properties"]


def panel(container, *, background=WHITE, border=BORDER, padding=12):
    properties(container, "background", show=literal(True), color=color(background), transparency=literal(0))
    properties(container, "border", show=literal(True), color=color(border), radius=literal(12), width=literal(1))
    properties(container, "padding", **dict.fromkeys(("left", "right", "top", "bottom"), literal(padding)))


def role_items(visual, role=None):
    query_state = visual.get("query", {}).get("queryState", {})
    roles = [query_state.get(role, {})] if role else query_state.values()
    return [item for config in roles for item in config.get("projections", [])]


def source(item, kind):
    field = item.get("field", {}).get(kind, {})
    entity = field.get("Expression", {}).get("SourceRef", {}).get("Entity")
    return entity, field.get("Property")


def uses(visual, table):
    return any(
        source(item, kind)[0] == table or item.get("queryRef", "").startswith((table + ".", "Sum(" + table + ".", "Avg(" + table + "."))
        for item in role_items(visual) for kind in ("Measure", "Column")
    )


def series(visual):
    return any(role_items(visual, name) for name in ("Series", "Legend"))


def query_field(kind, table, field):
    item = {
        "field": {kind: {"Expression": {"SourceRef": {"Entity": table}}, "Property": field}},
        "queryRef": f"{table}.{field}",
        "nativeQueryRef": field,
    }
    if kind == "Column":
        item["active"] = True
    return {"projections": [item]}


def gradient(visual):
    if visual.get("visualType") not in BARS or series(visual):
        return False
    items = role_items(visual, "Y")
    if len(items) != 1:
        return False
    table, measure = source(items[0], "Measure")
    if not table or MEASURES.get(table) != measure:
        return False
    objects = visual.setdefault("objects", {})
    # Specific series or category colors would take precedence over the scale.
    existing = objects.get("dataPoint", [])
    if any("fill" in item.get("properties", {}) for item in existing if "selector" in item):
        return False
    scale = {
        "FillRule": {
            "Input": deepcopy(items[0]["field"]),
            "FillRule": {
                "linearGradient2": {
                    "min": {"color": literal(LOW)["expr"]},
                    "max": {"color": literal(HIGH)["expr"]},
                    "nullColoringStrategy": {"strategy": literal("asZero")["expr"]},
                }
            },
        }
    }
    objects.setdefault("dataPoint", []).append({
        "properties": {"fill": {"solid": {"color": {"expr": scale}}}},
        "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]},
    })
    return True


def new_name(page_name, purpose):
    return hashlib.sha256(f"sistema-dengue:{page_name}:{purpose}".encode()).hexdigest()[:20]


def new_visual(page_name, purpose, visual_type, x, y, width, height, order):
    return {
        "$schema": SCHEMA,
        "name": new_name(page_name, purpose),
        "position": {"x": x, "y": y, "width": width, "height": height, "z": order, "tabOrder": order},
        "visual": {"visualType": visual_type, "drillFilterOtherVisuals": True},
    }


def text_run(value, size, hex_color, bold=False):
    style = {"fontFamily": "Segoe UI", "fontSize": f"{size}pt", "color": hex_color}
    if bold:
        style["fontWeight"] = "bold"
    return {"value": value, "textStyle": style}


def heading(page_name, label, subtitle, width, order):
    record = new_visual(page_name, "encabezado", "textbox", MARGIN, 20, width, 80, order)
    v = record["visual"]
    paragraphs = [
        {"textRuns": [text_run(label, 24, WHITE, True)]},
        {"textRuns": [text_run(subtitle, 11, "#D0EDF0")]},
    ]
    properties(v.setdefault("objects", {}), "general", paragraphs=paragraphs)
    container = v.setdefault("visualContainerObjects", {})
    panel(container, background=NAVY, border=NAVY)
    properties(container, "visualHeader", show=literal(False))
    return record


def page_navigator(page_name, width, order):
    record = new_visual(page_name, "navegacion", "pageNavigator", MARGIN, 110, width, 46, order)
    visual = record["visual"]
    visual["objects"] = {
        "shape": [{"properties": {"tileShape": literal("tabRoundTopCorners")}, "selector": {"id": "default"}}],
        "fill": [
            {"properties": {"fillColor": color(WHITE)}, "selector": {"id": "default"}},
            {"properties": {"fillColor": color(TEAL)}, "selector": {"id": "selected"}},
        ],
        "outline": [{"properties": {"show": literal(False)}}],
        "text": [
            {"properties": {"fontColor": color(INK), "fontSize": literal(12)}, "selector": {"id": "default"}},
            {"properties": {"fontColor": color(WHITE), "fontSize": literal(12), "bold": literal(True)}, "selector": {"id": "selected"}},
        ],
    }
    properties(visual.setdefault("visualContainerObjects", {}), "visualHeader", show=literal(False))
    return record


def department_slicer(page_name, x, order):
    record = new_visual(page_name, "departamento", "slicer", x, 20, SLICER_WIDTH, 80, order)
    v = record["visual"]
    v["query"] = {"queryState": {"Values": query_field("Column", DIM, "departamento")}}
    objects = v.setdefault("objects", {})
    properties(objects, "header", text=literal("Departamento del Perú"), show=literal(True), fontColor=color(INK))
    properties(objects, "data", mode=literal("Dropdown"))
    panel(v.setdefault("visualContainerObjects", {}), border=TEAL)
    return record


def set_title(visual, title):
    props = properties(visual.setdefault("visualContainerObjects", {}), "title", text=literal(title), show=literal(True))
    props.update(fontColor=color(INK), fontSize=literal(14), bold=literal(True))


def department_chart(page_name, table, width, y, order):
    chart = new_visual(page_name, "comparacion-departamentos", "clusteredBarChart", MARGIN, y, width, 380, order)
    v = chart["visual"]
    v["query"] = {"queryState": {
        "Category": query_field("Column", DIM, "departamento"),
        "Y": query_field("Measure", table, MEASURES[table]),
    }}
    label = "Casos reportados por departamento" if table == HIST else "Casos pronosticados por departamento"
    set_title(v, label)
    panel(v["visualContainerObjects"])
    return chart


def season_chart(page_name, width, y, order):
    chart = new_visual(page_name, "periodo-climatico", "lineChart", MARGIN, y, width, 300, order)
    v = chart["visual"]
    v["query"] = {"queryState": {
        "Category": query_field("Column", "DimFecha", "Date"),
        "Y": query_field("Measure", HIST, "Precipitacion Media"),
    }}
    set_title(v, "Precipitación media a lo largo del tiempo")
    panel(v["visualContainerObjects"])
    return chart


def restyle_visual(record):
    v = record.get("visual")
    if v is None or v.get("visualType") in {"textbox", "shape", "image", "actionButton", "pageNavigator", "bookmarkNavigator"}:
        return False
    container = v.setdefault("visualContainerObjects", {})
    kind = v.get("visualType")
    panel(container, border=TEAL if kind in {"card", "cardVisual", "kpi"} else BORDER)
    # Preserve existing dashboard captions and whether the author chose to show them.
    if container.get("title"):
        properties(container, "title", fontColor=color(INK), fontSize=literal(14), bold=literal(True))
    if container.get("subTitle"):
        properties(container, "subTitle", fontColor=color(SUBTLE))
    if kind == "cardVisual":
        v.setdefault("objects", {}).setdefault("accentBar", [{
            "properties": {"show": literal(True), "color": color(TEAL), "width": literal(4), "position": literal("Left")},
            "selector": {"id": "default"},
        }])
    return gradient(v)


def find_binding(tables, table, kind, field):
    return bool(re.search(rf"(?m)^\s*{kind}\s+(?:'{re.escape(field)}'|{re.escape(field)})(?=\s|=|$)", tables.get(table, "")))


def field_links(model):
    tables = {
        p.stem: p.read_text(encoding="utf-8-sig")
        for p in (model / "definition" / "tables").glob("*.tmdl")
    }
    relations = model / "definition" / "relationships.tmdl"
    text = relations.read_text(encoding="utf-8-sig") if relations.is_file() else ""
    geographic = set()
    if find_binding(tables, DIM, "column", "departamento"):
        geographic.add(DIM)
        for block in re.split(r"(?m)^relationship\s+", text):
            if re.search(r"(?m)^\s*isActive:\s*false\s*$", block):
                continue
            # TMDL default direction propagates from the dimension on the to side.
            many = re.search(r"(?m)^\s*fromColumn:\s*([\w]+)\.ubigeo\s*$", block)
            one = re.search(r"(?m)^\s*toColumn:\s*dim_distrito\.ubigeo\s*$", block)
            if many and one and many[1] in tables:
                geographic.add(many[1])
    return tables, geographic


def report_of(pbip):
    reports = [entry["report"]["path"] for entry in read(pbip).get("artifacts", []) if "report" in entry]
    if len(reports) != 1:
        raise ValueError(f"Se esperaba un informe en {pbip}.")
    report = (pbip.parent / reports[0]).resolve()
    if not report.is_relative_to(pbip.parent.resolve()):
        raise ValueError(f"La carpeta del informe debe estar dentro del proyecto {pbip.parent}.")
    index = report / "definition" / "pages" / "pages.json"
    if not index.is_file():
        raise ValueError(f"{pbip} requiere el formato PBIR mejorado con definition/pages/pages.json.")
    return report, read(index)["pageOrder"]


def find_pbip(root, selected, count):
    if selected:
        return Path(selected).resolve()
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_backup")) and d.casefold() not in {"backups", "data", "node_modules", "reports", "models"}]
        found.extend(Path(folder, f) for f in files if f.lower().endswith(".pbip"))
    if not found:
        raise ValueError("No se encontró un .pbip. Abre tu .pbix en Power BI Desktop y guárdalo como proyecto .pbip en formato PBIR mejorado.")
    matches = []
    for pbip in found:
        try:
            _, order = report_of(pbip)
            if count is None or len(order) == count:
                matches.append(pbip)
        except (ValueError, KeyError, OSError):
            continue
    if len(matches) == 1:
        return matches[0]
    if len(found) == 1:
        return found[0]
    candidates = "\n".join(f"  {p}" for p in matches or found)
    raise ValueError(f"Especifica el informe con -ProyectoPbip. Proyectos encontrados:\n{candidates}")


def has_department_chart(visual):
    return (
        visual.get("visualType") in BARS
        and any(source(item, "Column")[1] == "departamento" for item in role_items(visual, "Category"))
        and any(MEASURES.get(table) == field and table is not None for table, field in (source(item, "Measure") for item in role_items(visual, "Y")))
    )


def prepare_page(folder, page, tables, geographic):
    page_path = folder / "page.json"
    name = page["name"]
    visuals = {p: read(p) for p in sorted(folder.glob("visuals/*/visual.json"))}
    generated_header = folder / "visuals" / new_name(name, "encabezado") / "visual.json"
    label = title_for(page["displayName"])
    if generated_header in visuals:
        return {}, f"{label} · diseño ya aplicado"
    if page.get("type") == "Tooltip":
        # Preserve tooltip dimensions and position for the report's hover behavior.
        if "background" not in page.get("objects", {}):
            properties(page.setdefault("objects", {}), "background", color=color(PAGE), transparency=literal(0))
        return {page_path: page}, f"{label} · formato de página tooltip"

    visible = [r["visual"] for r in visuals.values() if "visual" in r and not r.get("isHidden")]
    regional = {table for table in geographic if any(uses(v, table) for v in visible)}
    already_has_slicer = any(v.get("visualType") == "slicer" and any(source(i, "Column") in {(table, "departamento") for table in regional | {DIM}} for i in role_items(v)) for v in visible)
    add_slicer = bool(regional) and not already_has_slicer
    add_nav = not any(v.get("visualType") == "pageNavigator" for v in visible)
    content_top = TOP + (54 if add_nav else 0)
    chart_table = next((table for table in (FORECAST, HIST) if table in regional and find_binding(tables, table, "measure", MEASURES[table])), None)
    add_rank = bool(chart_table) and not any(has_department_chart(v) for v in visible)
    add_rain = (
        HIST in regional and not add_rank and any(
            source(item, "Measure") == (HIST, "Temperatura Media")
            for v in visible if v.get("visualType") == "lineChart" for item in role_items(v, "Y")
        )
        and find_binding(tables, HIST, "measure", "Precipitacion Media")
        and find_binding(tables, "DimFecha", "column", "Date")
        and not any(source(item, "Measure") == (HIST, "Precipitacion Media") for v in visible if v.get("visualType") == "lineChart" for item in role_items(v, "Y"))
    )

    top_level = [r["position"] for r in visuals.values() if not r.get("parentGroupName")]
    # Expand around existing free-form layouts without moving children within a group.
    left = min(0, *(position["x"] for position in top_level)) if top_level else 0
    top = min(0, *(position["y"] for position in top_level)) if top_level else 0
    content_width = round(max([page["width"], 720, *(p["x"] + p["width"] for p in top_level)]) - left + 0.5)
    content_height = round(max([page["height"], *(p["y"] + p["height"] for p in top_level)]) - top + 0.5)
    page["width"] = content_width + 2 * MARGIN
    page["height"] = content_top + content_height + MARGIN
    objects = page.setdefault("objects", {})
    background = properties(objects, "background", color=color(PAGE), transparency=literal(0))
    background.pop("image", None)

    scales = []
    for record in visuals.values():
        if not record.get("parentGroupName"):
            record["position"]["x"] += MARGIN - left
            record["position"]["y"] += content_top - top
        if restyle_visual(record) and not record.get("isHidden"):
            scales.append(record["name"])

    next_order = 1000 + max([0, *(p.get("z", 0) for p in top_level), *(p.get("tabOrder", 0) for p in top_level)])
    new_records = []
    if add_rank or add_rain:
        new_y = content_top + content_height + 16
        if add_rank:
            chart = department_chart(name, chart_table, content_width, new_y, next_order)
        else:
            chart = season_chart(name, content_width, new_y, next_order)
        if gradient(chart["visual"]):
            scales.append(chart["name"])
        page["height"] = new_y + chart["position"]["height"] + MARGIN
        new_records.append(chart)
    subtitle = ["Vigilancia del dengue · Perú"]
    if scales:
        subtitle.append("Casos en barras: turquesa (menor) a terracota (mayor)")
    if regional and any(uses(v, NATIONAL) for v in visible):
        subtitle.append("Los indicadores nacionales mantienen su alcance")
    elif any(uses(v, METRICS) for v in visible) and not regional:
        subtitle.append("Métricas globales por modelo y horizonte")
    new_records.append(heading(name, label, "   |   ".join(subtitle),
                               content_width - (SLICER_WIDTH + 16 if add_slicer else 0), next_order + 1000))
    if add_slicer:
        new_records.append(department_slicer(name, MARGIN + content_width - SLICER_WIDTH, next_order + 2000))
    if add_nav:
        new_records.append(page_navigator(name, content_width, next_order + 3000))
    for record in new_records:
        path = folder / "visuals" / record["name"] / "visual.json"
        if path.exists():
            raise ValueError(f"Identificador de visual ya ocupado en {path}.")
        visuals[path] = record
    filter_status = "agregado" if add_slicer else "existente" if already_has_slicer else "sin vínculo geográfico aplicable"
    summary = f"{label} · departamento: {filter_status} · barras con escala: {len(scales)} · gráfico nuevo: {'sí' if add_rank or add_rain else 'no'}"
    return {page_path: page, **visuals}, summary


def fingerprint(folder):
    return {
        p.relative_to(folder): hashlib.sha256(p.read_bytes()).digest()
        for p in folder.rglob("*") if p.is_file()
    }


def apply(definition, updates, original):
    parent = definition.parent
    suffix = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
    backup = parent.parent / f"_respaldo_diseno_dengue_{suffix}"
    with TemporaryDirectory(prefix=".diseno-dengue-", dir=parent.parent) as temporary:
        staged = Path(temporary) / "definition"
        shutil.copytree(definition, staged)
        for path, value in updates.items():
            write(staged / path.relative_to(definition), value)
        # Detect changes made by another editor before replacing the definition directory.
        if fingerprint(definition) != original:
            raise ValueError("La definición cambió durante la preparación. Cierra Power BI Desktop y vuelve a ejecutar.")
        definition.rename(backup)
        try:
            staged.rename(definition)
        except OSError:
            backup.rename(definition)
            raise
    return backup


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pbip")
    parser.add_argument("--pages", type=int)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if not args.root.is_dir():
        raise ValueError(f"No se encontró la carpeta {args.root}.")
    pbip = find_pbip(args.root.resolve(), args.pbip, args.pages)
    report, order = report_of(pbip)
    if not isinstance(order, list) or not order or any(
        not isinstance(page_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", page_id) for page_id in order
    ):
        raise ValueError(f"{pbip} contiene una lista de páginas vacía o inválida.")
    if len(set(order)) != len(order):
        raise ValueError(f"{pbip} registra identificadores de página repetidos. Revisa pages.json.")
    if args.pages is not None and args.pages != len(order):
        raise ValueError(f"{pbip} registra {len(order)} páginas. Se esperaban {args.pages}.")
    reference = read(report / "definition.pbir").get("datasetReference", {})
    relative = (reference.get("byPath") or {}).get("path")
    model = (report / relative).resolve() if relative else None
    tables, geographic = field_links(model) if model else ({}, set())
    definition = report / "definition"
    original = fingerprint(definition)
    print(f"Proyecto: {pbip}\nPáginas: {len(order)}")
    updates = {}
    for page_id in order:
        folder = definition / "pages" / page_id
        page = read(folder / "page.json")
        if page.get("name") != page_id:
            raise ValueError(f"El identificador de {folder / 'page.json'} difiere del índice.")
        changes, summary = prepare_page(folder, page, tables, geographic)
        visibility = " [oculta]" if page.get("visibility") == "HiddenInViewMode" else ""
        print(f"  {summary}{visibility}")
        updates.update(changes)
    updates = {path: value for path, value in updates.items() if not path.is_file() or read(path) != value}
    if not updates:
        print("El informe ya tiene el diseño.")
    elif args.preview:
        print(f"Vista previa: {len(updates)} archivos de definición para actualizar.")
    else:
        backup = apply(definition, updates, original)
        print(f"Se actualizaron {len(updates)} archivos de definición.")
        print(f"Respaldo para restaurar la carpeta definition: {backup}")
        print(f"Abre en Power BI Desktop: {pbip}")


if __name__ == "__main__":
    try:
        run()
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"No se pudo aplicar el diseño: {error}")
'@

$archivoTemporal = [IO.Path]::GetTempFileName()
$codificacionAnterior = [Console]::OutputEncoding
try {
    $utf8 = [Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = $utf8
    [IO.File]::WriteAllText($archivoTemporal, $motor, $utf8)
    $argumentos = @("-X", "utf8", $archivoTemporal, "--root", $Raiz)
    if ($PSBoundParameters.ContainsKey("Paginas")) { $argumentos += @("--pages", "$Paginas") }
    if ($ProyectoPbip) { $argumentos += @("--pbip", $ProyectoPbip) }
    if ($VistaPrevia) { $argumentos += "--preview" }
    & $python @argumentos
    if ($LASTEXITCODE -ne 0) {
        throw "El script terminó con código $LASTEXITCODE."
    }
} finally {
    [Console]::OutputEncoding = $codificacionAnterior
    Remove-Item -LiteralPath $archivoTemporal -ErrorAction SilentlyContinue
}
