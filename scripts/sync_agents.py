#!/usr/bin/env python3
"""Generate agent files for several coding tools from one source file,
and decide (flag, saved choice or prompt) whether git should track them."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TARGETS = {
    "claude":      {"path": ".claude/agents/{name}.md",        "extra": {}},
    "copilot":     {"path": ".github/agents/{name}.agent.md",  "extra": {}},
    "opencode":    {"path": ".opencode/agents/{name}.md",      "extra": {"mode": "subagent"}},
    # Skill-style fallback; skills only need name + description
    "antigravity": {"path": ".agents/skills/{name}/SKILL.md",  "extra": {}, "keep": {"name", "description"}},
}

BEGIN = "# >>> agents-sync (generated files) >>>"
END = "# <<< agents-sync (generated files) <<<"
CONFIG_NAME = ".sync.json"


# --------------------------------------------------------------------------- #
# Source parsing / generation
# --------------------------------------------------------------------------- #
def parse(text: str, file: Path):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        sys.exit(f"error: {file} has no YAML frontmatter")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def build_meta(meta: dict, target: str) -> dict:
    """Shared keys + keys prefixed with '<target>.' (e.g. claude.tools)."""
    out = {}
    for key, value in meta.items():
        if "." in key:
            prefix, real_key = key.split(".", 1)
            if prefix == target:
                out[real_key] = value
            elif prefix in TARGETS:
                continue          # belongs to another target
            else:
                out[key] = value  # unknown prefix, keep as-is
        else:
            out.setdefault(key, value)
    for k, v in TARGETS[target]["extra"].items():
        out.setdefault(k, v)
    keep = TARGETS[target].get("keep")
    if keep:
        out = {k: v for k, v in out.items() if k in keep}
    return out


# --------------------------------------------------------------------------- #
# Git handling
# --------------------------------------------------------------------------- #
def git(args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        return 127, ""
    return r.returncode, r.stdout.strip()


def nearest_existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def git_root(out_root: Path):
    code, out = git(["rev-parse", "--show-toplevel"], nearest_existing(out_root))
    return Path(out).resolve() if code == 0 and out else None


def exclude_file(root: Path, scope: str) -> Path:
    if scope == "shared":
        return root / ".gitignore"
    code, out = git(["rev-parse", "--git-path", "info/exclude"], root)
    p = Path(out) if code == 0 and out else root / ".git" / "info" / "exclude"
    return p if p.is_absolute() else root / p


def split_block(text: str):
    m = re.search(rf"^{re.escape(BEGIN)}\n(.*?)^{re.escape(END)}\n?", text, re.S | re.M)
    entries = [l for l in m.group(1).splitlines() if l.strip()] if m else []
    return m, entries


def update_block(path: Path, entries, dry: bool) -> bool:
    """Create/replace the managed block with `entries`; remove it if empty."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    m, _ = split_block(text)
    if entries:
        block = BEGIN + "\n" + "\n".join(sorted(entries)) + "\n" + END + "\n"
        if m:
            new = text[:m.start()] + block + text[m.end():]
        else:
            sep = "" if not text or text.endswith("\n") else "\n"
            new = text + sep + block
    else:
        if not m:
            return False
        new = text[:m.start()] + text[m.end():]
    if new == text:
        return False
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return True


def load_config(src_dir: Path) -> dict:
    p = src_dir / CONFIG_NAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(src_dir: Path, mode: str, scope: str):
    (src_dir / CONFIG_NAME).write_text(
        json.dumps({"git": mode, "scope": scope}, indent=2) + "\n", encoding="utf-8")


def ask_choice(n_files: int):
    print(f"\n{n_files} generated file(s). How should git treat them?")
    print("  [t] track           commit them (teammates, CI and cloud agents get them)  <- recommended")
    print("  [l] ignore locally  .git/info/exclude (no diff in the repo, only this machine)")
    print("  [s] ignore shared   .gitignore (committed rule, nobody commits the outputs)")
    print("  [k] skip            do not touch git settings")
    choices = {"t": ("track", None), "l": ("ignore", "local"),
               "s": ("ignore", "shared"), "k": ("skip", None)}
    while True:
        a = (input("Choice [t/l/s/k] (default t): ").strip().lower() or "t")[:1]
        if a in choices:
            return choices[a]
        print("  please answer t, l, s or k")


def resolve_git_choice(args, src_dir: Path, n_files: int):
    """Returns (mode, scope, saveable). mode: track|ignore|skip."""
    cfg = load_config(src_dir)
    scope = args.scope or cfg.get("scope") or "local"
    if args.git == "ask" or (args.git is None and not cfg.get("git")):
        if args.dry_run:
            print("[git] (dry-run) would ask how git should treat the generated files")
            return "skip", scope, False
        if not sys.stdin.isatty():
            print("[git] not interactive and no choice saved; skipping git handling "
                  "(use --git track|ignore)")
            return "skip", scope, False
        mode, asked_scope = ask_choice(n_files)
        return mode, (asked_scope or scope), True
    if args.git:
        return args.git, scope, True
    return cfg["git"], scope, False


