$token = Get-Content "$env:USERPROFILE\.ghtoken" -Raw
$env:GH_TOKEN = $token.Trim()
Remove-Variable token