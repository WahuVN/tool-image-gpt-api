$AppDir = $PSScriptRoot
$Target = Join-Path $AppDir 'launch_wahu.vbs'

if (-not (Test-Path $Target)) {
    Write-Host "Khong tim thay launcher VBS: $Target"
    exit 1
}

$Desktop = [Environment]::GetFolderPath('Desktop')
if (-not $Desktop) {
    Write-Host "Khong xac dinh duoc Desktop."
    exit 1
}

# Remove the legacy "9Router Image Studio" shortcut if it exists.
$LegacyLink = Join-Path $Desktop '9Router Image Studio.lnk'
if (Test-Path $LegacyLink) {
    Remove-Item $LegacyLink -Force
    Write-Host "Da go shortcut cu: 9Router Image Studio.lnk"
}

$Link = Join-Path $Desktop 'Wahu Image Studio.lnk'

$WS = New-Object -ComObject WScript.Shell
$SC = $WS.CreateShortcut($Link)
$SC.TargetPath = $Target
$SC.WorkingDirectory = $AppDir
$SC.IconLocation = 'imageres.dll,109'
$SC.Description = 'Wahu Image Studio - Mo app tao anh AI bang 1 click'
$SC.WindowStyle = 1
$SC.Save()

if (Test-Path $Link) {
    Write-Host ''
    Write-Host '============================================================'
    Write-Host ' DA TAO SHORTCUT TREN DESKTOP'
    Write-Host '============================================================'
    Write-Host (' ' + $Link)
    Write-Host ''
    Write-Host ' Tu Desktop, nhap doi vao bieu tuong "Wahu Image Studio"'
    Write-Host ' de mo app trong cua so dep, khong co cua so cmd den.'
    Write-Host '============================================================'
} else {
    Write-Host 'Tao shortcut that bai.'
    exit 1
}
