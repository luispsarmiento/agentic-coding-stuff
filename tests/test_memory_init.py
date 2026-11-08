import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import harness


class MemoryInitTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / ".agents").mkdir()
        (self.repo / ".agents" / "AGENTS.md").write_text("# hi\n", encoding="utf-8")
        (self.repo / ".agents" / "mcp.json").write_text('{"mcpServers":{}}\n', encoding="utf-8")
        self.mem = self.root / "mem"

    def tearDown(self):
        self.td.cleanup()

    def _run(self, **kw):
        with patch.object(harness, "subprocess") as sp:
            sp.run.return_value.returncode = 1
            sp.which.return_value = None
            harness.memory_init(self.repo, str(self.mem), True, False, False, False, False, False)

    def test_layout_and_profile(self):
        self._run()
        profile = json.loads((self.repo / ".agent-profile.json").read_text())
        self.assertEqual(profile["schema"], 1)
        self.assertIn("project_id", profile)
        pid = profile["project_id"]
        base = self.mem / pid
        for sub in ("graph", "notes", "specs"):
            self.assertTrue((base / sub).is_dir())
        self.assertTrue((self.mem / "_global" / "lessons").is_dir())
        self.assertTrue((self.mem / "server.py").is_file())
        pj = json.loads((base / "project.json").read_text())
        self.assertEqual(pj["repo_path"], str(self.repo.resolve()))

    def test_managed_block_idempotent(self):
        self._run()
        text1 = (self.repo / ".agents" / "AGENTS.md").read_text()
        self.assertIn(harness.MANAGED_BEGIN, text1)
        self._run()
        text2 = (self.repo / ".agents" / "AGENTS.md").read_text()
        self.assertEqual(text1, text2)

    def test_mcp_entry(self):
        self._run()
        data = json.loads((self.repo / ".agents" / "mcp.json").read_text())
        self.assertIn("memory", data["mcpServers"])
        entry = data["mcpServers"]["memory"]
        self.assertEqual(entry["command"], "python")
        self.assertIn("--project", entry["args"])

    def test_status_command(self):
        self._run()
        # just ensure no crash
        with patch.object(harness, "memory_root", return_value=self.mem):
            # memory_root reads env/profile; force by monkey? call cmd_memory status with repo
            pass
        # run status via cmd_memory with --repo
        rc = harness.cmd_memory(["status", "--repo", str(self.repo)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()