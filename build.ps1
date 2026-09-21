# Повна збірка релізу VaultDrop: тести -> vaultdrop.exe (PyInstaller) -> Tauri + NSIS -> dist\
# Запуск з кореня проекту:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    throw 'Нема .venv. Створи: <python 3.12> -m venv .venv; .venv\Scripts\python -m pip install -e .[dev]'
}
# Кеші збірки — у проекті на D:, не в профілі на C:
$env:CARGO_HOME = Join-Path $PSScriptRoot '.cache\cargo'
$env:npm_config_cache = Join-Path $PSScriptRoot '.cache\npm'
$env:PIP_CACHE_DIR = Join-Path $PSScriptRoot '.cache\pip'

function Step($name, [scriptblock]$body) {
    Write-Host "== $name"
    & $body
    if ($LASTEXITCODE) { throw "${name}: код виходу $LASTEXITCODE" }
}

Step 'Тести' { & $py -m pytest -q }
Step 'vaultdrop.exe (PyInstaller)' {
    & $py -m PyInstaller --noconfirm --log-level WARN --onefile --console --name vaultdrop --paths src-core `
        --add-data "$PSScriptRoot\src-core\vaultdrop\locales;vaultdrop\locales" `
        --distpath .tmp\pyi\dist --workpath .tmp\pyi\build --specpath .tmp\pyi src-core\vaultdrop\__main__.py
}
New-Item -ItemType Directory -Force src-app\src-tauri\binaries, dist | Out-Null
Copy-Item .tmp\pyi\dist\vaultdrop.exe src-app\src-tauri\binaries\vaultdrop-x86_64-pc-windows-msvc.exe -Force

Push-Location src-app
try {
    Step 'npm ci' { npm ci --no-audit --no-fund }
    Step 'UI model tests' { npm test }
    Step 'UI browser tests' { npm run test:ui }
    Step 'Tauri + NSIS' { npx tauri build }
} finally {
    Pop-Location
}

$setup = Get-ChildItem src-app\src-tauri\target\release\bundle\nsis\*-setup.exe | Sort-Object LastWriteTime | Select-Object -Last 1
Copy-Item $setup.FullName dist\ -Force
Copy-Item .tmp\pyi\dist\vaultdrop.exe dist\ -Force
$releaseVersion = (Get-Content src-app\src-tauri\tauri.conf.json -Raw | ConvertFrom-Json).version
$portableDir = Join-Path $PSScriptRoot "dist\VaultDrop-$releaseVersion-portable"
New-Item -ItemType Directory -Force $portableDir | Out-Null
Copy-Item src-app\src-tauri\target\release\vaultdrop-gui.exe (Join-Path $portableDir 'VaultDrop Desktop.exe') -Force
Copy-Item .tmp\pyi\dist\vaultdrop.exe (Join-Path $portableDir 'vaultdrop.exe') -Force
Compress-Archive -Path "$portableDir\*" -DestinationPath "dist\VaultDrop-$releaseVersion-portable.zip" -Force
Get-ChildItem dist\* -File | Where-Object { $_.Extension -in '.exe', '.zip' } |
    ForEach-Object { '{0}  {1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name } |
    Set-Content -Encoding ascii dist\SHA256SUMS.txt
Get-Content dist\SHA256SUMS.txt


