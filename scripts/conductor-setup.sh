#!/usr/bin/env bash
# Conductor workspace setup.
#
# Keeps three things on the latest:
#   1. the primary clone outside the workspace ($CONDUCTOR_ROOT_PATH) — fetch+rebase if behind
#   2. the shared-context submodule pin — if a newer context commit exists, bump the
#      pin in the primary, commit, and push it directly to the default branch
#   3. this workspace — pull the (possibly newly bumped) base in and check out submodules
#
# Idempotent: a second run with everything current is a no-op (no commit, no push).
set -euo pipefail

BRANCH="${CONDUCTOR_DEFAULT_BRANCH:-main}"
ROOT="${CONDUCTOR_ROOT_PATH:-}"
SUB="shared-context"

if [ -n "$ROOT" ] && [ -d "$ROOT/.git" ]; then
  git -C "$ROOT" fetch --quiet origin "$BRANCH"

  # Only mutate the primary when it is cleanly on $BRANCH (don't disturb other work).
  if [ "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] \
     && git -C "$ROOT" diff --quiet && git -C "$ROOT" diff --cached --quiet; then

    # (1) primary behind origin -> fetch + rebase
    if [ "$(git -C "$ROOT" rev-parse HEAD)" != "$(git -C "$ROOT" rev-parse "origin/$BRANCH")" ]; then
      git -C "$ROOT" rebase "origin/$BRANCH"
    fi

    # (2) submodule: bump the pin to the latest context commit, push it directly
    if [ -f "$ROOT/.gitmodules" ] \
       && git -C "$ROOT" config -f "$ROOT/.gitmodules" --get "submodule.$SUB.url" >/dev/null 2>&1; then
      git -C "$ROOT" submodule update --quiet --init -- "$SUB"
      sub_branch="$(git -C "$ROOT" config -f "$ROOT/.gitmodules" --get "submodule.$SUB.branch" 2>/dev/null || echo main)"
      git -C "$ROOT/$SUB" fetch --quiet origin "$sub_branch"
      cur="$(git -C "$ROOT/$SUB" rev-parse HEAD)"
      latest="$(git -C "$ROOT/$SUB" rev-parse "origin/$sub_branch")"
      if [ "$cur" != "$latest" ]; then
        git -C "$ROOT/$SUB" checkout --quiet --detach "$latest"
        git -C "$ROOT" add "$SUB"
        git -C "$ROOT" commit -m "chore: bump $SUB submodule to latest" --quiet
        git -C "$ROOT" push origin "$BRANCH"
        echo "conductor-setup: bumped $SUB pin ${cur:0:8} -> ${latest:0:8} and pushed to $BRANCH"
      fi
    fi
  else
    echo "conductor-setup: primary not cleanly on $BRANCH, skipped primary/submodule sync" >&2
  fi
fi

# (3) workspace: pull the latest base (incl. any pin bump just pushed) and check out submodules
git fetch --quiet origin "$BRANCH"
git rebase "origin/$BRANCH"
git submodule update --init --recursive
echo "conductor-setup: workspace synced to origin/$BRANCH with submodules"
