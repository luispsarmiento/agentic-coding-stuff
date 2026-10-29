import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import harness


class ProjectScaffoldTests(unittest.TestCase):
    def test_scaffold_is_created_once_and_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            agents_root = project / ".agents"
            agents_root.mkdir()
            instructions = agents_root / "agents.md"
            instructions.write_text("custom instructions\n", encoding="utf-8")
            mcp_config = agents_root / "mcp.json"
            mcp_config.write_text('{"mcpServers":{"custom":{}}}\n', encoding="utf-8")

            created = harness.ensure_project_scaffold(project)
            second_pass = harness.ensure_project_scaffold(project)

            self.assertTrue((agents_root / "agents").is_dir())
            self.assertTrue((agents_root / "memories").is_dir())
            self.assertTrue((agents_root / "skills").is_dir())
            self.assertTrue((agents_root / "agents" / ".gitkeep").is_file())
            self.assertEqual(instructions.read_text(encoding="utf-8"), "custom instructions\n")
            self.assertEqual(json.loads(mcp_config.read_text(encoding="utf-8")),
                             {"mcpServers": {"custom": {}}})
            self.assertGreater(len(created), 0)
            self.assertEqual(second_pass, [])

    def test_sync_scaffolds_project_scope_but_not_global_or_dry_run(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            project_source = Path(temporary_directory) / "source"
            project_source.mkdir()
            project_lock = {"where": "project", "out": str(project)}

            with patch.object(harness.sync_agents, "run", return_value=None), \
                    patch.object(harness.sync_agents, "load_lock", return_value=project_lock), \
                    patch.object(harness, "handle_tool_ignore"):
                harness.cmd_sync(["--where", "project", "-o", str(project), "--all"])

            self.assertTrue((project / ".agents" / "memories").is_dir())

            global_project = project / "global"
            global_project.mkdir()
            global_lock = {"where": "global", "out": str(global_project)}
            with patch.object(harness.sync_agents, "run", return_value=None), \
                    patch.object(harness.sync_agents, "load_lock", return_value=global_lock):
                harness.cmd_sync(["--where", "global", "-o", str(global_project), "--all"])
            self.assertFalse((global_project / ".agents").exists())

            dry_project = project / "dry"
            dry_project.mkdir()
            with patch.object(harness.sync_agents, "run", return_value=None), \
                    patch.object(harness.sync_agents, "load_lock", return_value=project_lock):
                harness.cmd_sync(["--where", "project", "-o", str(dry_project), "--all", "-n"])
            self.assertFalse((dry_project / ".agents").exists())


if __name__ == "__main__":
    unittest.main()