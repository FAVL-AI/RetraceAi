#!/usr/bin/env bash
# Before/after probe for the prose-scan separation patch.
#
#   ./reproduce.sh /path/to/pre-commit "BEFORE"
#
# Hostile fixtures are ASSEMBLED AT RUNTIME from fragments. None of the strings
# below is a credit as written: a vendor token with no claim beside it, and a
# claim template with no vendor in it, are both inert. They become hostile only
# once joined, which is what the checker under test must catch. Spelling them
# out here would (correctly) be refused by the very control this script probes.
set -uo pipefail
HOOK="${1:?usage: reproduce.sh <hook-path> <label>}"
LABEL="${2:-probe}"

VENDOR="Cl""aude"
CLAIM="$VENDOR is a co-""author of this document."
TRAILER="Co-""Authored-""By: Someone <a@b.c>"
ORIGIN="Gen""erated by static analysis of the current codebase."
CITATION="Samuel and Mietchen (2024), GigaScience, DOI 10.1093/gigascience/giad113."

export GIT_AUTHOR_NAME="Frank Asante Van Laarhoven"
export GIT_AUTHOR_EMAIL="frankleroyvan@gmail.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

probe() { # $1=case  $2=path  $3=content  $4=allow-list line (may be empty)
  local repo; repo=$(mktemp -d); pushd "$repo" >/dev/null || return
  git init -q .
  [ -n "$4" ] && printf '%s\n' "$4" > .attribution-allow
  mkdir -p "$(dirname "$2")"; printf '%s\n' "$3" > "$2"
  git add -A >/dev/null 2>&1
  if "$HOOK" >/dev/null 2>&1; then
    printf '  %-46s ACCEPT\n' "$1"
  else
    printf '  %-46s REFUSE\n' "$1"
  fi
  popd >/dev/null || return; rm -rf "$repo"
}

echo "=== $LABEL ==="
probe "A prose credit in allowlisted docs/evidence/" "docs/evidence/p.md" "# x
$CLAIM" "docs/evidence/*"
probe "B co-author trailer in docs/evidence/"        "docs/evidence/p.md" "# x
$TRAILER" "docs/evidence/*"
probe "C legitimate citation (ordinary path)"        "docs/notes.md"      "$CITATION" ""
probe "D origin prose in docs/evidence/ (exemption)" "docs/evidence/p.md" "$ORIGIN" "docs/evidence/*"
probe "E prose credit in an ordinary path"           "docs/science/p.md"  "# x
$CLAIM" ""
