function Get-PyVpnClipboardText {
    $clipboardCommand = Get-Command Get-Clipboard -ErrorAction SilentlyContinue
    if (-not $clipboardCommand) {
        throw "Ctrl+V was received as a control character, but Get-Clipboard is unavailable. Use right-click paste or pass --token explicitly."
    }
    return (@(Get-Clipboard -ErrorAction Stop) -join [Environment]::NewLine)
}

function Normalize-PyVpnTokenInput([AllowNull()][string]$Value) {
    if ($null -eq $Value) {
        return ""
    }
    $normalized = $Value.Trim()
    if ($normalized.StartsWith("PYVPN_TOKEN=", [StringComparison]::OrdinalIgnoreCase)) {
        $normalized = $normalized.Substring("PYVPN_TOKEN=".Length).Trim()
    }
    foreach ($character in $normalized.ToCharArray()) {
        if ([char]::IsControl($character)) {
            throw "Shared token contains a control character. Copy it again and paste with Ctrl+V or right-click."
        }
    }
    return $normalized
}

function Resolve-PyVpnTokenInput([AllowNull()][string]$Value) {
    $resolved = $Value
    if ($null -ne $resolved -and $resolved.IndexOf([char]0x16) -ge 0) {
        $resolved = Get-PyVpnClipboardText
        Write-Host "Shared token read from the clipboard."
    }
    $resolved = Normalize-PyVpnTokenInput $resolved
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        throw "Shared token is required."
    }
    return $resolved
}

function Read-PyVpnSecretToken([AllowNull()][string]$CurrentValue = "") {
    if (-not [string]::IsNullOrWhiteSpace($CurrentValue)) {
        return Resolve-PyVpnTokenInput $CurrentValue
    }
    $secure = Read-Host "Shared token" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    return Resolve-PyVpnTokenInput $value
}
