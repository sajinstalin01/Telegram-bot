#!/usr/bin/env python3
"""Watch a Git repository and auto-commit/push changes to origin/main.

Usage: python auto_push.py [poll_seconds]
Requires Git installed, origin configured, and GitHub authentication set up.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False
    )
    if check and result.returncode:
        raise RuntimeError(result.stdout.strip() or f"git {' '.join(args)} failed")
    return result


def main() -> int:
    try:
        poll = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        if poll < 1:
            raise ValueError("poll_seconds must be at least 1")
        root = git("rev-parse", "--show-toplevel").stdout.strip()
        branch = git("branch", "--show-current").stdout.strip()
        if branch != "main":
            raise RuntimeError(f"Expected branch 'main', current branch is {branch!r}")
        git("remote", "get-url", "origin")
    except (ValueError, RuntimeError) as exc:
        print(f"Cannot start auto-push: {exc}", file=sys.stderr)
        return 1

    print(f"Watching {root} every {poll} seconds. Press Ctrl+C to stop.")
    print("Review .gitignore first; non-ignored changes may be published to GitHub.")

    try:
        while True:
            time.sleep(poll)
            status = git("status", "--porcelain").stdout.strip()
            if status:
                git("add", "-A")
                staged = git("diff", "--cached", "--quiet", check=False)
                if staged.returncode == 1:
                    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    commit = git("commit", "-m", f"Auto-sync local changes {stamp}", check=False)
                    if commit.returncode:
                        print("Commit failed; configure Git identity. Will retry.", file=sys.stderr)
                        print(commit.stdout, file=sys.stderr)
                        continue

            fetch = git("fetch", "origin", "main", check=False)
            if fetch.returncode:
                print("Fetch failed; check network/authentication. Will retry.", file=sys.stderr)
                continue

            ancestry = git("merge-base", "--is-ancestor", "origin/main", "main", check=False)
            if ancestry.returncode != 0:
                print("Remote main has commits not in local main. Stopping to avoid overwriting; pull/reconcile manually.", file=sys.stderr)
                return 1

            ahead = git("rev-list", "--count", "origin/main..main").stdout.strip()
            if ahead.isdigit() and int(ahead) > 0:
                push = git("push", "origin", "main", check=False)
                if push.returncode == 0:
                    print(f"Pushed changes to GitHub at {datetime.now():%H:%M:%S}.")
                else:
                    print("Push failed; will retry after checking network/authentication/conflicts.", file=sys.stderr)
                    print(push.stdout, file=sys.stderr)
    except KeyboardInterrupt:
        print("\nAuto-push stopped.")
        return 0
    except RuntimeError as exc:
        print(f"Auto-push warning: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
