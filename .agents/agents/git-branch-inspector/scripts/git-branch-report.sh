#!/usr/bin/env bash
# git-branch-report.sh
# Read-only git inspection: collects every local and remote branch, flags the
# ones with recent activity and prints a compact, LLM-friendly plain-text report.
#
# The only command that writes anything is the optional `git fetch` (-f), which
# updates remote-tracking refs and never touches the working tree or the index.
#
# Usage: git-branch-report.sh [-C path] [-d days] [-r days] [-b base] [-a author]
#                             [-n commits] [-m branches] [-f]
#   -C path      repository path (default: .)
#   -d days      "active" window in days (default: 30)
#   -r days      "recent" window in days (default: 90)
#   -b base      base branch/ref to compare against (default: auto-detect)
#   -a author    only show commits whose author matches this pattern
#   -n commits   max commits listed per branch (default: 8)
#   -m branches  max branches with detailed analysis (default: 10)
#   -f           run `git fetch --all --prune` first (updates remote refs)
#   -h           show this help

LC_ALL=C
export LC_ALL
export GIT_OPTIONAL_LOCKS=0   # never take locks / refresh the index

REPO="."; WINDOW=30; RECENT=90; BASE=""; AUTHOR=""; MAXC=8; MAXB=10; FETCH=0
MAXT=40          # max rows in the all-branches table
STALE_DAYS=14    # unintegrated work older than this is flagged STALE
FAR_BEHIND=30    # behind count that triggers FAR_BEHIND_BASE

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; }

while getopts "C:d:r:b:a:n:m:fh" opt; do
  case $opt in
    C) REPO=$OPTARG ;;
    d) WINDOW=$OPTARG ;;
    r) RECENT=$OPTARG ;;
    b) BASE=$OPTARG ;;
    a) AUTHOR=$OPTARG ;;
    n) MAXC=$OPTARG ;;
    m) MAXB=$OPTARG ;;
    f) FETCH=1 ;;
    h) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

g() { git -C "$REPO" --no-pager "$@"; }

fmt_ts() { date -d "@$1" '+%Y-%m-%d %H:%M' 2>/dev/null || date -r "$1" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "$1"; }
file_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

if ! g rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: not a git repository (or no work tree): $REPO"
  exit 1
fi

NOW=$(date +%s)
TOP=$(g rev-parse --show-toplevel)
CURRENT=$(g branch --show-current 2>/dev/null)
[ -z "$CURRENT" ] && CURRENT="(detached HEAD at $(g rev-parse --short HEAD 2>/dev/null))"

# ---------- optional fetch ----------
FETCH_NOTE=""
if [ "$FETCH" = 1 ]; then
  if out=$(g fetch --all --prune --quiet 2>&1); then
    FETCH_NOTE="fetch executed now"
  else
    FETCH_NOTE="fetch FAILED: $(echo "$out" | head -n 2 | tr '\n' ' ')"
  fi
fi

# ---------- last fetch time ----------
COMMON=$(cd "$REPO" && cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd)
LASTFETCH="unknown (never fetched or no remotes)"
if [ -n "$COMMON" ] && [ -f "$COMMON/FETCH_HEAD" ]; then
  mt=$(file_mtime "$COMMON/FETCH_HEAD")
  if [ -n "$mt" ]; then
    LASTFETCH="$(fmt_ts "$mt") ($(( (NOW - mt) / 3600 ))h ago)"
  fi
fi

# ---------- base detection ----------
BASE_HOW="given with -b"
if [ -z "$BASE" ]; then
  BASE_HOW="origin/HEAD"
  BASE=$(g symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)
  if [ -z "$BASE" ]; then
    for c in origin/main origin/master origin/develop main master develop; do
      if g rev-parse --verify --quiet "$c^{commit}" >/dev/null; then
        BASE=$c; BASE_HOW="first existing candidate"; break
      fi
    done
  fi
fi
if [ -z "$BASE" ]; then
  BASE=$(g rev-parse --abbrev-ref HEAD 2>/dev/null)
  BASE_HOW="FALLBACK: current branch (no main/master/develop found)"
