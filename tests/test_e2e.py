"""End-to-End (E2E) tests for the full agencos workflow.

Tests real execution through the CLI entry points (cli/agencos.cmd / agencos.py),
verifying:
1. Fresh project bootstrap and installation with selective skills & subagents.
2. In-repo project memory setup and MCP server stdio query over notes, specs, and graph.
3. Pre-existing AGENTS.md / DESIGN.md / specs/ detection and migration.
4. Custom skills & subagents import via --custom-dir.
5. Backward-compatibility of cli/harness and harness.py.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_AGENCOS = str(ROOT / "agencos.py")
CLI_HARNESS = str(ROOT / "harness.py")


class AgencosE2ETest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(prefix="agencos-e2e-")
        self.tmp = Path(self.td.name)
        self.project_dir = self.tmp / "test_workspace"
        self.project_dir.mkdir()

    def tearDown(self):
        self.td.cleanup()

    def run_cli(self, *args, use_harness=False, cwd=None):
        script = CLI_HARNESS if use_harness else CLI_AGENCOS
        cmd = [sys.executable, script, *args]
        env = dict(os.environ)
        # Ensure fresh environment without AGENT_MEMORY_ROOT pollution
        env.pop("AGENT_MEMORY_ROOT", None)
        return subprocess.run(cmd, cwd=cwd or self.project_dir, capture_output=True, text=True, env=env)

    def test_e2e_full_install_with_memory_and_mcp_query(self):
        """E2E Test 1: Full install with in-repo memory, then start MCP server and run search/query."""
        # 1. Install from this repo into a fresh test workspace with selective agents & skills
        res = self.run_cli(
            "install", str(ROOT),
            "-o", str(self.project_dir),
            "--where", "project",
            "--agents", "code-reviewer",
            "--skills", "spec-driven-development",
            "-t", "claude", "copilot", "opencode", "antigravity",
            "--with-memory",
            "--memory-root", "local",
            "--git", "skip"
        )
        self.assertEqual(res.returncode, 0, f"Install failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")

        # Check canonical workspace structure
        canon = self.project_dir / ".agents"
        self.assertTrue((canon / "agents" / "code-reviewer").is_dir())
        self.assertFalse((canon / "agents" / "git-branch-inspector").exists())
        self.assertTrue((canon / "skills" / "spec-driven-development").is_dir())
        self.assertTrue((canon / "mcp.json").is_file())

        # Check in-repo memory directory
        mem_dir = self.project_dir / ".agents" / "memories"
        profile_json = json.loads((self.project_dir / ".agent-profile.json").read_text(encoding="utf-8"))
        pid = profile_json["project_id"]
        proj_mem = mem_dir / pid
        self.assertTrue((proj_mem / "notes").is_dir())
        self.assertTrue((proj_mem / "specs").is_dir())
        self.assertTrue((proj_mem / "graph").is_dir())
        self.assertTrue((mem_dir / "server.py").is_file())

        # Check materialized tool outputs
        self.assertTrue((self.project_dir / ".claude" / "agents" / "code-reviewer.md").is_file())
        self.assertTrue((self.project_dir / ".github" / "agents" / "code-reviewer.agent.md").is_file())
        self.assertTrue((self.project_dir / "CLAUDE.md").is_file())

        # Verify agent-memory instruction block was injected into CLAUDE.md
        claude_md = (self.project_dir / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Project memory", claude_md)
        self.assertIn("memory_search", claude_md)

        # 2. Add sample content into notes, specs, and graph report
        (proj_mem / "notes" / "arch-decision.md").write_text("# Decision\nWe use SQLite for local caching.\n", encoding="utf-8")
        (proj_mem / "specs" / "feature-auth.md").write_text("# Auth Spec\nOAuth2 with PKCE flow required.\n", encoding="utf-8")
        (proj_mem / "graph" / "GRAPH_REPORT.md").write_text("# Code Graph Report\nCritical dependencies: database and auth modules.\n", encoding="utf-8")

        # 3. Spawn the materialized MCP server stdio process and query it
        server_py = mem_dir / "server.py"
        proc = subprocess.Popen(
            [sys.executable, str(server_py), "--root", str(mem_dir), "--project", pid],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=self.project_dir
        )
        try:
            def rpc(method, params=None, rid=1):
                req = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            init_res = rpc("initialize", {"protocolVersion": "2024-11-05"})
            self.assertEqual(init_res["result"]["serverInfo"]["name"], "agent-memory")

            # Search note section
            search_notes = rpc("tools/call", {"name": "memory_search", "arguments": {"query": "SQLite"}})
            text = search_notes["result"]["content"][0]["text"]
            self.assertIn("SQLite for local caching", text)
            self.assertIn("notes", text)

            # Search spec section
            search_specs = rpc("tools/call", {"name": "memory_search", "arguments": {"query": "OAuth2"}})
            text_spec = search_specs["result"]["content"][0]["text"]
            self.assertIn("OAuth2 with PKCE", text_spec)
            self.assertIn("specs", text_spec)

            # Search graph section
            search_graph = rpc("tools/call", {"name": "memory_search", "arguments": {"query": "Critical dependencies"}})
            text_graph = search_graph["result"]["content"][0]["text"]
            self.assertIn("Critical dependencies", text_graph)

            # Spec get tool
            get_spec = rpc("tools/call", {"name": "spec_get", "arguments": {"name": "feature-auth"}})
            self.assertIn("OAuth2 with PKCE", get_spec["result"]["content"][0]["text"])

        finally:
            proc.kill()
            proc.wait()

    def test_e2e_migration_and_custom_dir(self):
        """E2E Test 2: Detect existing DESIGN.md, specs/, and import user custom assets."""
        # 1. Create pre-existing DESIGN.md and specs in the target project
        (self.project_dir / "DESIGN.md").write_text("# Design Philosophy\nMinimalist and secure by default.\n", encoding="utf-8")
        existing_specs = self.project_dir / "specs"
        existing_specs.mkdir()
        (existing_specs / "billing-spec.md").write_text("# Billing Spec\nStripe webhook integration.\n", encoding="utf-8")

        # 2. Create a user-provided custom folder with custom skill
        custom_folder = self.tmp / "my_custom_assets"
        (custom_folder / "skills" / "my-custom-validator").mkdir(parents=True)
        (custom_folder / "skills" / "my-custom-validator" / "SKILL.md").write_text(
            "---\nname: my-custom-validator\ndescription: validates schema\n---\nRun validation here.\n",
            encoding="utf-8"
        )

        # 3. Run install with --migrate-specs, --import-design, and --custom-dir
        res = self.run_cli(
            "install", str(ROOT),
            "-o", str(self.project_dir),
            "--where", "project",
            "--with-memory",
            "--migrate-specs",
            "--import-design",
            "--custom-dir", str(custom_folder),
            "-t", "claude",
            "--git", "skip"
        )
        self.assertEqual(res.returncode, 0, f"Install failed:\n{res.stdout}\n{res.stderr}")

        # Verify DESIGN.md was absorbed into canonical and materialized instructions
        canon = self.project_dir / ".agents"
        self.assertTrue((canon / "DESIGN.md").is_file())
        claude_md = (self.project_dir / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Design Philosophy", claude_md)
        self.assertIn("Minimalist and secure by default.", claude_md)

        # Verify custom skill was imported
        self.assertTrue((canon / "skills" / "my-custom-validator" / "SKILL.md").is_file())
        self.assertTrue((self.project_dir / ".claude" / "skills" / "my-custom-validator" / "SKILL.md").is_file())

        # Verify existing spec was migrated to memory server
        profile_json = json.loads((self.project_dir / ".agent-profile.json").read_text(encoding="utf-8"))
        pid = profile_json["project_id"]
        # Default memory root is in user home data ~/agent-memory/<pid>/specs
        mem_root = Path.home() / "agent-memory"
        migrated_file = mem_root / pid / "specs" / "billing-spec.md"
        self.assertTrue(migrated_file.is_file(), f"Expected {migrated_file} to exist")
        self.assertIn("Stripe webhook", migrated_file.read_text(encoding="utf-8"))

    def test_e2e_harness_backward_compatibility(self):
        """E2E Test 3: Running via harness.py still works identically."""
        res = self.run_cli("doctor", use_harness=True, cwd=str(ROOT))
        self.assertEqual(res.returncode, 0)
        self.assertIn("[doctor]", res.stdout)
        self.assertIn("OK", res.stdout)


if __name__ == "__main__":
    unittest.main()
