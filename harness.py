#!/usr/bin/env python3
"""harness - manage your AI agent harness (.agents/).

Commands:
  install     Fetch a harness (GitHub tarball or a local dir), drop its canonical
              .agents/ into the project/global scope and materialize it to tools.
  update      Re-fetch the recorded source and re-materialize, with drift backup.
  uninstall   Remove the files the harness generated (and its ignore rules).
  sync        Materialize the canonical .agents/ to the configured tools.
  migrate     Convert a legacy flat source (agents-src/*.md) into .agents/.
  status      Show the lock and any drift vs the generated files.
  doctor      Validate the source (frontmatter, scripts, ids).
  profile     List available profiles (<src>/profiles/<name>.json).
  bundle      Package .agents/ into a portable .dotagents archive.

Run:  python harness.py <command> [options]
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_agents  # noqa: E402

TARGET_CHOICES = list(sync_agents.ALL_TARGETS)
STATE_NAMES = {".lock.json", ".sync.json", ".backups"}


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def has_src(argv):
    for a in argv:
        if a in ("-s", "--src") or a.startswith("--src="):
            return True
    return False


def peek_flag(argv, names, default=None):
    for i, a in enumerate(argv):
        if a in names and i + 1 < len(argv):
            return argv[i + 1]
        for n in names:
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
    return default


def is_dry(argv):
    return "-n" in argv or "--dry-run" in argv


def install_base(where, out):
    if where == "global":
        return Path.home()
    outp = Path(out).expanduser()
    if where == "root":
        root = sync_agents.git_root(outp)
        return root if root else outp.resolve()
    return outp.resolve()


def ensure_project_scaffold(base: Path):
    agents_root = base / ".agents"
    created = []
    for name in ("agents", "memories", "skills"):
        directory = agents_root / name
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / ".gitkeep"
        if not any(directory.iterdir()):
            marker.touch(exist_ok=True)
            created.append(marker)

    starter_files = {
        "agents.md": "# Project Agent Instructions\n\n"
                     "Add project-specific guidance for your coding agents here.\n",
        "mcp.json": '{\n  "mcpServers": {}\n}\n',
    }
    for name, content in starter_files.items():
        path = agents_root / name
        try:
            with path.open("x", encoding="utf-8") as starter:
                starter.write(content)
        except FileExistsError:
            continue
        created.append(path)
    return created


def scaffold_project(where, base):
    if where not in ("project", "root"):
        return
    created = ensure_project_scaffold(base)
    if created:
        print(f"[scaffold] initialized {base / '.agents'}")


def memory_root() -> Path:
    env = os.environ.get("AGENT_MEMORY_ROOT")
    if env:
        return Path(env).expanduser()
    # honor .agent-profile.json override if present in CWD
    profile = Path.cwd() / ".agent-profile.json"
    try:
        data = json.loads(profile.read_text(encoding="utf-8"))
        if data.get("memory_root"):
            return Path(data["memory_root"]).expanduser()
    except (OSError, ValueError):
        pass
    return Path.home() / "agent-memory"


def project_id_for(repo: Path) -> str:
    repo = repo.resolve()
    pid = None
    # try git remote origin
    try:
        code, out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo, capture_output=True, text=True).returncode, None
    except Exception:
        code = 1
        out = None
    if code == 0:
        try:
            r = subprocess.run(["git", "remote", "get-url", "origin"],
                               cwd=repo, capture_output=True, text=True)
            url = r.stdout.strip()
            if url:
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-").lower()
                # drop common host prefixes
                slug = slug.replace("https-github-com-", "").replace("git-github-com-", "")
                pid = slug[:60] or None
        except Exception:
            pid = None
    if not pid:
        h = hashlib.sha256(str(repo).encode("utf-8")).hexdigest()[:8]
        pid = f"{repo.name}-{h}"
    # sanitize
    pid = re.sub(r"[^a-zA-Z0-9._-]+", "-", pid).strip("-")
    return pid or f"project-{hashlib.sha256(str(repo).encode()).hexdigest()[:8]}"


def ensure_memory_layout(mem_root: Path, project_id: str) -> Path:
    base = mem_root / project_id
    for sub in ("graph", "notes", "specs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (mem_root / "_global" / "lessons").mkdir(parents=True, exist_ok=True)
    return base


def agent_profile_path(repo: Path) -> Path:
    return repo / ".agent-profile.json"


def read_agent_profile(repo: Path) -> dict:
    p = agent_profile_path(repo)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_agent_profile(repo: Path, project_id: str, mem_root: Path) -> Path:
    p = agent_profile_path(repo)
    data = {
        "schema": 1,
        "project_id": project_id,
        "memory_root": None,
    }
    # store override only if non-default? keep null for default
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


def project_json_path(mem_base: Path) -> Path:
    return mem_base / "project.json"


def write_project_json(mem_base: Path, repo: Path) -> Path:
    p = project_json_path(mem_base)
    data = {
        "repo_path": str(repo.resolve()),
        "created_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
    }
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return p


MANAGED_BEGIN = "<!-- >>> agent-memory (managed) >>> -->"
MANAGED_END = "<!-- <<< agent-memory (managed) <<< -->"


def append_managed_block(agents_md: Path):
    block = (
        MANAGED_BEGIN + "\n"
        "## Project memory (user data)\n"
        "- Before changing code, planning or knowledge gathering, search memory with the `memory` MCP tools "
        "(`memory_search`, `graph_query`) for relevant decisions, lessons, and structure.\n"
        "- After a non-trivial decision or lesson, save it with `memory_save` "
        "(or write to `~/agent-memory/<project-id>/notes/`).\n"
        "- If the memory server is unavailable, continue normally; memory is advisory.\n"
        "- Specs live in `~/agent-memory/<project-id>/specs/` unless committed to the repo for teammates/CI.\n"
        "- Don't create memory files in the project directory; use the designated memory locations.\n"
        + MANAGED_END + "\n"
    )
    text = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
    if MANAGED_BEGIN in text:
        # replace existing block
        import re as _re
        pattern = _re.compile(re.escape(MANAGED_BEGIN) + r".*?" + re.escape(MANAGED_END) + r"\n?", _re.S)
        new = pattern.sub(block, text)
        if new == text:
            return False
        agents_md.write_text(new, encoding="utf-8")
        return True
    sep = "" if not text or text.endswith("\n") else "\n"
    agents_md.write_text(text + sep + "\n" + block, encoding="utf-8")
    return True


def add_memory_mcp_entry(canon: Path, mem_root: Path, project_id: str):
    mcp_path = canon / "mcp.json"
    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8")) if mcp_path.is_file() else {"mcpServers": {}}
    except (OSError, ValueError):
        data = {"mcpServers": {}}
    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}
    server_py = mem_root / "server.py"
    data["mcpServers"]["memory"] = {
        "command": "python",
        "args": [str(server_py), "--root", str(mem_root), "--project", project_id],
    }
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return mcp_path

def parse_source(source):
    s = source.rstrip("/")
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", s)
    if m:
        return ("github", m.group(1), m.group(2))
    m = re.match(r"^([\w.-]+)/([\w.-]+?)(?:\.git)?$", s)
    if m:
        return ("github", m.group(1), m.group(2))
    p = Path(s).expanduser()
    if p.is_file():
        return ("archive", str(p), None)
    if p.exists():
        return ("local", str(p), None)
    raise SystemExit(f"error: cannot parse source: {source}")


def extract_tar(tar: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:               # Python < 3.12
            tf.extractall(dest)
    return dest


def fetch_source(kind, a, b, ref, workdir):
    if kind == "local":
        return Path(a)
    if kind == "archive":
        ex = extract_tar(Path(a), workdir / "extract")
        roots = [p for p in ex.iterdir() if p.is_dir()]
        if len(roots) == 1 and roots[0].name != ".agents":
            return roots[0]
        return ex
    owner, repo = a, b
    ref = ref or "HEAD"
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    print(f"[install] fetching {url}")
    tar = workdir / "src.tar.gz"
    try:
        with urllib.request.urlopen(url) as r, open(tar, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"error: download failed: {e}")
    ex = extract_tar(tar, workdir / "extract")
    roots = [p for p in ex.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else ex


def copy_tree(src: Path, dst: Path):
    n = 0
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(src)
        if rel.parts and rel.parts[0] in STATE_NAMES:
            continue                        # never copy machine-local state
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(f.read_bytes())
        if os.name != "nt" and f.suffix == ".sh":
            out.chmod(out.stat().st_mode | 0o111)
        n += 1
    return n


def clear_canonical(dest_canon: Path):
    """Drop the managed canonical dirs so a fetch fully replaces them."""
    for sub in ("agents", "skills"):
        d = dest_canon / sub
        if d.exists():
            shutil.rmtree(d)


def tool_rel_to(base: Path):
    try:
        rel = ROOT.relative_to(base)
    except ValueError:
        return None
    if str(rel) in ("", "."):
        return None
    return rel.as_posix()


def handle_tool_ignore(where, out, mode, dry):
    """Keep the harness tool folder out of git (default) or trackable."""
    if where == "global":
        return
    base = install_base(where, out)
    if not (base / ".git").exists():
        return
    if mode == "track":
        changed = (sync_agents.set_tool_ignore(base, "local", None, dry)
                   or sync_agents.set_tool_ignore(base, "shared", None, dry))
        if changed:
            print("[git] harness tool folder is now trackable (removed the ignore entry)")
        return
    rel = tool_rel_to(base)
    if rel is None:
        return
    scope = "shared" if mode == "shared" else "local"
    sync_agents.set_tool_ignore(base, scope, rel, dry)
    shown = ".gitignore" if scope == "shared" else ".git/info/exclude"
    print(f"[git] '{rel}/' added to {shown} ({scope}) so it does not dirty the project.")
    print("      to version it instead:  python harness.py sync --harness-ignore track")


def sync_argv(canon: Path, args, agents=True):
    argv = ["-s", str(canon), "--where", args.where or "project", "-o", args.out]
    if getattr(args, "target", None):
        argv += ["-t", *args.target]
    if getattr(args, "profile", None):
        argv += ["--profile", args.profile]
    if agents and getattr(args, "agents", None):
        argv += ["--agents", *args.agents]
    elif getattr(args, "skills", None) and not getattr(args, "agents", None):
        argv += ["--skills", *args.skills]
    else:
        argv += ["--all"]
    if getattr(args, "skills", None) and getattr(args, "agents", None):
        argv += ["--skills", *args.skills]
    if getattr(args, "git", None):
        argv += ["--git", args.git]
    if getattr(args, "scope", None):
        argv += ["--scope", args.scope]
    if getattr(args, "no_instructions", False):
        argv += ["--no-instructions"]
    if getattr(args, "no_mcp", False):
        argv += ["--no-mcp"]
    if getattr(args, "dry_run", False):
        argv += ["-n"]
    return argv


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_sync(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]

    # our own flags; not understood by the sync engine
    harness_ignore = "local"
    with_memory = False
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--harness-ignore" and i + 1 < len(argv):
            harness_ignore = argv[i + 1]
            i += 2
            continue
        if a.startswith("--harness-ignore="):
            harness_ignore = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--with-memory":
            with_memory = True
            i += 1
            continue
        rest.append(a)
        i += 1
    argv = rest

    # default source is the tool's own canonical dir, not the CWD
    if not has_src(argv):
        tool_agents = ROOT / ".agents"
        if tool_agents.is_dir():
            argv = ["-s", str(tool_agents), *argv]

    src = Path(peek_flag(argv, ["-s", "--src"], str(ROOT / ".agents")))
    rc = sync_agents.run(argv)
    lock = sync_agents.load_lock(src)
    if not is_dry(argv):
        scaffold_project(lock.get("where"), install_base(lock.get("where"), lock.get("out", ".")))
    if lock.get("where") in ("project", "root") and not is_dry(argv):
        handle_tool_ignore(lock["where"], lock.get("out", "."), harness_ignore, False)
        base = install_base(lock["where"], lock.get("out", "."))
        print("[hint] Optional: store this project's graph/notes in user data: "
              "run `harness memory init` (or re-run sync with --with-memory). "
              "The graph-init subagent is also available for in-repo graphs.")
        if with_memory:
            memory_init(base, None, False, False, True, False, False, False)
    return rc


def cmd_install(args):
    kind, a, b = parse_source(args.source)
    where = args.where or "project"
    base = install_base(where, args.out)
    print(f"[install] source: {args.source}  ref: {args.ref or 'HEAD'}  "
          f"-> {where} ({base})")

    with tempfile.TemporaryDirectory(prefix="harness-src-") as td:
        root = fetch_source(kind, a, b, args.ref, Path(td))
        canon = root / args.path
        if not canon.is_dir():
            sys.exit(f"error: '{args.path}' not found in {args.source}")
        dest_canon = base / ".agents"
        clear_canonical(dest_canon)
        n = copy_tree(canon, dest_canon)
        print(f"[install] {n} canonical file(s) -> {dest_canon}")

    rc = sync_agents.run(sync_argv(dest_canon, args))
    if not args.dry_run:
        scaffold_project(where, base)
        sync_agents.set_lock_provenance(dest_canon, args.source, args.ref, args.path)
        handle_tool_ignore(where, args.out, args.harness_ignore, False)
        if where in ("project", "root"):
            print("[hint] Optional: store this project's graph/notes in user data: "
                  "run `harness memory init` (or re-run install with --with-memory). "
                  "The graph-init subagent is also available for in-repo graphs.")
            if getattr(args, "with_memory", False):
                memory_init(base, None, False, getattr(args, "no_mcp", False),
                            True, False, False, False)
    return rc


def cmd_update(args):
    src = Path(args.src)
    old = sync_agents.load_lock(src)
    if not old:
        sys.exit(f"error: no lock at {sync_agents.lock_path(src)} (nothing to update)")
    source = old.get("source")
    if not source:
        sys.exit("error: lock has no source; install with: harness install <source>")

    ref = args.ref or old.get("ref")
    path = old.get("path", ".agents")
    where = args.where or old.get("where", "project")
    out = args.out or old.get("out", ".")
    base = install_base(where, out)
    canon = base / ".agents"

    if not args.dry_run:
        _, rows = sync_agents.lock_status(old)
        drifted = [(rel, p) for rel, t, state, p in rows if state == "drift"]
        if drifted:
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            bdir = src / ".backups" / ts
            for rel, p in drifted:
                dest = bdir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(p.read_bytes())
            print(f"[update] backed up {len(drifted)} edited file(s) -> {bdir}")
            for rel, _ in drifted:
                print(f"  [edited] {rel}")

    kind, a, b = parse_source(source)
    with tempfile.TemporaryDirectory(prefix="harness-src-") as td:
        root = fetch_source(kind, a, b, ref, Path(td))
        src_canon = root / path
        if not src_canon.is_dir():
            sys.exit(f"error: '{path}' not found in {source}")
        clear_canonical(canon)
        copy_tree(src_canon, canon)

    rc = sync_agents.run(sync_argv(canon, args))
    if not args.dry_run:
        scaffold_project(where, base)
        sync_agents.set_lock_provenance(canon, source, ref, path)
        new = sync_agents.load_lock(canon)
        oldset = {sync_agents.lock_base(old) / f["path"] for f in old.get("files", [])}
        newset = {sync_agents.lock_base(new) / f["path"] for f in new.get("files", [])}
        removed = [p for p in oldset - newset if p.exists()]
        for p in removed:
            p.unlink()
            print(f"[update] pruned {p}")
        handle_tool_ignore(where, out, args.harness_ignore, False)
        if where in ("project", "root"):
            print("[hint] Optional: store this project's graph/notes in user data: "
                  "run `harness memory init` (or re-run with --with-memory).")
            if getattr(args, "with_memory", False):
                memory_init(base, None, False, getattr(args, "no_mcp", False),
                            True, False, False, False)
    return rc


def cmd_uninstall(args):
    src = Path(args.src)
    lock = sync_agents.load_lock(src)
    if not lock:
        sys.exit(f"error: no lock at {sync_agents.lock_path(src)} (nothing to uninstall)")
    base = sync_agents.lock_base(lock)

    removed = kept = 0
    for f in lock.get("files", []):
        p = Path(f["path"])
        p = p if p.is_absolute() else base / f["path"]
        if not p.exists():
            continue
        state = sync_agents.file_state(p, f.get("sha256") or "")
        if state == "drift" and not args.force:
            print(f"[uninstall] kept (edited locally, use --force): {f['path']}")
            kept += 1
            continue
        if not args.dry_run:
            p.unlink()
        print(f"[uninstall] removed {f['path']}")
        removed += 1
    print(f"[uninstall] {removed} removed, {kept} kept")

    if not args.dry_run:
        for scope in ("local", "shared"):
            sync_agents.set_tool_ignore(base, scope, None, False)
        if args.purge:
            shutil.rmtree(src, ignore_errors=True)
            print(f"[uninstall] purged canonical: {src}")
        else:
            sync_agents.lock_path(src).unlink(missing_ok=True)
            print(f"[uninstall] removed lock; canonical kept at {src} (--purge to delete)")
    return 0


def cmd_status(args):
    src = Path(args.src)
    lock = sync_agents.load_lock(src)
    if not lock:
        print(f"no lock at {sync_agents.lock_path(src)}; run: harness sync")
        return 1
    base, rows = sync_agents.lock_status(lock)
    drift = [r for r in rows if r[2] != "ok"]
    print(f"lock:      {sync_agents.lock_path(src)}")
    if lock.get("source"):
        print(f"source:    {lock['source']} @ {lock.get('ref') or 'HEAD'} ({lock.get('path', '.agents')})")
    print(f"generated: {lock.get('generated_at')}")
    print(f"where:     {lock.get('where')} (base: {base})")
    print(f"targets:   {', '.join(lock.get('targets', []))}")
    print(f"agents:    {len(lock.get('agents', []))}  skills: {len(lock.get('skills', []))}")
    print(f"files:     {len(rows)}  (drift/missing: {len(drift)})")
    for rel, target, state, _ in drift:
        label = "edited" if state == "drift" else state
        print(f"  [{label}] {rel}  ({target})")
    return 1 if drift else 0


def cmd_doctor(args):
    count, issues = sync_agents.doctor(Path(args.src), Path(args.scripts_src))
    print(f"[doctor] {count} item(s) checked in {args.src}")
    for i in issues:
        print(f"  ISSUE: {i}")
    print("[doctor] " + ("OK" if not issues else f"{len(issues)} issue(s)"))
    return 1 if issues else 0


def cmd_migrate(args):
    src = Path(args.src)
    dest = Path(args.dest)
    scripts_src = Path(args.scripts_src)
    files = sorted(src.glob("*.md"))
    if not files:
        sys.exit(f"error: no *.md in {src}")

    dest_agents = dest / "agents"
    moved = 0
    missing = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        meta, _ = sync_agents.parse(text, f)
        adir = dest_agents / f.stem
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "agent.md").write_text(text, encoding="utf-8")

        names = sync_agents.declared_scripts(meta)
        for name in names:
            sfile = scripts_src / name
            if not sfile.is_file():
                missing.append(name)
                print(f"[migrate] WARNING: script not found: {sfile}")
                continue
            sdir = adir / "scripts"
            sdir.mkdir(exist_ok=True)
            sdest = sdir / name
            sdest.write_bytes(sfile.read_bytes())
            if os.name != "nt":
                sdest.chmod(sdest.stat().st_mode | 0o111)
            moved += 1
        print(f"[migrate] {f} -> {adir / 'agent.md'}"
              + (f" (+{len(names)} script(s))" if names else ""))

    print(f"\n[migrate] {len(files)} agent(s) written under {dest_agents}, "
          f"{moved} script(s) bundled")
    if missing:
        print("[migrate] missing scripts (add them to the bundle manually): "
              + ", ".join(sorted(set(missing))))
    if args.remove_source:
        shutil.rmtree(src)
        print(f"[migrate] removed source: {src}")
    else:
        print(f"[migrate] kept source: {src} (re-run with --remove-source to delete)")
    return 0


# --------------------------------------------------------------------------- #
def cmd_bundle(args):
    src = Path(args.src)
    if not src.is_dir():
        sys.exit(f"error: {src} not found")
    name = args.name or ROOT.name
    version = args.version or "0.0.0"
    out = Path(args.out) if args.out else Path(f"{name}-{version}.dotagents")
    meta = {
        "schema": 1, "name": name, "version": version,
        "description": args.description or "",
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat(),
        "path": ".agents",
    }
    with tempfile.TemporaryDirectory(prefix="harness-bundle-") as td:
        tdp = Path(td)
        shutil.copytree(src, tdp / ".agents", ignore=shutil.ignore_patterns(*STATE_NAMES))
        (tdp / "bundle.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        with tarfile.open(out, "w:gz") as tf:
            tf.add(tdp / ".agents", arcname=".agents")
            tf.add(tdp / "bundle.json", arcname="bundle.json")
    print(f"[bundle] wrote {out}  ({name} {version})")
    return 0


def cmd_profile(args):
    pdir = Path(args.src) / "profiles"
    if not pdir.is_dir():
        print("no profiles")
        return 0
    for f in sorted(pdir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            print(f"  {f.stem}: INVALID JSON")
            continue
        print(f"  {f.stem}: targets={d.get('targets', 'all')} "
              f"agents={d.get('agents', 'all')} skills={d.get('skills', 'all')} "
              f"instructions={d.get('instructions', True)} mcp={d.get('mcp', True)}")
    return 0


# --------------------------------------------------------------------------- #
def add_materialize_args(p, include_ref=False, include_source=False):
    if include_source:
        p.add_argument("source", help="owner/repo, GitHub URL or a local directory")
    if include_ref:
        p.add_argument("--ref", default=None, help="git ref: tag, branch or sha (default: HEAD)")
    p.add_argument("--path", default=".agents", help="canonical subpath in the source (default: .agents)")
    p.add_argument("-s", "--src", default=".agents", help="local canonical root (default: .agents)")
    p.add_argument("-o", "--out", default=".", help="project output root (default: .)")
    p.add_argument("--where", choices=["project", "root", "global"], default=None,
                   help="install scope (default: project)")
    p.add_argument("-t", "--target", nargs="+", choices=TARGET_CHOICES, default=None,
                   help="tools to materialize (default: all)")
    p.add_argument("--agents", nargs="+", metavar="NAME", default=None,
                   help="only these subagents (default: all)")
    p.add_argument("--skills", nargs="+", metavar="NAME", default=None,
                   help="only these skills (default: all)")
    p.add_argument("-p", "--profile", default=None,
                   help="use a named profile from <src>/profiles/<name>.json")
    p.add_argument("--git", choices=["ask", "track", "ignore", "skip"], default=None,
                   help="how git treats the generated files")
    p.add_argument("--scope", choices=["local", "shared"], default=None,
                   help="with --git ignore: local=.git/info/exclude, shared=.gitignore")
    p.add_argument("--harness-ignore", choices=["local", "shared", "track"], default="local",
                   help="keep the harness tool folder out of git (default: local). "
                        "'track' makes it versionable")
    p.add_argument("--no-instructions", action="store_true",
                   help="do not write AGENTS.md as per-tool instruction files")
    p.add_argument("--no-mcp", action="store_true",
                   help="do not write mcp.json to per-tool MCP configs")
    p.add_argument("--with-memory", action="store_true",
                   help="also set up project memory in user data (~/agent-memory)")
    p.add_argument("-n", "--dry-run", action="store_true", help="show what would be done")
    return p


def resolve_repo(args):
    out = getattr(args, "out", None) or "."
    where = getattr(args, "where", None) or "project"
    base = install_base(where, out)
    if where in ("project", "root"):
        return base
    return Path.cwd()


def memory_init(repo: Path, mem_root_override=None, no_graph=False, no_mcp=False,
               do_sync=True, dry=False, relocate_codegraph=False, full_graph=False):
    repo = repo.resolve()
    # ensure canonical workspace exists
    scaffold_project("project", repo)
    profile = read_agent_profile(repo)
    project_id = profile.get("project_id")
    if not project_id:
        project_id = project_id_for(repo)
    mem_root = Path(mem_root_override).expanduser() if mem_root_override else memory_root()
    if dry:
        print(f"[memory] (dry-run) project_id={project_id} root={mem_root}")
        return project_id
    # layout
    mem_base = ensure_memory_layout(mem_root, project_id)
    write_project_json(mem_base, repo)
    write_agent_profile(repo, project_id, mem_root)
    # copy server
    src_server = ROOT / "scripts" / "agent-memory-server.py"
    dst_server = mem_root / "server.py"
    if src_server.is_file():
        dst_server.write_bytes(src_server.read_bytes())
        if os.name != "nt":
            dst_server.chmod(dst_server.stat().st_mode | 0o111)
        print(f"[memory] server -> {dst_server}")
    # AGENTS.md managed block
    agents_md = repo / ".agents" / "AGENTS.md"
    if not agents_md.is_file():
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text("# Project Agent Instructions\n\n", encoding="utf-8")
    changed = append_managed_block(agents_md)
    print(f"[memory] AGENTS.md managed block {'updated' if changed else 'already present'}")
    # mcp entry
    canon = repo / ".agents"
    if not no_mcp:
        add_memory_mcp_entry(canon, mem_root, project_id)
        print(f"[memory] mcp entry -> {canon / 'mcp.json'}")
    # graph build
    if not no_graph:
        graph_dir = mem_base / "graph"
        # graphify
        import shutil as _sh
        if _sh.which("graphify"):
            env = dict(os.environ)
            env["GRAPHIFY_OUT"] = str(graph_dir)
            cmd = ["graphify", "extract", str(repo), "--code-only", "--out", str(graph_dir)]
            if full_graph:
                cmd = ["graphify", "extract", str(repo), "--out", str(graph_dir)]
            print(f"[memory] running: {' '.join(cmd)}")
            try:
                subprocess.run(cmd, env=env, check=False)
            except Exception as e:
                print(f"[memory] graphify failed: {e}")
        else:
            print("[memory] graphify not installed; run manually:")
            print(f"  GRAPHIFY_OUT={graph_dir} graphify extract {repo} --code-only --out {graph_dir}")
        # codegraph (in-repo, ignored) + optional symlink
        if _sh.which("codegraph"):
            print(f"[memory] running codegraph init in {repo}")
            try:
                subprocess.run(["codegraph", "init", str(repo)], check=False)
            except Exception as e:
                print(f"[memory] codegraph failed: {e}")
            if relocate_codegraph:
                cg = repo / ".codegraph"
                target = graph_dir / "codegraph"
                if cg.exists() and not cg.is_symlink():
                    try:
                        import shutil as _s
                        if target.exists():
                            _s.rmtree(target, ignore_errors=True)
                        _s.move(str(cg), str(target))
                        try:
                            os.symlink(str(target), str(cg), target_is_directory=True)
                            print(f"[memory] relocated .codegraph -> {target}")
                        except OSError as e:
                            print(f"[memory] symlink failed ({e}); .codegraph moved to {target}, restore manually if needed")
                    except Exception as e:
                        print(f"[memory] codegraph relocation failed: {e}")
        else:
            print("[memory] codegraph not installed; skip")
    # sync to propagate
    if do_sync:
        try:
            argv = ["-s", str(canon), "--where", "project", "-o", str(repo), "--all"]
            # avoid interactive prompts
            import sync_agents as _sa
            # call run with saved choices? Just run; sync_agents resolves where from config
            _sa.run(argv)
        except Exception as e:
            print(f"[memory] sync failed: {e}")
    print(f"[memory] done. project_id={project_id} memory={mem_base}")
    print(f"[memory] backup tip: create a private git repo in {mem_root}")
    return project_id


def cmd_memory(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("usage: harness memory <init|sync|status|hook|backup> [options]")
        return 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "init":
        ap = argparse.ArgumentParser(prog="harness memory init")
        ap.add_argument("--root", default=None, help="override memory root")
        ap.add_argument("--project-id", default=None, help="override project id")
        ap.add_argument("--repo", default=".", help="repo root (default .)")
        ap.add_argument("--no-graph", action="store_true")
        ap.add_argument("--no-mcp", action="store_true")
        ap.add_argument("--no-sync", action="store_true")
        ap.add_argument("--full-graph", action="store_true", help="run full graphify extraction (needs model)")
        ap.add_argument("--relocate-codegraph", action="store_true")
        ap.add_argument("-n", "--dry-run", action="store_true")
        a = ap.parse_args(rest)
        repo = Path(a.repo).resolve()
        # honor explicit project id
        if a.project_id:
            prof = read_agent_profile(repo)
            prof["project_id"] = a.project_id
            agent_profile_path(repo).write_text(json.dumps({**prof, "schema": 1,
                "project_id": a.project_id, "memory_root": None}, indent=2) + "\n", encoding="utf-8")
        memory_init(repo, a.root, a.no_graph, a.no_mcp, not a.no_sync, a.dry_run,
                    a.relocate_codegraph, a.full_graph)
        return 0
    if sub in ("sync", "reindex"):
        ap = argparse.ArgumentParser(prog="harness memory sync")
        ap.add_argument("--root", default=None)
        ap.add_argument("--repo", default=".")
        ap.add_argument("--quiet", action="store_true")
        a = ap.parse_args(rest)
        repo = Path(a.repo).resolve()
        profile = read_agent_profile(repo)
        pid = profile.get("project_id") or project_id_for(repo)
        mem_root = Path(a.root).expanduser() if a.root else memory_root()
        mem_base = mem_root / pid
        if not a.quiet:
            print(f"[memory] syncing {pid}")
        import shutil as _sh
        graph_dir = mem_base / "graph"
        if _sh.which("graphify") and graph_dir.parent.is_dir():
            env = dict(os.environ)
            env["GRAPHIFY_OUT"] = str(graph_dir)
            try:
                subprocess.run(["graphify", "update", str(repo)], env=env, check=False,
                               stdout=subprocess.DEVNULL if a.quiet else None)
            except Exception as e:
                if not a.quiet:
                    print(f"[memory] graphify update failed: {e}")
        cg = repo / ".codegraph"
        if cg.is_dir() and _sh.which("codegraph"):
            try:
                subprocess.run(["codegraph", "sync", str(repo)], check=False,
                               stdout=subprocess.DEVNULL if a.quiet else None)
            except Exception as e:
                if not a.quiet:
                    print(f"[memory] codegraph sync failed: {e}")
        if not a.quiet:
            print("[memory] sync done")
        return 0
    if sub == "status":
        ap = argparse.ArgumentParser(prog="harness memory status")
        ap.add_argument("--repo", default=".")
        a = ap.parse_args(rest)
        repo = Path(a.repo).resolve()
        profile = read_agent_profile(repo)
        pid = profile.get("project_id")
        mr = memory_root()
        print(f"repo:        {repo}")
        print(f"project_id:  {pid or '(none)'}")
        print(f"memory_root: {mr}")
        if pid:
            base = mr / pid
            print(f"memory_dir:  {base}")
            print(f"  graph.json: {'yes' if (base/'graph'/'graph.json').is_file() else 'no'}")
            print(f"  notes:      {len(list((base/'notes').glob('*'))) if (base/'notes').is_dir() else 0}")
            print(f"  specs:      {len(list((base/'specs').glob('*'))) if (base/'specs').is_dir() else 0}")
            print(f"  server.py:  {'yes' if (mr/'server.py').is_file() else 'no'}")
        print(f".codegraph:   {'yes' if (repo/'.codegraph').is_dir() else 'no'}")
        return 0
    if sub == "hook":
        if not rest or rest[0] not in ("install", "uninstall"):
            print("usage: harness memory hook install|uninstall")
            return 2
        repo = Path(".").resolve()
        # find git root
        try:
            r = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, text=True)
            gitdir = Path(r.stdout.strip())
            if not gitdir.is_absolute():
                gitdir = repo / gitdir
        except Exception:
            gitdir = None
        if not gitdir or not gitdir.exists():
            print("[memory] not a git repo; hook skipped")
            return 1
        hooks = gitdir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = hooks / "post-commit"
        marker = "# >>> agent-memory sync >>>"
        end = "# <<< agent-memory sync <<<"
        block = (marker + "\n"
                 "harness memory sync --quiet || true\n"
                 + end + "\n")
        if rest[0] == "install":
            text = hook.read_text(encoding="utf-8") if hook.is_file() else "#!/bin/sh\n"
            if marker in text:
                print("[memory] hook already installed")
                return 0
            if not text.endswith("\n"):
                text += "\n"
            text += block
            hook.write_text(text, encoding="utf-8")
            if os.name != "nt":
                hook.chmod(hook.stat().st_mode | 0o111)
            print(f"[memory] installed post-commit hook: {hook}")
            return 0
        else:
            if not hook.is_file():
                print("[memory] no hook file")
                return 0
            text = hook.read_text(encoding="utf-8")
            import re as _re
            text = _re.sub(re.escape(marker) + r".*?" + re.escape(end) + r"\n?", "", text, flags=_re.S)
            hook.write_text(text, encoding="utf-8")
            print(f"[memory] removed agent-memory block from {hook}")
            return 0
    if sub == "backup":
        ap = argparse.ArgumentParser(prog="harness memory backup")
        ap.add_argument("--repo", default=".")
        a = ap.parse_args(rest)
        mem = memory_root()
        mem.mkdir(parents=True, exist_ok=True)
        gitdir = mem / ".git"
        if not gitdir.exists():
            subprocess.run(["git", "init"], cwd=mem, check=False)
            print(f"[memory] initialized git repo in {mem}")
        # write a minimal .gitignore? none needed
        subprocess.run(["git", "add", "-A"], cwd=mem, check=False)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=mem)
        if r.returncode != 0:
            subprocess.run(["git", "commit", "-m", "backup agent-memory"], cwd=mem, check=False)
            print("[memory] committed backup")
        else:
            print("[memory] nothing to commit")
        print("[memory] add a private remote for off-machine backup:")
        print(f"  cd {mem} && git remote add origin <private-repo-url> && git push -u origin main")
        return 0
    print(f"unknown memory subcommand: {sub}")
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["--help"]

    if argv[0] == "sync":
        return cmd_sync(argv[1:])
    if argv[0] == "memory":
        return cmd_memory(argv[1:])

    p = argparse.ArgumentParser(prog="harness",
                                description="Manage your .agents/ harness.")
    sub = p.add_subparsers(dest="command", required=True)

    add_materialize_args(sub.add_parser("install",
                                        help="fetch a harness and materialize it"),
                         include_ref=True, include_source=True).set_defaults(func=cmd_install)

    up = add_materialize_args(sub.add_parser("update",
                                             help="re-fetch the source and re-materialize"))
    up.add_argument("--ref", default=None, help="override the ref (default: from lock)")
    up.set_defaults(func=cmd_update)

    un = sub.add_parser("uninstall", help="remove generated files and ignore rules")
    un.add_argument("-s", "--src", default=".agents", help="canonical root (default: .agents)")
    un.add_argument("--force", action="store_true", help="also remove locally edited files")
    un.add_argument("--purge", action="store_true", help="also delete the canonical .agents/")
    un.add_argument("-n", "--dry-run", action="store_true", help="show what would be removed")
    un.set_defaults(func=cmd_uninstall)

    sub.add_parser("sync",
                   help="materialize .agents/ to the configured tools "
                        "(args are forwarded to sync, e.g. harness sync --all)")

    st = sub.add_parser("status", help="show the lock and drift vs generated files")
    st.add_argument("-s", "--src", default=".agents", help="canonical root (default: .agents)")
    st.set_defaults(func=cmd_status)

    dr = sub.add_parser("doctor", help="validate the harness (frontmatter, scripts, ids)")
    dr.add_argument("-s", "--src", default=".agents", help="canonical root (default: .agents)")
    dr.add_argument("--scripts-src", default="scripts",
                    help="shared scripts fallback (default: scripts)")
    dr.set_defaults(func=cmd_doctor)

    pf = sub.add_parser("profile", help="list available profiles")
    pf.add_argument("-s", "--src", default=".agents", help="canonical root (default: .agents)")
    pf.set_defaults(func=cmd_profile)

    bn = sub.add_parser("bundle", help="package .agents/ into a .dotagents archive")
    bn.add_argument("-s", "--src", default=".agents", help="canonical root (default: .agents)")
    bn.add_argument("-o", "--out", default=None,
                    help="output file (default: <name>-<version>.dotagents)")
    bn.add_argument("--name", default=None, help="bundle name (default: repo folder name)")
    bn.add_argument("--version", default=None, help="bundle version (default: 0.0.0)")
    bn.add_argument("--description", default=None, help="bundle description")
    bn.set_defaults(func=cmd_bundle)

    mg = sub.add_parser("migrate",
                        help="convert a legacy flat source into .agents/agents/<id>/agent.md")
    mg.add_argument("--src", default="agents-src", help="legacy source dir (default: agents-src)")
    mg.add_argument("--dest", default=".agents", help="canonical root (default: .agents)")
    mg.add_argument("--scripts-src", default="scripts",
                    help="where declared scripts live (default: scripts)")
    mg.add_argument("--remove-source", action="store_true",
                    help="delete the legacy source dir after migrating")
    mg.set_defaults(func=cmd_migrate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
