param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][ValidateSet('Directory')][string]$Kind
)
$ErrorActionPreference = 'Stop'
# Fixed helper for scripts/ag_slice_run.py: apply the owner-only, inheritable ACL
# (reused from the verified AG-GEMINI-SLICE-CODING-01 host scripts) to exactly one
# existing directory. Files created inside inherit owner-only access, so sensitive
# bytes are never written before the container is protected.
function Set-OwnerOnlyDirectory([string]$path) {
  $acl = New-Object System.Security.AccessControl.DirectorySecurity
  $acl.SetOwner([System.Security.Principal.NTAccount]$env:USERNAME)
  $acl.SetAccessRuleProtection($true, $false)
  $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule($env:USERNAME, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
  Set-Acl -LiteralPath $path -AclObject $acl
}
if ($Kind -ne 'Directory') { throw 'ONLY_DIRECTORY_SUPPORTED' }
if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'DIRECTORY_MISSING' }
Set-OwnerOnlyDirectory $Path
exit 0
