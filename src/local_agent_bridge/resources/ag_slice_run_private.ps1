param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][ValidateSet('Directory')][string]$Kind,
  [ValidateSet('Protect', 'Verify')][string]$Mode = 'Protect'
)
$ErrorActionPreference = 'Stop'
# Fixed helper for one directory: initialize only after creation, or verify an
# existing container without rewriting its ACL.
function Assert-OwnerOnlyDirectory(
  [string]$path,
  [System.Security.Principal.SecurityIdentifier]$ownerSid
) {
  $acl = Get-Acl -LiteralPath $path
  if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $ownerSid.Value) {
    throw 'OWNER_MISMATCH'
  }
  if (-not $acl.AreAccessRulesProtected) { throw 'DACL_NOT_PROTECTED' }
  $rules = $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])
  if ($rules.Count -ne 1) { throw 'DACL_RULE_COUNT_MISMATCH' }
  $rule = $rules[0]
  $expectedInheritance = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
    [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
  if (
    $rule.IdentityReference.Value -ne $ownerSid.Value -or
    $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
    $rule.IsInherited -or
    $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
    $rule.InheritanceFlags -ne $expectedInheritance -or
    $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None
  ) {
    throw 'DACL_RULE_MISMATCH'
  }
}
function Set-OwnerOnlyDirectory(
  [string]$path,
  [System.Security.Principal.SecurityIdentifier]$ownerSid
) {
  $acl = New-Object System.Security.AccessControl.DirectorySecurity
  $acl.SetOwner($ownerSid)
  $acl.SetAccessRuleProtection($true, $false)
  $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($ownerSid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
  Set-Acl -LiteralPath $path -AclObject $acl
}
if ($Kind -ne 'Directory') { throw 'ONLY_DIRECTORY_SUPPORTED' }
if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'DIRECTORY_MISSING' }
$ownerSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if ($null -eq $ownerSid) { throw 'CURRENT_SID_UNAVAILABLE' }
if ($Mode -eq 'Protect') { Set-OwnerOnlyDirectory $Path $ownerSid }
Assert-OwnerOnlyDirectory $Path $ownerSid
exit 0
