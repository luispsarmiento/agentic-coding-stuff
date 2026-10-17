#!/usr/bin/env python3
"""Generate agent files for several coding tools from one source file,
and decide (flag, saved choice or prompt) whether git should track them."""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# path/global          = agent file template (repo-relative / home-relative)
# scripts_dir/_global  = where scripts declared in frontmatter are copied
TARGETS = {
    "claude":      {"path": ".claude/agents/{name}.md",
                    "global": ".claude/agents/{name}.md",
                    "scripts_dir": ".claude/scripts",
                    "scripts_global": ".claude/scripts",
                    "extra": {}},
    "copilot":     {"path": ".github/agents/{name}.agent.md",
                    "global": ".copilot/agents/{name}.agent.md",
                    "scripts_dir": ".github/scripts",
                    "scripts_global": ".copilot/scripts",
                    "extra": {}},
    "opencode":    {"path": ".opencode/agents/{name}.md",
                    "global": ".config/opencode/agents/{name}.md",
                    "scripts_dir": ".opencode/scripts",
                    "scripts_global": ".config/opencode/scripts",
                    "extra": {"mode": "subagent"}},
}

# Skill bundles (Skill.md + assets) materialized per tool. `dir`/`global` are the
# skill folder; assets travel with the bundle. Antigravity reads .agents/skills
# natively, so at workspace scope the canonical location already is the target.
SKILL_TARGETS = {
    "claude":      {"dir": ".claude/skills/{name}",        "global": ".claude/skills/{name}"},
    "copilot":     {"dir": ".github/skills/{name}",        "global": ".copilot/skills/{name}"},
    "opencode":    {"dir": ".opencode/skills/{name}",      "global": ".config/opencode/skills/{name}"},
    "antigravity": {"dir": ".agents/skills/{name}",        "global": ".gemini/config/skills/{name}"},
}

ALL_TARGETS = list(dict.fromkeys([*TARGETS, *SKILL_TARGETS]))

# AGENTS.md (canonical .agents/AGENTS.md) -> per-tool instruction file. Only
# files this tool fully owns are written (project scope; documented global ones).
INSTRUCTION_TARGETS = {
    "claude":      {"path": "CLAUDE.md",                       "global": ".claude/CLAUDE.md"},
    "copilot":     {"path": ".github/copilot-instructions.md", "global": ".copilot/copilot-instructions.md"},
    "opencode":    {"path": "AGENTS.md",                       "global": None},
    "antigravity": {"path": "AGENTS.md",                       "global": None},
}

# mcp.json ({"mcpServers": {...}}) -> per-tool MCP config, only for targets that
# use a dedicated file with the same schema. OpenCode (mcp key inside
# opencode.json, different schema) and Claude global (~/.claude.json) are skipped.
MCP_TARGETS = {
    "claude":      {"path": ".mcp.json",               "global": None},
    "copilot":     {"path": ".mcp.json",               "global": ".copilot/mcp-config.json"},
    "opencode":    {"path": None,                      "global": None},
    "antigravity": {"path": ".agents/mcp_config.json", "global": ".gemini/config/mcp_config.json"},
}

# Frontmatter keys each target understands for an agent. Anything else is dropped
# (with a warning) so a Claude-shaped key cannot make another tool's agent invalid.
# opencode intentionally omits tools/model: it needs a tools object and a
# provider/model value, which we do not emit yet.
FRONTMATTER_KEYS = {
    "claude":   {"name", "description", "tools", "model", "color"},
    "copilot":  {"name", "description", "tools", "model", "target",
                 "argument-hint", "handoffs", "infer", "user-invocable",
                 "disable-model-invocation"},
    "opencode": {"name", "description", "mode", "temperature", "permission",
                 "color", "steps", "variant", "disable", "hidden"},
}

