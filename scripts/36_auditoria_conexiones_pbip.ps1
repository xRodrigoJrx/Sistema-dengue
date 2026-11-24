$project = "C:\Users\xxter\Documents\Data_Dengue\Sistema"

$tables = Join-Path $project "powerbi\Dengue_Analytics\Dengue_Analytics.SemanticModel\definition\tables"

$reportPath = Join-Path $project "reports\powerbi\36_auditoria_conexiones_pbip.txt"

$files = Get-ChildItem -LiteralPath $tables -Filter "*.tmdl" -File

$reportLines = [System.Collections.Generic.List[string]]::new()

$sqlConnectionCount = 0

$reportLines.Add("AUDITORIA DE CONEXIONES SQL - DENGUE ANALYTICS")
$reportLines.Add("Fecha: $(Get-Date)")
$reportLines.Add("Archivos TMDL: $($files.Count)")
$reportLines.Add("")

foreach ($file in $files) {

    $fileLines = [System.IO.File]::ReadAllLines($file.FullName)

    for ($i = 0; $i -lt $fileLines.Length; $i++) {

        if ($fileLines[$i] -match 'Sql\.Database\s*\(') {

            $sqlConnectionCount++

            $reportLines.Add("============================================")
            $reportLines.Add("TABLA: $($file.Name)")
            $reportLines.Add("CONEXION SQL NUMERO: $sqlConnectionCount")
            $reportLines.Add("")

            $startLine = [Math]::Max(0, $i - 3)
            $endLine = [Math]::Min($fileLines.Length - 1, $i + 30)

            for ($j = $startLine; $j -le $endLine; $j++) {

                $lineText = "{0,4}: {1}" -f ($j + 1), $fileLines[$j]

                $reportLines.Add($lineText)
            }

            $reportLines.Add("")
        }
    }
}

$reportLines.Add("============================================")
$reportLines.Add("RESUMEN FINAL")
$reportLines.Add("============================================")
$reportLines.Add("Archivos TMDL: $($files.Count)")
$reportLines.Add("Conexiones SQL encontradas: $sqlConnectionCount")

$geoFile = Join-Path $tables "dim_distrito.tmdl"

$reportLines.Add("")
$reportLines.Add("===== CONFIGURACION GEOGRAFICA =====")

if (Test-Path $geoFile) {

    $geoLines = Get-Content -LiteralPath $geoFile

    foreach ($line in $geoLines) {

        if ($line -match 'latitud|longitud|dim_distrito_geo|dataCategory') {

            $reportLines.Add($line.Trim())
        }
    }
}

[System.IO.File]::WriteAllLines(
    $reportPath,
    $reportLines.ToArray(),
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "`nAUDITORIA COMPLETADA" -ForegroundColor Green

Write-Host "Archivos TMDL: $($files.Count)"
Write-Host "Conexiones SQL: $sqlConnectionCount"

Write-Host "`nREPORTE:"
Write-Host $reportPath

Write-Host "`n===== RESULTADOS ====="

Get-Content -LiteralPath $reportPath