fi
BASE_SHORT=$BASE
if g show-ref --verify --quiet "refs/remotes/$BASE"; then BASE_SHORT=${BASE#*/}; fi

# ---------- inventory (local + remote collapsed by branch name) ----------
# Output per line: name <TAB> scopes <TAB> full-ref-of-newest-tip <TAB> unix-ts
INV=$(g for-each-ref --sort=-committerdate \
        --format='%(refname)%09%(committerdate:unix)' refs/heads refs/remotes |
  awk -F'\t' '
  {
    ref=$1; ts=$2
    if (ref ~ /\/HEAD$/) next
    if (ref ~ /^refs\/heads\//) { name=substr(ref,12); scope="local" }
    else { rest=substr(ref,14); i=index(rest,"/"); name=substr(rest,i+1); scope="remote:" substr(rest,1,i-1) }
    if (!(name in seen)) { seen[name]=1; order[++n]=name; best[name]=ref; bts[name]=ts; sc[name]=scope }
    else { sc[name]=sc[name] "," scope }
  }
  END { for (i=1;i<=n;i++) { nm=order[i]; print nm "\t" sc[nm] "\t" best[nm] "\t" bts[nm] } }')

TOTAL=0; N_ACTIVE=0; N_RECENT=0; N_INACTIVE=0; N_LOCALONLY=0; N_UNPUSHED=0
TABLE=""; DETAIL_LIST=""; DETAIL_COUNT=0

while IFS=$'\t' read -r name scope ref ts; do
  [ -z "$name" ] && continue
  TOTAL=$((TOTAL + 1))
  age=$(( (NOW - ts) / 86400 ))
  if   [ "$age" -le "$WINDOW" ]; then class="active";   N_ACTIVE=$((N_ACTIVE + 1))
  elif [ "$age" -le "$RECENT" ]; then class="recent";   N_RECENT=$((N_RECENT + 1))
  else                                class="inactive"; N_INACTIVE=$((N_INACTIVE + 1))
  fi

  behind="?"; ahead="?"
  cnt=$(g rev-list --left-right --count "$BASE...$ref" 2>/dev/null)
  if [ -n "$cnt" ]; then behind=${cnt%%[[:space:]]*}; ahead=${cnt##*[[:space:]]}; fi

  hints=""
  [ "$ahead" = "0" ] && hints="$hints INTEGRATED"
  case "$scope" in
    local) hints="$hints LOCAL_ONLY"; N_LOCALONLY=$((N_LOCALONLY + 1)) ;;
    *local*remote*|*remote*local*)
      rname=$(echo "$scope" | tr ',' '\n' | grep '^remote:' | head -n 1 | cut -d: -f2)
      sync=$(g rev-list --left-right --count "refs/heads/$name...refs/remotes/$rname/$name" 2>/dev/null)
      if [ -n "$sync" ]; then
        unpushed=${sync%%[[:space:]]*}; unpulled=${sync##*[[:space:]]}
        [ "$unpushed" != "0" ] && { hints="$hints UNPUSHED:$unpushed"; N_UNPUSHED=$((N_UNPUSHED + 1)); }
        [ "$unpulled" != "0" ] && hints="$hints BEHIND_REMOTE:$unpulled"
      fi ;;
  esac
  if [ "$ahead" != "?" ] && [ "$ahead" != "0" ]; then
    [ "$age" -gt "$STALE_DAYS" ] && hints="$hints STALE_${STALE_DAYS}D"
    [ "$behind" -ge "$FAR_BEHIND" ] && hints="$hints FAR_BEHIND_BASE"
  fi

  [ "$name" = "$BASE_SHORT" ] && hints=" BASE_BRANCH"

  if [ "$TOTAL" -le "$MAXT" ]; then
    TABLE+="$(printf '%-8s %-38s %-22s %s  %4sd  +%s/-%s %s' \
      "$class" "$name" "$scope" "$(fmt_ts "$ts")" "$age" "$ahead" "$behind" "$hints")"$'\n'
  fi

  if [ "$class" != "inactive" ] && [ "$name" != "$BASE_SHORT" ] && [ "$DETAIL_COUNT" -lt "$MAXB" ]; then
    DETAIL_LIST+="$name"$'\t'"$scope"$'\t'"$ref"$'\t'"$ts"$'\t'"$ahead"$'\t'"$behind"$'\t'"$class"$'\t'"$hints"$'\n'
    DETAIL_COUNT=$((DETAIL_COUNT + 1))
  fi
done <<< "$INV"

# ---------- print: header ----------
echo "# GIT BRANCH REPORT"
echo "repo:          $TOP"
echo "generated:     $(date '+%Y-%m-%d %H:%M %Z')"
echo "current:       $CURRENT"
echo "base:          $BASE ($BASE_HOW)"
echo "windows:       active <= ${WINDOW}d, recent <= ${RECENT}d"
echo "last fetch:    $LASTFETCH${FETCH_NOTE:+ | $FETCH_NOTE}"
[ -n "$AUTHOR" ] && echo "author filter: $AUTHOR (applies to commit lists only)"
echo "remotes:       $(g remote -v | awk '{print $1" "$2}' | sort -u | tr '\n' ';')"
if [ "$LASTFETCH" != "${LASTFETCH#unknown}" ] || [ "$FETCH" = 0 ]; then
  echo "WARNING:       remote branches reflect the last fetch, not the live remote."
fi

echo
echo "## SUMMARY"
echo "branches: $TOTAL (active: $N_ACTIVE, recent: $N_RECENT, inactive: $N_INACTIVE)"
echo "local-only: $N_LOCALONLY | with unpushed commits: $N_UNPUSHED"

echo
echo "## BASE BRANCH RECENT ACTIVITY ($BASE)"
g log "$BASE" -n "$MAXC" --date=short --format='  %h %ad %an: %s' 2>/dev/null | cut -c1-200

echo
echo "## ALL BRANCHES (newest first; columns: class name scope last-commit age +ahead/-behind hints)"
printf '%s' "$TABLE"
[ "$TOTAL" -gt "$MAXT" ] && echo "... $((TOTAL - MAXT)) older branches not shown"

# ---------- print: detail ----------
echo
echo "## DETAIL: ACTIVE AND RECENT BRANCHES (max $MAXB)"
AARGS=()
[ -n "$AUTHOR" ] && AARGS=(--author="$AUTHOR")

while IFS=$'\t' read -r name scope ref ts ahead behind class hints; do
  [ -z "$name" ] && continue

  if [ -n "$AUTHOR" ]; then
    mine=$(g log "$ref" "${AARGS[@]}" --since="$WINDOW days ago" -n 1 --format=%h 2>/dev/null)
    [ -z "$mine" ] && continue
  fi

  echo
  echo "### $name  [$class]"
  echo "scope: $scope | tip: $ref"
  echo "last commit: $(g log -1 --date=short --format='%h %ad (%ar) %an: %s' "$ref" | cut -c1-200)"
  echo "vs base: +$ahead ahead / -$behind behind |${hints:- no flags}"

  if [ "$ahead" = "0" ]; then
    echo "commits (branch fully contained in base; last 3):"
    g log "$ref" -n 3 --no-merges "${AARGS[@]}" --date=short --format='  %h %ad %an: %s' | cut -c1-200
  else
    echo "commits unique to branch (base..branch, no merges, max $MAXC):"
    g log "$BASE..$ref" --no-merges -n "$MAXC" "${AARGS[@]}" --date=short --format='  %h %ad %an: %s' 2>/dev/null | cut -c1-200
    stat_line=$(g diff --shortstat "$BASE...$ref" 2>/dev/null)
    echo "net change vs merge-base:${stat_line:- n/a}"
    areas=$(g diff --numstat "$BASE...$ref" 2>/dev/null | awk -F'\t' '
      { n=split($3,p,"/"); d=(n>2)? p[1] "/" p[2] : ((n>1)? p[1] : "(root)")
        files[d]++; if ($1!="-") { ins[d]+=$1; del[d]+=$2 } }
      END { for (d in files) printf "%d\t%s\t+%d/-%d\n", files[d], d, ins[d], del[d] }' |
      sort -rn | head -n 5 | awk -F'\t' '{ printf "  %s: %s files (%s)\n", $2, $1, $3 }')
    [ -n "$areas" ] && { echo "top areas touched:"; echo "$areas"; }
  fi
done <<< "$DETAIL_LIST"

# ---------- print: working tree ----------
echo
echo "## WORKING TREE (current branch: $CURRENT)"
dirty=$(g status --porcelain 2>/dev/null)
if [ -z "$dirty" ]; then
  echo "clean"
else
  echo "$(echo "$dirty" | wc -l | tr -d ' ') changed/untracked paths (first 15):"
  echo "$dirty" | head -n 15 | sed 's/^/  /'
fi

echo
echo "## STASHES"
st=$(g stash list --format='  %gd (%cr): %gs' 2>/dev/null)
[ -z "$st" ] && echo "none" || echo "$st" | cut -c1-200

echo
echo "## WORKTREES"
g worktree list 2>/dev/null | sed 's/^/  /'

echo
echo "## NOTES"
echo "- ahead/behind are computed against $BASE. INTEGRATED means ahead = 0 (all commits reachable from base)."
echo "- Squash-merged or rebase-merged branches cannot be detected by ancestry and may look un-integrated."
echo "- Dates are committer dates; age is measured from the branch tip."