BEGIN = "# >>> agents-sync (generated files) >>>"
END = "# <<< agents-sync (generated files) <<<"
TOOL_BEGIN = "# >>> agents-sync (harness tool folder) >>>"
TOOL_END = "# <<< agents-sync (harness tool folder) <<<"
CONFIG_NAME = ".sync.json"
LOCK_NAME = ".lock.json"
STATE_FILES = {CONFIG_NAME, LOCK_NAME}


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
            elif prefix in ALL_TARGETS:
                continue          # belongs to another target
            else:
                out[key] = value  # unknown prefix, keep as-is
        else:
            out.setdefault(key, value)
    for k, v in TARGETS[target]["extra"].items():
        out.setdefault(k, v)
    out.pop("scripts", None)      # generator metadata, not an agent field
    allowed = FRONTMATTER_KEYS.get(target)
    if allowed is not None:
        dropped = [k for k in out if k not in allowed]
        for k in dropped:
            print(f"[{target}] WARNING: dropping field '{k}' "
                  f"(not supported by this target)")
        out = {k: v for k, v in out.items() if k in allowed}
    return out


def dropped_fields(meta: dict, target: str):
    """Keys build_meta would drop for a target (for doctor/inspection)."""
    allowed = FRONTMATTER_KEYS.get(target)
    if allowed is None:
        return []
    tmp = {}
    for key, value in meta.items():
        if "." in key:
            prefix, real_key = key.split(".", 1)
            if prefix == target:
                tmp[real_key] = value
            elif prefix in ALL_TARGETS:
                continue
            else:
                tmp[key] = value
        else:
            tmp.setdefault(key, value)
    for k, v in TARGETS[target]["extra"].items():
        tmp.setdefault(k, v)
    tmp.pop("scripts", None)
    return [k for k in tmp if k not in allowed]


def parse_scripts(value: str):
    return [s for s in re.split(r"[,\s]+", (value or "").strip()) if s]


def effective_scripts(meta: dict, target: str):
    """'<target>.scripts' overrides the shared 'scripts' key."""
    shared = specific = None
    for key, value in meta.items():
        if key == "scripts":
            shared = value
        elif key.endswith(".scripts") and key.rsplit(".", 1)[0] == target:
            specific = value
    return parse_scripts(specific if specific is not None else shared)


def declared_scripts(meta: dict):
    """Union of every 'scripts' / '<target>.scripts' value (order preserved)."""
    names = []
    for key, value in meta.items():
        if key == "scripts" or (
                key.endswith(".scripts") and key.rsplit(".", 1)[0] in ALL_TARGETS):
            names += parse_scripts(value)
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


class Agent:
    """One source agent: its id, its agent.md path and where its scripts live."""

    def __init__(self, id: str, path: Path, scripts_dir: Path, source_label: str):
        self.id = id
        self.path = path
        self.scripts_dir = scripts_dir      # bundle scripts/ (canonical mode)
        self.source_label = source_label    # shown in the GENERATED header


def discover_agents(src_root: Path, scripts_src: Path):
    """Canonical <src>/agents/<id>/agent.md, or legacy flat <src>/*.md."""
    canonical = src_root / "agents"
    agents = []
    if canonical.is_dir():
        for d in sorted(canonical.iterdir()):
            agent_md = d / "agent.md"
            if d.is_dir() and agent_md.is_file():
                label = f"{src_root.as_posix()}/agents/{d.name}/agent.md"
                agents.append(Agent(d.name, agent_md, d / "scripts", label))
        return agents
    for f in sorted(src_root.glob("*.md")):
        if f.name in ("AGENTS.md", "agents.md"):
            continue                        # instructions, not an agent
        agents.append(Agent(f.stem, f, scripts_src, f"{src_root.as_posix()}/{f.name}"))
    return agents


class Skill:
    """One canonical skill bundle: id and its folder (<src>/skills/<id>/)."""

    def __init__(self, id: str, dir: Path, source_label: str):
        self.id = id
        self.dir = dir
        self.source_label = source_label


def discover_skills(src_root: Path):
    """Canonical <src>/skills/<id>/SKILL.md bundles."""
    skills_dir = src_root / "skills"
    skills = []
    if skills_dir.is_dir():
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and (d / "SKILL.md").is_file():
                skills.append(Skill(d.name, d, f"{src_root.as_posix()}/skills/{d.name}/SKILL.md"))
    return skills


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


