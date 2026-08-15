$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SigningDir = Join-Path $ProjectDir ".signing"
$SigningFile = Join-Path $SigningDir "keystore.properties"
$KeyStoreFile = Join-Path $SigningDir "pyvpn-release.jks"
$DistDir = Join-Path $ProjectDir "dist"
$Gradle = if ($env:PYVPN_GRADLE) {
    $env:PYVPN_GRADLE
} else {
    Join-Path $ProjectDir "gradlew.bat"
}

if (-not (Test-Path -LiteralPath $Gradle -PathType Leaf)) {
    throw "Gradle command is missing: $Gradle"
}

$KeyTool = $null
if ($env:JAVA_HOME) {
    $Candidate = Join-Path $env:JAVA_HOME "bin\keytool.exe"
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        $KeyTool = $Candidate
    }
}
if (-not $KeyTool) {
    $Command = Get-Command keytool.exe -ErrorAction SilentlyContinue
    if ($Command) { $KeyTool = $Command.Source }
}
if (-not $KeyTool) {
    throw "JDK 17 keytool.exe was not found. Set JAVA_HOME to a JDK 17 installation."
}

if ((Test-Path -LiteralPath $SigningFile) -xor (Test-Path -LiteralPath $KeyStoreFile)) {
    throw "The local signing files are incomplete. Restore both files under android\.signing."
}

if (-not (Test-Path -LiteralPath $SigningFile)) {
    New-Item -ItemType Directory -Force -Path $SigningDir | Out-Null
    $Password = ([Guid]::NewGuid().ToString("N") + [Guid]::NewGuid().ToString("N"))
    & $KeyTool -genkeypair `
        -keystore $KeyStoreFile `
        -storepass $Password `
        -keypass $Password `
        -alias pyvpn `
        -keyalg RSA `
        -keysize 4096 `
        -validity 10000 `
        -dname "CN=pyvpn, OU=pyvpn, O=pyvpn, C=CN"
    if ($LASTEXITCODE -ne 0) { throw "Could not create the APK signing key." }
    [IO.File]::WriteAllLines($SigningFile, @(
        "storeFile=.signing/pyvpn-release.jks",
        "storePassword=$Password",
        "keyAlias=pyvpn",
        "keyPassword=$Password"
    ), [Text.Encoding]::ASCII)
}

Push-Location $ProjectDir
try {
    $GradleArguments = @("--no-daemon")
    if ($env:PYVPN_GRADLE_OFFLINE -eq "1") {
        $GradleArguments += "--offline"
    }
    if ($env:PYVPN_GRADLE_INIT_SCRIPT) {
        $GradleArguments += @("-I", $env:PYVPN_GRADLE_INIT_SCRIPT)
    }
    $GradleArguments += @("testDebugUnitTest", "lintRelease", "assembleRelease")
    & $Gradle @GradleArguments
    if ($LASTEXITCODE -ne 0) { throw "Android build failed." }
} finally {
    Pop-Location
}

$BuiltApk = Join-Path $ProjectDir "app\build\outputs\apk\release\pyvpn-android-0.1.0.apk"
if (-not (Test-Path -LiteralPath $BuiltApk -PathType Leaf)) {
    throw "The release APK was not produced: $BuiltApk"
}
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
$OutputApk = Join-Path $DistDir "pyvpn-android-0.1.0.apk"
Copy-Item -Force -LiteralPath $BuiltApk -Destination $OutputApk
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputApk).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$OutputApk.sha256", "$Hash  pyvpn-android-0.1.0.apk`n", [Text.Encoding]::ASCII)

Write-Host ""
Write-Host "APK: $OutputApk"
Write-Host "SHA-256: $Hash"
Write-Host "Signing key backup required: $SigningDir"
