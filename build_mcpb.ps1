param(
    [string]$Output = "dist\Sparkle.mcpb"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$OutputPath = [System.IO.Path]::GetFullPath((Join-Path $Root $Output))
$ExePath = Join-Path $Root "dist\SparkleMCP.exe"
$ManifestPath = Join-Path $Root "mcpb\manifest.json"
$IconPath = Join-Path $Root "Icon.png"

foreach ($RequiredPath in @($ExePath, $ManifestPath, $IconPath)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "必要なファイルがありません: $RequiredPath"
    }
}

$StagePath = Join-Path ([System.IO.Path]::GetTempPath()) ("sparkle-mcpb-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path (Join-Path $StagePath "server") -Force | Out-Null

try {
    Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $StagePath "manifest.json")
    Copy-Item -LiteralPath $IconPath -Destination (Join-Path $StagePath "icon.png")
    Copy-Item -LiteralPath $ExePath -Destination (Join-Path $StagePath "server\SparkleMCP.exe")

    $OutputDirectory = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    Compress-Archive -Path (Join-Path $StagePath "manifest.json"), (Join-Path $StagePath "icon.png"), (Join-Path $StagePath "server") -DestinationPath $OutputPath -Force
    Write-Output "Created $OutputPath"
}
finally {
    if (Test-Path -LiteralPath $StagePath) {
        Remove-Item -LiteralPath $StagePath -Recurse -Force
    }
}