def set_tool_ignore(root: Path, scope: str, entry, dry: bool) -> bool:
    """Add/remove the harness tool folder in its own managed block.

    `entry` is a repo-relative folder like 'harness' (a '/harness/' line is
    written) or None to remove the block.
    """
    f = exclude_file(root, scope)
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    m = re.search(rf"^{re.escape(TOOL_BEGIN)}\n(.*?)^{re.escape(TOOL_END)}\n?", text, re.S | re.M)
    if entry:
        block = f"{TOOL_BEGIN}\n/{entry.strip('/')}/\n{TOOL_END}\n"
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
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(new, encoding="utf-8")
    return True


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


def save_config(src_dir: Path, **updates):
    cfg = load_config(src_dir)
    cfg.update({k: v for k, v in updates.items() if v is not None})
    (src_dir / CONFIG_NAME).write_text(
        json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Lock / drift / doctor
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_path(src_root: Path) -> Path:
    return src_root / LOCK_NAME


def load_lock(src_root: Path) -> dict:
    try:
        return json.loads(lock_path(src_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def lock_base(lock: dict):
    where = lock.get("where", "project")
    if where == "global":
        return Path.home()
    out = Path(lock.get("out", ".")).expanduser()
    if where == "root":
        root = git_root(out)
        return root if root else out.resolve()
    return out.resolve()


def write_lock(src_root, where, out_root, repo_root, targets, agents, entries,
               skills=None, source=None, ref=None, path=None):
    if where == "global":
        base = Path.home()
    elif where == "root":
        base = repo_root or Path(out_root).expanduser()
    else:
        base = Path(out_root).expanduser()
    base = base.resolve()

    files = []
    for e in entries:
        p = e["path"].resolve()
        try:
            rel = p.relative_to(base).as_posix()
        except ValueError:
            rel = p.as_posix()
        files.append({"path": rel, "sha256": sha256_file(p) if p.exists() else None,
                      "target": e["target"], "kind": e["kind"]})
    lock = {
        "schema": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat(),
        "where": where,
        "out": str(out_root),
        "targets": list(targets),
        "agents": list(agents),
        "skills": list(skills or []),
        "files": sorted(files, key=lambda f: f["path"]),
    }
    prev = load_lock(src_root)
    for k, v in (("source", source), ("ref", ref), ("path", path)):
        if v is not None:
            lock[k] = v
        elif k in prev:
            lock[k] = prev[k]
    lock_path(src_root).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def set_lock_provenance(src_root, source, ref, path):
    lock = load_lock(src_root)
    if not lock:
        return
    lock["source"] = source
    lock["ref"] = ref
    lock["path"] = path
    lock_path(src_root).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def file_state(path: Path, expected: str) -> str:
    if not path.exists():
        return "missing"
    return "ok" if sha256_file(path) == expected else "drift"


def lock_status(lock: dict):
    """Returns (base, rows) where rows = [(rel, target, state, abs_path)]."""
    base = lock_base(lock)
    rows = []
    for f in lock.get("files", []):
        p = Path(f["path"])
        p = p if p.is_absolute() else base / f["path"]
        rows.append((f["path"], f.get("target"), file_state(p, f.get("sha256") or ""), p))
    return base, rows


def doctor(src_root: Path, scripts_src: Path):
    """Validate the canonical source. Returns (count, issues)."""
    agents = discover_agents(src_root, scripts_src)
    skills = discover_skills(src_root)
    issues = []
    if not agents and not skills:
        issues.append(f"no agents or skills found in {src_root}")
        return 0, issues

    seen = set()
    for a in agents:
        if a.id in seen:
            issues.append(f"duplicate agent id: {a.id}")
        seen.add(a.id)
        try:
            meta, _ = parse(a.path.read_text(encoding="utf-8"), a.path)
        except SystemExit:
            issues.append(f"{a.id}: invalid or missing frontmatter ({a.path})")
            continue
        for sname in declared_scripts(meta):
            if not (a.scripts_dir / sname).is_file() and not (scripts_src / sname).is_file():
                issues.append(f"{a.id}: script not found: {sname}")
        for t in ALL_TARGETS:
            for k in dropped_fields(meta, t):
                issues.append(f"{a.id}: field '{k}' not supported by '{t}' "
                              f"(will be dropped)")

    seen_skills = set()
    for s in skills:
        if s.id in seen_skills:
            issues.append(f"duplicate skill id: {s.id}")
        seen_skills.add(s.id)
        try:
            meta, _ = parse((s.dir / "SKILL.md").read_text(encoding="utf-8"), s.dir / "SKILL.md")
        except SystemExit:
            issues.append(f"{s.id}: invalid or missing frontmatter in SKILL.md")
            continue
        for field in ("name", "description"):
            if not meta.get(field):
                issues.append(f"{s.id}: SKILL.md missing '{field}'")

    mcp = src_root / "mcp.json"
    if mcp.is_file():
        try:
            data = json.loads(mcp.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "mcpServers" not in data:
                issues.append("mcp.json: expected a top-level 'mcpServers' object")
        except ValueError as e:
            issues.append(f"mcp.json: invalid JSON ({e})")

    return len(agents) + len(skills), issues


def ask_choice(n_files: int):
    print(f"\n{n_files} generated file(s). How should git treat them?")
    print("  [t] track           commit them (teammates, CI and cloud agents get them)  <- recommended")
    print("  [l] ignore locally  .git/info/exclude (no diff in the repo, only this machine)")
    print("  [s] ignore shared   .gitignore (committed rule, nobody commits the outputs)")
    print("  [k] skip            do not touch git settings")
    choices = {"t": ("track", None), "l": ("ignore", "local"),
               "s": ("ignore", "shared"), "k": ("skip", None)}
    while True:
        try:
            a = (input("Choice [t/l/s/k] (default t): ").strip().lower() or "t")[:1]
        except (EOFError, KeyboardInterrupt):
            print("\n[git] no input; skipping git handling")
            return "skip", None
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
def parse_selection(choice: str, agents):
    """Turn 'a', '1,3', '1-3' or agent ids into a list of Agent objects."""
    if not choice or choice == "a":
        return list(agents)
    ids = [a.id for a in agents]
    picked = []
    for part in choice.replace(" ", "").split(","):
        if not part:
            continue
        if part in ids:
            picked.extend(a for a in agents if a.id == part)
        elif part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(agents):
                picked.append(agents[idx])
        elif "-" in part:
            try:
                start, end = (int(x) for x in part.split("-", 1))
            except ValueError:
                continue
            for idx in range(max(0, start - 1), min(len(agents), end)):
                picked.append(agents[idx])
    return sorted(set(picked), key=lambda a: a.id)


def select_agents(agents):
    """Interactively ask whether to sync all subagents or just some."""
    if not sys.stdin.isatty():
        print("[select] not interactive; syncing all subagents (use --agents to pick)")
        return list(agents)
    print("\nSelect subagent(s) to sync (similar to skills package):")
    print("  [a] all subagents")
    for i, a in enumerate(agents, 1):
        print(f"  [{i}] {a.id}")
    try:
        choice = input("\nEnter choice (a, 1, 1,3, 1-3 or a name) [a]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n[select] no input; syncing all subagents")
        return list(agents)
    picked = parse_selection(choice, agents)
    if not picked:
        sys.exit("error: no subagents selected")
    return picked


def dest_for(target: str, name: str, where: str, out_root: Path, repo_root):
    """Resolve the agent file path for one target at the chosen scope."""
    if where == "global":
        return Path.home() / TARGETS[target]["global"].format(name=name)
    base = repo_root if where == "root" else out_root
    return base / TARGETS[target]["path"].format(name=name)


def scripts_dir_token(target: str, name: str, where: str) -> str:
    """Text substituted for {{scripts_dir}} in the agent body."""
    key = "scripts_global" if where == "global" else "scripts_dir"
    tmpl = TARGETS[target][key].format(name=name)
    return "~/" + tmpl if where == "global" else tmpl


def scripts_dest_dir(target: str, name: str, where: str, out_root: Path, repo_root):
    """Directory where declared scripts are copied for one target."""
    if where == "global":
        return Path.home() / TARGETS[target]["scripts_global"].format(name=name)
    base = repo_root if where == "root" else out_root
    return base / TARGETS[target]["scripts_dir"].format(name=name)


def skill_base(where: str, out_root: Path, repo_root):
    if where == "global":
        return Path.home()
    return repo_root if where == "root" else out_root


def skill_dest_dir(target: str, name: str, where: str, out_root: Path, repo_root):
    """Folder where a skill bundle is materialized for one target."""
    key = "global" if where == "global" else "dir"
    return skill_base(where, out_root, repo_root) / SKILL_TARGETS[target][key].format(name=name)


def skill_scripts_token(target: str, name: str, where: str) -> str:
    """Text substituted for {{scripts_dir}} inside a skill's SKILL.md."""
    key = "global" if where == "global" else "dir"
    tmpl = SKILL_TARGETS[target][key].format(name=name) + "/scripts"
    return "~/" + tmpl if where == "global" else tmpl


def ask_where() -> str:
    print("\nWhere should the generated files go?")
    print("  [p] project  the current repo (this folder)")
    print("  [r] root     the git repository root")
    print("  [g] global   user config, shared across all projects  <- all repos")
    choices = {"p": "project", "r": "root", "g": "global"}
    while True:
        try:
            a = (input("Choice [p/r/g] (default p): ").strip().lower() or "p")[:1]
        except (EOFError, KeyboardInterrupt):
            print("\n[where] no input; using project")
            return "project"
        if a in choices:
            return choices[a]
        print("  please answer p, r or g")


def resolve_where(args, src_dir: Path):
    """Returns (where, saveable). where: project|root|global."""
    if args.where:
        return args.where, True
    saved = load_config(src_dir).get("where")
    if saved:
        return saved, False
    if args.dry_run:
        print("[where] (dry-run) would ask where to install; using project")
        return "project", False
    if not sys.stdin.isatty():
        print("[where] not interactive and no choice saved; using project")
        return "project", False
    return ask_where(), True


def load_profile(src_root: Path, name: str) -> dict:
    p = src_root / "profiles" / f"{name}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sys.exit(f"error: profile not found or invalid: {p}")


def pick(items, sel):
    """sel is None (all), ['*'] (all) or a list of ids."""
    if sel is None or "*" in sel:
        return list(items)
    wanted = set(sel)
    return [o for o in items if o.id in wanted]


# --------------------------------------------------------------------------- #
def run(argv=None):
    p = argparse.ArgumentParser(description="Sync agent definitions to multiple tools.")
    p.add_argument("-t", "--target", nargs="+", default=["all"],
                   choices=["all", *ALL_TARGETS], help="targets to generate (default: all)")
    p.add_argument("-s", "--src", default=".agents",
                   help="source root: canonical .agents/ or a legacy flat dir of *.md "
                        "(default: .agents)")
    p.add_argument("--scripts-src", default="scripts",
                   help="directory holding scripts declared in frontmatter (default: scripts)")
    p.add_argument("-o", "--out", default=".", help="output root for project scope (default: .)")
    p.add_argument("-n", "--dry-run", action="store_true", help="show what would be written")
    p.add_argument("--where", choices=["project", "root", "global"], default=None,
                   help="where to install: project (this repo), root (git root), "
                        "global (user config, all projects). Default: saved choice, else ask")
    p.add_argument("--git", choices=["ask", "track", "ignore", "skip"], default=None,
                   help="how git treats generated files. Default: use the saved choice, "
                        "else ask (interactive) or skip (non-interactive)")
    p.add_argument("--scope", choices=["local", "shared"], default=None,
                   help="with --git ignore: local=.git/info/exclude, shared=.gitignore (default: local)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--agents", nargs="+", metavar="NAME",
                       help="sync only these subagents by name (non-interactive)")
    group.add_argument("--all", action="store_true",
                       help="sync every subagent and skill without prompting")
    group.add_argument("--select", action="store_true",
                       help="force the interactive subagent picker "
                            "(default when no selection flag is given)")
    p.add_argument("--skills", nargs="+", metavar="NAME",
                   help="sync only these skills by name (non-interactive)")
    p.add_argument("--no-instructions", action="store_true",
                   help="do not write AGENTS.md as per-tool instruction files")
    p.add_argument("--no-mcp", action="store_true",
                   help="do not write mcp.json to per-tool MCP configs")
    p.add_argument("-p", "--profile", default=None,
                   help="use a named profile from <src>/profiles/<name>.json")
    args = p.parse_args(argv)

    src_root, out_root = Path(args.src), Path(args.out).expanduser()
    scripts_src = Path(args.scripts_src)
    prof = load_profile(src_root, args.profile) if args.profile else {}

    if "all" not in args.target:
        targets = args.target
    elif prof.get("targets"):
        targets = prof["targets"]
    else:
        targets = list(ALL_TARGETS)

    all_agents = discover_agents(src_root, scripts_src)
    all_skills = discover_skills(src_root)
    have_instructions = (src_root / "AGENTS.md").is_file() or (src_root / "agents.md").is_file()
    have_mcp = (src_root / "mcp.json").is_file()
    if not (all_agents or all_skills or have_instructions or have_mcp):
        sys.exit(f"error: nothing to sync in {src_root} (no agents, skills, AGENTS.md or mcp.json)")

    no_instructions = args.no_instructions or prof.get("instructions") is False
    no_mcp = args.no_mcp or prof.get("mcp") is False

    # Selection precedence: explicit CLI flags > profile > interactive default.
    cli_selection = args.all or args.agents is not None or args.skills is not None
    if args.all:
        agents, skills = all_agents, all_skills
    elif args.agents is not None:
        agents = pick(all_agents, args.agents)
        if not agents:
            sys.exit(f"error: no matching subagents found from: {', '.join(args.agents)}")
        skills = pick(all_skills, args.skills) if args.skills is not None else []
    elif args.skills is not None:
        agents = []
        skills = pick(all_skills, args.skills)
        if not skills:
            sys.exit(f"error: no matching skills found from: {', '.join(args.skills)}")
    elif not cli_selection and (prof.get("agents") is not None or prof.get("skills") is not None):
        agents = pick(all_agents, prof.get("agents"))
        skills = pick(all_skills, prof.get("skills"))
    else:
        agents = select_agents(all_agents) if all_agents else []
        skills = all_skills

    where, save_where = resolve_where(args, src_root)
    repo_root = git_root(out_root)
    if where == "root" and repo_root is None:
        print("[where] no git repository found; falling back to project scope")
        where = "project"

    tag = "(dry-run) " if args.dry_run else ""
    entries = []
    seen = set()
    for spec in agents:
        meta, body = parse(spec.path.read_text(encoding="utf-8"), spec.path)
        for t in targets:
            if t not in TARGETS:
                continue
            dest = dest_for(t, spec.id, where, out_root, repo_root)
            meta_t = build_meta(meta, t)
            fm = "\n".join(f"{k}: {v}" for k, v in meta_t.items())
            body_t = body.replace("{{scripts_dir}}", scripts_dir_token(t, spec.id, where))
            header = f"<!-- GENERATED from {spec.source_label}. Do not edit. -->\n"
            content = f"---\n{fm}\n---\n{header}{body_t}"
            print(f"[{t}] ({where}) {tag}{dest}")
            if not args.dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            entries.append({"path": dest, "target": t, "kind": "agent"})

            for sname in effective_scripts(meta, t):
                sdest = scripts_dest_dir(t, spec.id, where, out_root, repo_root) / sname
                if str(sdest) in seen:
                    continue
                seen.add(str(sdest))
                sfile = spec.scripts_dir / sname
                if not sfile.is_file():
                    sfile = scripts_src / sname      # shared fallback
                if not sfile.is_file():
                    print(f"[{t}] WARNING: script not found: {sname}")
                    continue
                print(f"[{t}] ({where}) {tag}{sdest}  <- {sfile}")
                if not args.dry_run:
                    sdest.parent.mkdir(parents=True, exist_ok=True)
                    sdest.write_bytes(sfile.read_bytes())
                    if os.name != "nt":
                        sdest.chmod(sdest.stat().st_mode | 0o111)
                entries.append({"path": sdest, "target": t, "kind": "script"})

    for spec in skills:
        for t in targets:
            if t not in SKILL_TARGETS:
                continue
            sdir = skill_dest_dir(t, spec.id, where, out_root, repo_root)
            token = skill_scripts_token(t, spec.id, where)
            for f in sorted(spec.dir.rglob("*")):
                if not f.is_file() or f.name in STATE_FILES:
                    continue
                rel = f.relative_to(spec.dir)
                dest = sdir / rel
                if str(dest) in seen:
                    continue
                seen.add(str(dest))
                try:
                    if dest.resolve() == f.resolve():
                        continue            # antigravity workspace == canonical
                except OSError:
                    pass
                data = f.read_bytes()
                if rel.as_posix() == "SKILL.md":
                    data = data.decode("utf-8").replace("{{scripts_dir}}", token).encode("utf-8")
                print(f"[{t}] ({where}) {tag}{dest}  <- {f}")
                if not args.dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    if os.name != "nt" and f.suffix == ".sh":
                        dest.chmod(dest.stat().st_mode | 0o111)
                entries.append({"path": dest, "target": t, "kind": "skill"})

    def emit(dest, data, target, kind, src_label):
        if str(dest) in seen:
            return
        seen.add(str(dest))
        print(f"[{target}] ({where}) {tag}{dest}  <- {src_label}")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(data, encoding="utf-8")
        entries.append({"path": dest, "target": target, "kind": kind})

    # AGENTS.md -> per-tool instruction files
    if not no_instructions:
        inst = src_root / "AGENTS.md"
        if not inst.is_file():
            inst = src_root / "agents.md"
        if inst.is_file():
            text = f"<!-- GENERATED from {inst.name}. Do not edit. -->\n" \
                   + inst.read_text(encoding="utf-8")
            for t in targets:
                tmpl = (INSTRUCTION_TARGETS.get(t) or {}).get(
                    "global" if where == "global" else "path")
                if tmpl:
                    emit(skill_base(where, out_root, repo_root) / tmpl,
                         text, t, "instructions", inst)

    # mcp.json -> per-tool MCP configs (dedicated, same schema)
    if not no_mcp:
        mcp = src_root / "mcp.json"
        if mcp.is_file():
            text = mcp.read_text(encoding="utf-8")
            if not text.endswith("\n"):
                text += "\n"
            for t in targets:
                tmpl = (MCP_TARGETS.get(t) or {}).get(
                    "global" if where == "global" else "path")
                if tmpl:
                    emit(skill_base(where, out_root, repo_root) / tmpl,
                         text, t, "mcp", mcp)

    generated = [e["path"] for e in entries]
    if not args.dry_run:
        write_lock(src_root, where, out_root, repo_root, targets,
                   [a.id for a in agents], entries, skills=[s.id for s in skills])

    if where == "global":
        print("[git] global scope: files live outside this repo, git untouched")
        if save_where and not args.dry_run:
            save_config(src_root, where=where)
            print(f"[where] choice saved in {src_root / CONFIG_NAME}")
        return

    if repo_root is None:
        print("[git] output folder is not inside a git repo; nothing to configure")
        return
    mode, scope, saveable = resolve_git_choice(args, src_root, len(generated))
    apply_git(mode, scope, generated, repo_root, args.dry_run)
    if not args.dry_run:
        save_config(src_root,
                    where=where if save_where else None,
                    git=mode if saveable and mode != "skip" else None,
                    scope=scope if saveable and mode != "skip" else None)
    if saveable and mode != "skip" and not args.dry_run:
        print(f"[git] choice saved in {src_root / CONFIG_NAME} (override with --git ask)")


def main():
    run()


if __name__ == "__main__":
    main()