def apply_git(mode: str, scope: str, generated, root: Path, dry: bool):
    tag = "(dry-run) " if dry else ""
    rels = ["/" + d.resolve().relative_to(root).as_posix() for d in generated]
    local_f, shared_f = exclude_file(root, "local"), exclude_file(root, "shared")

    if mode == "skip":
        print("[git] skipped; git settings untouched")
        return

    if mode == "track":
        changed = [update_block(f, [], dry) for f in (local_f, shared_f)]
        print(f"[git] {tag}tracking generated files"
              + (" (removed old ignore block)" if any(changed) else ""))
        print("      remember to `git add` them so teammates and cloud agents see them")
        return

    # mode == "ignore": exact file paths only, never whole directories, so
    # hand-written agents in the same folders stay visible to git.
    chosen, other = (local_f, shared_f) if scope == "local" else (shared_f, local_f)
    existing = []
    if chosen.exists():
        _, existing = split_block(chosen.read_text(encoding="utf-8"))
    entries = sorted(set(existing) | set(rels))
    changed = update_block(chosen, entries, dry)
    update_block(other, [], dry)   # avoid a stale block in the other file
    shown = chosen.relative_to(root).as_posix() if chosen.is_relative_to(root) else str(chosen)
    print(f"[git] {tag}ignoring {len(rels)} generated file(s) via {shown} ({scope})"
          + ("" if changed else " - already up to date"))

    code, out = git(["ls-files", "--", *[r.lstrip("/") for r in rels]], root)
    if code == 0 and out:
        print("[git] WARNING: these are already tracked; ignore rules do not untrack them:")
        for line in out.splitlines():
            print(f"        {line}")
        print("      to stop tracking (not run): git rm --cached <file>")


# --------------------------------------------------------------------------- #
def parse_selection(choice: str, all_files):
    """Turn 'a', '1,3', '1-3' or agent names into a list of source files."""
    if not choice or choice == "a":
        return list(all_files)
    stems = [f.stem for f in all_files]
    picked = []
    for part in choice.replace(" ", "").split(","):
        if not part:
            continue
        if part in stems:
            picked.extend(f for f in all_files if f.stem == part)
        elif part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(all_files):
                picked.append(all_files[idx])
        elif "-" in part:
            try:
                start, end = (int(x) for x in part.split("-", 1))
            except ValueError:
                continue
            for idx in range(max(0, start - 1), min(len(all_files), end)):
                picked.append(all_files[idx])
    return sorted(set(picked))


def select_agents(all_files):
    """Interactively ask whether to sync all subagents or just some."""
    if not sys.stdin.isatty():
        print("[select] not interactive; syncing all subagents (use --agents to pick)")
        return list(all_files)
    print("\nSelect subagent(s) to sync (similar to skills package):")
    print("  [a] all subagents")
    for i, f in enumerate(all_files, 1):
        print(f"  [{i}] {f.stem}")
    try:
        choice = input("\nEnter choice (a, 1, 1,3, 1-3 or a name) [a]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n[select] no input; syncing all subagents")
        return list(all_files)
    files = parse_selection(choice, all_files)
    if not files:
        sys.exit("error: no subagents selected")
    return files


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Sync agent definitions to multiple tools.")
    p.add_argument("-t", "--target", nargs="+", default=["all"],
                   choices=["all", *TARGETS], help="targets to generate (default: all)")
    p.add_argument("-s", "--src", default="agents-src", help="source directory")
    p.add_argument("-o", "--out", default=".", help="output root (project root, or ~ for user-level)")
    p.add_argument("-n", "--dry-run", action="store_true", help="show what would be written")
    p.add_argument("--git", choices=["ask", "track", "ignore", "skip"], default=None,
                   help="how git treats generated files. Default: use the saved choice, "
                        "else ask (interactive) or skip (non-interactive)")
    p.add_argument("--scope", choices=["local", "shared"], default=None,
                   help="with --git ignore: local=.git/info/exclude, shared=.gitignore (default: local)")
    pick = p.add_mutually_exclusive_group()
    pick.add_argument("--agents", nargs="+", metavar="NAME",
                      help="sync only these subagents by name (non-interactive)")
    pick.add_argument("--all", action="store_true",
                      help="sync every subagent without prompting")
    pick.add_argument("--select", action="store_true",
                      help="force the interactive subagent picker "
                           "(default when no selection flag is given)")
    args = p.parse_args()

    targets = list(TARGETS) if "all" in args.target else args.target
    src_dir, out_root = Path(args.src), Path(args.out).expanduser()
    all_files = sorted(src_dir.glob("*.md"))
    if not all_files:
        sys.exit(f"error: no .md files in {src_dir}")

    # Subagent selection: interactive by default, --all/--agents for scripts.
    if args.agents:
        selected = set(args.agents)
        files = [f for f in all_files if f.stem in selected]
        if not files:
            sys.exit(f"error: no matching subagents found from: {', '.join(args.agents)}")
    elif args.all:
        files = all_files
    else:
        files = select_agents(all_files)

    generated = []
    for src in files:
        meta, body = parse(src.read_text(encoding="utf-8"), src)
        for t in targets:
            dest = out_root / TARGETS[t]["path"].format(name=src.stem)
            fm = "\n".join(f"{k}: {v}" for k, v in build_meta(meta, t).items())
            header = f"<!-- GENERATED from agents-src/{src.name}. Do not edit. -->\n"
            content = f"---\n{fm}\n---\n{header}{body}"
            print(f"[{t}] {'(dry-run) ' if args.dry_run else ''}{dest}")
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            generated.append(dest)

    root = git_root(out_root)
    if root is None:
        print("[git] output folder is not inside a git repo; nothing to configure")
        return
    mode, scope, saveable = resolve_git_choice(args, src_dir, len(generated))
    apply_git(mode, scope, generated, root, args.dry_run)
    if saveable and mode != "skip" and not args.dry_run:
        save_config(src_dir, mode, scope)
        print(f"[git] choice saved in {src_dir / CONFIG_NAME} (override with --git ask)")


if __name__ == "__main__":
    main()
