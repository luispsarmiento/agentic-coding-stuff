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
import json
import os
import re
import shutil
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

    # our own flag; not understood by the sync engine
    harness_ignore = "local"
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
    p.add_argument("-n", "--dry-run", action="store_true", help="show what would be done")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["--help"]

    if argv[0] == "sync":
        return cmd_sync(argv[1:])

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
