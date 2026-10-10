#!/usr/bin/env bash
# Auto-commit and push non-ignored changes from the current Git repository to origin/main.
# Usage: ./auto-push.sh [poll_seconds]
set -u

POLL_SECONDS="${1:-5}"
if ! [[ "$POLL_SECONDS" =~ ^[0-9]+$ ]] || (( POLL_SECONDS < 1 )); then
  echo "Usage: $0 [poll_seconds>=1]" >&2
  exit 2
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Run this script inside a Git repository." >&2
  exit 1
}
cd "$ROOT" || exit 1

BRANCH="$(git branch --show-current)"
if [[ "$BRANCH" != "main" ]]; then
  echo "Expected branch 'main', current branch is '$BRANCH'. Switch to main first." >&2
  exit 1
fi
git remote get-url origin >/dev/null 2>&1 || {
  echo "Git remote 'origin' is missing." >&2
  exit 1
}

echo "Watching $ROOT every $POLL_SECONDS seconds. Press Ctrl+C to stop."
echo "Review .gitignore first. Non-ignored changes can be published to GitHub."

while true; do
  sleep "$POLL_SECONDS"
  if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    git add -A || { echo "git add failed; will retry." >&2; continue; }
    if ! git diff --cached --quiet; then
      git commit -m "Auto-sync local changes $(date '+%Y-%m-%d %H:%M:%S')" || {
        echo "Commit failed. Configure git user.name/user.email; will retry." >&2
        continue
      }
    fi
  fi

  # Fetch first so we do not push blindly over new remote commits.
  if ! git fetch origin main; then
    echo "Fetch failed; check network/authentication. Will retry." >&2
    continue
  fi
  if ! git merge-base --is-ancestor origin/main main; then
    echo "Remote main has commits not in local main. Stopping to avoid overwriting; pull/reconcile manually." >&2
    exit 1
  fi

  AHEAD="$(git rev-list --count origin/main..main)"
  if [[ "$AHEAD" =~ ^[0-9]+$ ]] && (( AHEAD > 0 )); then
    if git push origin main; then
      echo "Pushed changes to GitHub at $(date '+%H:%M:%S')."
    else
      echo "Push failed; will retry after checking network/authentication/conflicts." >&2
    fi
  fi
done
