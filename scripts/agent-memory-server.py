#!/usr/bin/env python3
"""agent-memory MCP server (stdio).

Exposes project memory stored under <root>/<project>/ (notes/, specs/, graph/)
plus an optional code graph. Stdlib only; degrades gracefully when tools are
missing.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = None
PROJECT = None


def memory_dir() -> Path:
    return Path(ROOT) / PROJECT


def project_json_path() -> Path:
    return memory_dir() / "project.json"


def load_project_meta() -> dict:
    try:
        return json.loads(project_json_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def tool_definitions() -> list:
    return [
        {
            "name": "memory_search",
            "description": "Search project memory (notes, specs, graph report) for a query string.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "graph_query",
            "description": "Query the project's code graph (graphify or CodeGraph) for a question.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "budget": {"type": "integer", "default": 2000},
                },
                "required": ["question"],
            },
        },
        {
            "name": "spec_get",
            "description": "Read a spec file from project memory by name (fuzzy match).",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
        {
            "name": "memory_save",
            "description": "Save a note/decision into project memory and return its path.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "folder": {"type": "string", "default": "notes"},
                },
                "required": ["title", "content"],
            },
        },
    ]


def do_memory_search(args: dict) -> dict:
    query = args.get("query", "")
    limit = int(args.get("limit", 10) or 10)
    if not query:
        return text_result("query is required", True)
    base = memory_dir()
    targets = []
    for sub in ("notes", "specs"):
        d = base / sub
        if d.is_dir():
            targets.append(d)
    graph_report = base / "graph" / "GRAPH_REPORT.md"
    if graph_report.is_file():
        targets.append(graph_report.parent)
    hits = []
    rx = re.compile(re.escape(query), re.IGNORECASE)
    for d in targets:
        files = [d] if d.is_file() else list(d.rglob("*"))
        for f in files:
            if not f.is_file():
                continue
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    rel = f.relative_to(base).as_posix() if f.is_relative_to(base) else str(f)
                    hits.append(f"{rel}:{i}: {line.strip()}")
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    if not hits:
        return text_result(f"No matches for {query!r}.")
    return text_result("\n".join(hits))


def do_graph_query(args: dict) -> dict:
    question = args.get("question", "")
    budget = int(args.get("budget", 2000) or 2000)
    if not question:
        return text_result("question is required", True)
    graph_dir = memory_dir() / "graph"
    graph_json = graph_dir / "graph.json"
    if graph_json.is_file():
        cmd = ["graphify", "query", question, "--graph", str(graph_json), "--budget", str(budget)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
            return text_result(out.strip() or "graphify returned no output")
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            return text_result(f"graphify failed: {e}", True)
    meta = load_project_meta()
    repo = meta.get("repo_path")
    if repo and (Path(repo) / ".codegraph").is_dir():
        try:
            r = subprocess.run(["codegraph", "explore", question], cwd=repo,
                               capture_output=True, text=True, timeout=120)
            out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
            return text_result(out.strip() or "codegraph returned no output")
        except FileNotFoundError:
            pass
        except Exception as e:  # noqa: BLE001
            return text_result(f"codegraph failed: {e}", True)
    return text_result("No code graph available. Run `harness memory sync` or `graph-init --memory`.")


def do_spec_get(args: dict) -> dict:
    name = args.get("name", "")
    if not name:
        return text_result("name is required", True)
    specs = memory_dir() / "specs"
    if not specs.is_dir():
        return text_result("No specs directory.")
    p = specs / name
    if p.is_file():
        return text_result(p.read_text(encoding="utf-8", errors="replace"))
    candidates = [f for f in specs.rglob("*") if f.is_file()]
    matches = [f for f in candidates if name.lower() in f.name.lower()]
    if not matches:
        matches = candidates
    if not matches:
        return text_result(f"Spec not found: {name}")
    if len(matches) == 1:
        return text_result(matches[0].read_text(encoding="utf-8", errors="replace"))
    listing = "\n".join(str(f.relative_to(specs)) for f in matches)
    return text_result(f"Multiple matches:\n{listing}\nUse a more specific name.")


def do_memory_save(args: dict) -> dict:
    title = (args.get("title") or "").strip()
    content = args.get("content", "")
    folder = (args.get("folder") or "notes").strip()
    if not title:
        return text_result("title is required", True)
    base = memory_dir() / folder
    base.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-").lower() or "note"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = base / f"{ts}-{slug}.md"
    path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
    return text_result(f"Saved: {path}")


DISPATCH = {
    "memory_search": do_memory_search,
    "graph_query": do_graph_query,
    "spec_get": do_spec_get,
    "memory_save": do_memory_save,
}


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    rid = req.get("id", None)
    params = req.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "agent-memory", "version": "1.0.0"},
        }
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": tool_definitions()}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = DISPATCH.get(name)
        if not fn:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"unknown tool {name}"}}
        try:
            result = fn(args)
        except Exception as e:  # noqa: BLE001
            result = text_result(f"error: {e}", True)
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    global ROOT, PROJECT
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--project", required=True)
    args = ap.parse_args()
    ROOT = args.root
    PROJECT = args.project
    try:
        (Path(ROOT) / PROJECT).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


if __name__ == "__main__":
    main()