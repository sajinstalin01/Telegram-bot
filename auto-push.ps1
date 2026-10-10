# Automatically commit and push local project changes to GitHub.
# Run from the repository root in PowerShell: .\auto-push.ps1
# Requires Git installed, a configured Git identity, and authenticated access to origin.

$ErrorActionPreference = "Stop"
$PollSeconds = 5

function Invoke-Git {
    param([string[]]$GitArgs)
    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($output -join "`n")
    }
    return $output
}

try {
    $root = (Invoke-Git -GitArgs @("rev-parse", "--show-toplevel") | Select-Object -First 1).Trim()
    Set-Location $root
    $branch = (Invoke-Git -GitArgs @("branch", "--show-current") | Select-Object -First 1).Trim()
    if ($branch -ne "main") {
        throw "This auto-push script expects branch 'main'; current branch is '$branch'. Switch to main first."
    }

    $remotes = Invoke-Git -GitArgs @("remote")
    if ($remotes -notcontains "origin") {
        throw "Git remote 'origin' was not found. Add your GitHub repository as origin first."
    }
} catch {
    Write-Host "Auto-push cannot start: $_" -ForegroundColor Red
    exit 1
}

Write-Host "Watching $root for changes. Press Ctrl+C to stop." -ForegroundColor Green
Write-Host "Only files not excluded by .gitignore can be committed; review .gitignore before using." -ForegroundColor Yellow

while ($true) {
    Start-Sleep -Seconds $PollSeconds
    try {
        $status = & git status --porcelain
        if ($LASTEXITCODE -ne 0) {
            throw "Could not read Git status."
        }

        if ($status) {
            & git add -A
            if ($LASTEXITCODE -ne 0) {
                throw "git add failed."
            }

            $staged = & git diff --cached --quiet
            if ($LASTEXITCODE -eq 1) {
                $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                & git commit -m "Auto-sync local changes $stamp"
                if ($LASTEXITCODE -ne 0) {
                    throw "git commit failed. Configure user.name and user.email in Git."
                }
            }

            $status = & git status --porcelain
            if ($status) {
                Write-Host "Some changes remain uncommitted; check Git output." -ForegroundColor Yellow
            }
        }

        # Also retry pushing already-committed local changes if a previous push failed.
        $ahead = & git rev-list --count "origin/main..main" 2>$null
        if ($LASTEXITCODE -eq 0 -and [int]($ahead | Select-Object -First 1) -gt 0) {
            & git push origin main
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Pushed latest changes to GitHub at $(Get-Date -Format 'HH:mm:ss')." -ForegroundColor Green
            } else {
                Write-Host "Push failed; will retry. Check network, GitHub authentication, and remote conflicts." -ForegroundColor Yellow
            }
        }
    } catch {
        Write-Host "Auto-push warning: $_" -ForegroundColor Yellow
    }
}
