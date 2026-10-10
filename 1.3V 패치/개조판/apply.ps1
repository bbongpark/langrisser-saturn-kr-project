param([string]$InputCue)

$ErrorActionPreference = 'Stop'

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Assert-File([string]$Path, $Entry, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label 파일을 찾을 수 없습니다: $Path"
    }
    $size = (Get-Item -LiteralPath $Path).Length
    if ($null -ne $Entry.size -and $size -ne [long]$Entry.size) {
        throw "$Label 크기가 맞지 않습니다: $Path"
    }
    if ((Get-Sha256 $Path) -ne $Entry.sha256.ToLowerInvariant()) {
        throw "$Label 내용이 지원하는 판본과 다릅니다: $Path"
    }
}

function Assert-PackageFile([string]$Path, [string]$ExpectedHash, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label 파일을 찾을 수 없습니다: $Path"
    }
    if ((Get-Sha256 $Path) -ne $ExpectedHash.ToLowerInvariant()) {
        throw "$Label 파일이 배포본과 다릅니다: $Path"
    }
}

function Main {
    $package = $PSScriptRoot
    $manifest = Get-Content -LiteralPath (Join-Path $package 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format_version -ne 1 -or $manifest.source_tracks.Count -ne 6 -or $manifest.result_tracks.Count -ne 6) {
        throw '패치 설정 파일 형식이 올바르지 않습니다.'
    }
    foreach ($name in @($manifest.patch_file, $manifest.cue_file, $manifest.tool_file, $manifest.output_folder)) {
        if ([string]::IsNullOrWhiteSpace($name) -or [IO.Path]::GetFileName($name) -ne $name) {
            throw '패치 설정에 잘못된 파일 이름이 있습니다.'
        }
    }
    $patch = Join-Path $package $manifest.patch_file
    $outputCue = Join-Path $package $manifest.cue_file
    $tool = Join-Path $package $manifest.tool_file
    Assert-PackageFile $patch $manifest.patch_sha256 '패치'
    Assert-PackageFile $outputCue $manifest.cue_sha256 '출력 CUE'
    Assert-PackageFile $tool $manifest.tool_sha256 '적용 도구'

    if ([string]::IsNullOrWhiteSpace($InputCue)) {
        $InputCue = Read-Host '원본 CUE 파일 또는 원본 폴더의 경로를 붙여 넣으세요'
    }
    $InputCue = $InputCue.Trim().Trim('"')
    $item = Get-Item -LiteralPath $InputCue -ErrorAction Stop
    if ($item.PSIsContainer) {
        $cues = @(Get-ChildItem -LiteralPath $item.FullName -File -Filter '*.cue')
        if ($cues.Count -ne 1) {
            throw '폴더에 CUE 파일이 정확히 하나 있어야 합니다. CUE 파일을 직접 지정해 주세요.'
        }
        $item = $cues[0]
    }
    if ($item.Extension -ine '.cue') {
        throw '원본 CUE 파일을 지정해 주세요.'
    }
    $sourceDir = $item.DirectoryName
    $cueText = Get-Content -LiteralPath $item.FullName -Raw
    $refs = [regex]::Matches($cueText, '(?im)^\s*FILE\s+"([^"]+)"\s+BINARY\s*$')
    if ($refs.Count -ne 6) {
        throw '원본 CUE에 BINARY 트랙 6개가 있어야 합니다.'
    }
    $sourceFiles = @()
    for ($i = 0; $i -lt 6; $i++) {
        $fileName = $refs[$i].Groups[1].Value
        if ([IO.Path]::GetFileName($fileName) -ne $fileName) {
            throw 'CUE의 트랙 파일은 원본 CUE와 같은 폴더에 있어야 합니다.'
        }
        $file = Join-Path $sourceDir $fileName
        Write-Host ("원본 트랙 {0}/6 확인 중..." -f ($i + 1))
        Assert-File $file $manifest.source_tracks[$i] ("원본 트랙 {0}" -f ($i + 1))
        $sourceFiles += $file
    }

    $final = Join-Path $sourceDir $manifest.output_folder
    if (Test-Path -LiteralPath $final) {
        throw "출력 폴더가 이미 있습니다. 기존 결과를 확인해 주세요: $final"
    }
    $stage = Join-Path $sourceDir ('.langrisser-v13-pending-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        Write-Host '첫 번째 트랙에 패치 적용 중...'
        & $tool -d -s $sourceFiles[0] $patch (Join-Path $stage 'track1.bin')
        if ($LASTEXITCODE -ne 0) {
            throw "패치 도구가 실패했습니다. 종료 코드: $LASTEXITCODE"
        }
        for ($i = 1; $i -lt 6; $i++) {
            Copy-Item -LiteralPath $sourceFiles[$i] -Destination (Join-Path $stage ("track{0}.bin" -f ($i + 1)))
        }
        Copy-Item -LiteralPath $outputCue -Destination (Join-Path $stage $manifest.cue_file)
        for ($i = 0; $i -lt 6; $i++) {
            Write-Host ("완성된 트랙 {0}/6 확인 중..." -f ($i + 1))
            Assert-File (Join-Path $stage ("track{0}.bin" -f ($i + 1))) $manifest.result_tracks[$i] ("완성 트랙 {0}" -f ($i + 1))
        }
        Assert-PackageFile (Join-Path $stage $manifest.cue_file) $manifest.cue_sha256 '완성 CUE'
        Move-Item -LiteralPath $stage -Destination $final
        $stage = $null
        Write-Host ''
        Write-Host "완료: $final"
        Write-Host ("게임을 열 때 사용할 파일: {0}" -f (Join-Path $final $manifest.cue_file))
    }
    finally {
        if ($stage -and (Test-Path -LiteralPath $stage)) {
            $safeParent = [IO.Path]::GetFullPath([IO.Path]::GetDirectoryName($stage))
            if ($safeParent -ne [IO.Path]::GetFullPath($sourceDir) -or
                -not ([IO.Path]::GetFileName($stage).StartsWith('.langrisser-v13-pending-'))) {
                throw '임시 폴더 경로가 예상과 달라 정리를 중단했습니다.'
            }
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
}

try {
    Main
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('적용 실패: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
