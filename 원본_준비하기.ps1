param([string]$OriginalRepository = (Join-Path (Split-Path -Parent $PSScriptRoot) 'langrisser-saturn-kr-original'))
$ErrorActionPreference = 'Stop'
try {
    $originalRoot = (Resolve-Path -LiteralPath $OriginalRepository).Path
    $manifest = Get-Content -LiteralPath (Join-Path $originalRoot 'file_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $projectPrefix = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
    $sourcePrefix = [IO.Path]::GetFullPath($originalRoot).TrimEnd('\') + '\'
    $planned = @()
    foreach ($item in $manifest.files) {
        $sourceFile = [IO.Path]::GetFullPath((Join-Path $originalRoot $item.path))
        $targetFile = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $item.path))
        if (!$sourceFile.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase) -or !$targetFile.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw '목록에 잘못된 파일 경로가 있습니다.' }
        if (!(Test-Path -LiteralPath $sourceFile -PathType Leaf)) { throw ('원본 파일이 없습니다: ' + $item.path + '. 원본 저장소에서 git lfs pull을 실행하세요.') }
        if ((Get-Item -LiteralPath $sourceFile).Length -ne $item.bytes -or (Get-FileHash -LiteralPath $sourceFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw ('원본 내용이 다릅니다: ' + $item.path + '. 원본 저장소에서 git lfs pull을 실행하세요.') }
        if (Test-Path -LiteralPath $targetFile) {
            if ((Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.sha256) { throw ('다른 내용의 파일이 이미 있습니다. 덮어쓰지 않았습니다: ' + $item.path) }
        } else { $planned += [pscustomobject]@{ source=$sourceFile; target=$targetFile } }
    }
    foreach ($item in $planned) {
        $targetDirectory = Split-Path -Parent $item.target
        New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
        Copy-Item -LiteralPath $item.source -Destination $item.target
    }
    Write-Host ('원본 준비 완료. 새로 복사한 파일: ' + $planned.Count)
} catch {
    Write-Host ('원본 준비 실패: ' + $_.Exception.Message)
    exit 1
}
