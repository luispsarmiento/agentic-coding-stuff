#!/usr/bin/env bash
# graph-init.sh - init CodeGraph / graphify in a project and keep their
# generated files out of git. Exclusions are written BEFORE anything is built.
#
# Usage: graph-init.sh [-t codegraph|graphify|both] [-s local|shared]
#                      [-p PATH] [--install] [-n]
#   -t  tools to set up                (default: both)
#   -s  local  -> <git dir>/info/exclude (no diff, only on this machine)
#       shared -> <repo root>/.gitignore (committed, protects teammates)
#                                      (default: local)
#   -p  project path                   (default: current directory)
#   --install  allow `npm i -g` / `pip install` for missing tools
#   -n  dry run: print what would happen, change nothing
#
# Never runs: git add/commit/rm, `codegraph install`, `graphify install`.

set -euo pipefail

TOOLS="both"; SCOPE="local"; TARGET="."; INSTALL=0; DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    -t) TOOLS="${2:?missing value for -t}"; shift 2 ;;
    -s) SCOPE="${2:?missing value for -s}"; shift 2 ;;
    -p) TARGET="${2:?missing value for -p}"; shift 2 ;;
    --install) INSTALL=1; shift ;;
    -n) DRY=1; shift ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$TOOLS" in codegraph|graphify|both) ;; *) echo "-t must be codegraph|graphify|both" >&2; exit 2 ;; esac
case "$SCOPE" in local|shared) ;; *) echo "-s must be local|shared" >&2; exit 2 ;; esac

say()  { printf '%s\n' "$*"; }
run()  { if [ "$DRY" -eq 1 ]; then say "  (dry-run) $*"; else "$@"; fi; }
want() { [ "$TOOLS" = "both" ] || [ "$TOOLS" = "$1" ]; }

cd "$TARGET"
REPORT=()
WARN=0
RAN="ran"; [ "$DRY" -eq 1 ] && RAN="would run"

# 1. Locate project root ------------------------------------------------------
IS_GIT=0
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IS_GIT=1
  ROOT="$(git rev-parse --show-toplevel)"
else
  ROOT="$(pwd)"
fi
cd "$ROOT"
say "Project root: $ROOT"

# 2-4. Git exclusions (before any build) --------------------------------------
if [ "$IS_GIT" -eq 1 ]; then
  if [ "$SCOPE" = "local" ]; then
    EXCL="$(git rev-parse --git-path info/exclude)"
  else
    EXCL=".gitignore"
  fi
  HEADER="# code-graph tooling (generated, do not commit)"
  PATTERNS=(".codegraph/" "graphify-out/")

  # Make sure the file ends with a newline before appending.
  if [ "$DRY" -eq 0 ]; then
    mkdir -p "$(dirname "$EXCL")"
    touch "$EXCL"
    if [ -s "$EXCL" ] && [ "$(tail -c1 "$EXCL" | wc -l)" -eq 0 ]; then printf '\n' >> "$EXCL"; fi
  fi

  ADDED=0
  for pat in "${PATTERNS[@]}"; do
    if [ -f "$EXCL" ] && grep -qxF -- "$pat" "$EXCL"; then continue; fi
    if [ "$ADDED" -eq 0 ] && ! { [ -f "$EXCL" ] && grep -qxF -- "$HEADER" "$EXCL"; }; then
      if [ "$DRY" -eq 1 ]; then say "  (dry-run) append to $EXCL: $HEADER"; else printf '%s\n' "$HEADER" >> "$EXCL"; fi
    fi
    if [ "$DRY" -eq 1 ]; then say "  (dry-run) append to $EXCL: $pat"; else printf '%s\n' "$pat" >> "$EXCL"; fi
    ADDED=$((ADDED + 1))
  done
  REPORT+=("git: yes | exclusion file: $EXCL ($SCOPE) | lines added: $ADDED")

  # Already tracked? Ignoring will not untrack.
  TRACKED="$(git ls-files -- .codegraph graphify-out | head -n 5)"
  if [ -n "$TRACKED" ]; then
    WARN=1
    REPORT+=("WARNING: already tracked by git (ignore rules do not untrack):")
    while IFS= read -r f; do REPORT+=("    $f"); done <<< "$TRACKED"
    REPORT+=("  fix (not run): git rm -r --cached .codegraph graphify-out")
  fi

  # Verify (skip in dry-run: nothing was written)
  if [ "$DRY" -eq 0 ]; then
    for p in .codegraph/x graphify-out/x; do
      if ! git check-ignore -q -- "$p"; then
        echo "ERROR: $p is NOT ignored after writing $EXCL. Aborting before any build." >&2
        exit 1
      fi
    done
    REPORT+=("verified: .codegraph/ and graphify-out/ are ignored")
  fi
else
  REPORT+=("git: no repo found, exclusions skipped")
fi

# 5. CodeGraph -----------------------------------------------------------------
if want codegraph; then
  if ! command -v codegraph >/dev/null 2>&1; then
    if [ "$INSTALL" -eq 1 ] && command -v npm >/dev/null 2>&1; then
      run npm i -g @colbymchenry/codegraph
    else
      REPORT+=("codegraph: not installed, skipped. Run: npm i -g @colbymchenry/codegraph (or re-run with --install)")
    fi
  fi
  if command -v codegraph >/dev/null 2>&1 || [ "$DRY" -eq 1 ]; then
    if [ -d .codegraph ]; then
      run codegraph index
      REPORT+=("codegraph: existing .codegraph/ found, $RAN: codegraph index")
    else
      run codegraph init -i
      REPORT+=("codegraph: $RAN: codegraph init -i")
    fi
    REPORT+=("codegraph: if the MCP server is not wired to your agents yet, run once yourself: codegraph install")
  fi
fi

# 6. graphify (prepare only; the build is the /graphify skill) -----------------
if want graphify; then
  if ! command -v graphify >/dev/null 2>&1; then
    if [ "$INSTALL" -eq 1 ] && command -v pip >/dev/null 2>&1; then
      run pip install graphifyy
    else
      REPORT+=("graphify: not installed, skipped. Run: pip install graphifyy  (double y), then: graphify install")
    fi
  fi
  if command -v graphify >/dev/null 2>&1; then
    REPORT+=("graphify: build not run here. In your AI assistant run: /graphify .  (may spend model tokens on docs/images)")
  fi
fi

# 7. Final check ---------------------------------------------------------------
if [ "$IS_GIT" -eq 1 ] && [ "$DRY" -eq 0 ]; then
  LEAK="$(git status --short -- .codegraph graphify-out)"
  if [ -n "$LEAK" ]; then
    WARN=1
    REPORT+=("WARNING: git status shows graph files:" "$LEAK")
  else
    REPORT+=("git status: clean of graph files")
  fi
fi

say ""; say "--- report ---"
for line in "${REPORT[@]}"; do say "$line"; done
exit "$WARN"