import json
import shutil
import tempfile
import unittest
from pathlib import Path

import agencos


class AgencosCliTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.repo = self.root / "myproject"
        self.repo.mkdir()

        # Create a mock source harness with 2 agents and 2 skills
        self.src = self.root / "src_harness"
        (self.src / "agents" / "agent-a").mkdir(parents=True)
        (self.src / "agents" / "agent-a" / "agent.md").write_text(
            "---\nname: agent-a\ndescription: agent A\n---\nHello A\n", encoding="utf-8"
        )
        (self.src / "agents" / "agent-b").mkdir(parents=True)
        (self.src / "agents" / "agent-b" / "agent.md").write_text(
            "---\nname: agent-b\ndescription: agent B\n---\nHello B\n", encoding="utf-8"
        )

        (self.src / "skills" / "skill-1").mkdir(parents=True)
        (self.src / "skills" / "skill-1" / "SKILL.md").write_text(
            "---\nname: skill-1\ndescription: skill 1\n---\nSkill 1 content\n", encoding="utf-8"
        )
        (self.src / "skills" / "skill-2").mkdir(parents=True)
        (self.src / "skills" / "skill-2" / "SKILL.md").write_text(
            "---\nname: skill-2\ndescription: skill 2\n---\nSkill 2 content\n", encoding="utf-8"
        )

    def tearDown(self):
        self.td.cleanup()

    def test_install_selective_agents_and_skills(self):
        """Test that install with --agents and --skills only installs the selected items."""
        args = [
            "install",
            str(self.src),
            "-o", str(self.repo),
            "--where", "project",
            "--agents", "agent-a",
            "--skills", "skill-2",
            "-t", "claude",
            "--git", "skip",
        ]
        rc = agencos.main(args)
        self.assertEqual(rc, 0)

        # In destination canonical .agents/
        dest_canon = self.repo / ".agents"
        self.assertTrue((dest_canon / "agents" / "agent-a").is_dir())
        self.assertFalse((dest_canon / "agents" / "agent-b").exists())
        self.assertTrue((dest_canon / "skills" / "skill-2").is_dir())
        self.assertFalse((dest_canon / "skills" / "skill-1").exists())

        # In materialized claude files
        self.assertTrue((self.repo / ".claude" / "agents" / "agent-a.md").is_file())
        self.assertFalse((self.repo / ".claude" / "agents" / "agent-b.md").exists())
        self.assertTrue((self.repo / ".claude" / "skills" / "skill-2" / "SKILL.md").is_file())
        self.assertFalse((self.repo / ".claude" / "skills" / "skill-1").exists())

    def test_install_custom_dir(self):
        """Test importing custom skills and agents via --custom-dir."""
        custom = self.root / "custom_stuff"
        (custom / "skills" / "custom-skill").mkdir(parents=True)
        (custom / "skills" / "custom-skill" / "SKILL.md").write_text(
            "---\nname: custom-skill\ndescription: custom\n---\nCustom\n", encoding="utf-8"
        )

        args = [
            "install",
            str(self.src),
            "-o", str(self.repo),
            "--where", "project",
            "--custom-dir", str(custom),
            "-t", "claude",
            "--git", "skip",
        ]
        rc = agencos.main(args)
        self.assertEqual(rc, 0)

        dest_canon = self.repo / ".agents"
        self.assertTrue((dest_canon / "skills" / "custom-skill").is_dir())
        self.assertTrue((self.repo / ".claude" / "skills" / "custom-skill" / "SKILL.md").is_file())

    def test_detect_and_import_design_and_agents_md(self):
        """Test that pre-existing DESIGN.md and AGENTS.md are detected and incorporated."""
        (self.repo / "DESIGN.md").write_text("# My Design Principles\nAlways be concise.\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("# Custom Agents Info\nSpecial rule.\n", encoding="utf-8")

        args = [
            "install",
            str(self.src),
            "-o", str(self.repo),
            "--where", "project",
            "--import-instructions",
            "--import-design",
            "-t", "claude",
            "--git", "skip",
        ]
        rc = agencos.main(args)
        self.assertEqual(rc, 0)

        dest_canon = self.repo / ".agents"
        self.assertTrue((dest_canon / "DESIGN.md").is_file())
        self.assertTrue((dest_canon / "AGENTS.md").is_file())

        claude_md = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Special rule.", claude_md)
        self.assertIn("Always be concise.", claude_md)

    def test_migrate_specs_to_memory(self):
        """Test migrating pre-existing project specs/ to memory server."""
        project_specs = self.repo / "specs"
        project_specs.mkdir(parents=True)
        (project_specs / "feature1.md").write_text("# Feature 1\nDetails\n", encoding="utf-8")

        mem_dir = self.root / "mem_test"
        args = [
            "install",
            str(self.src),
            "-o", str(self.repo),
            "--where", "project",
            "--with-memory",
            "--memory-root", str(mem_dir),
            "--migrate-specs",
            "-t", "claude",
            "--git", "skip",
        ]
        rc = agencos.main(args)
        self.assertEqual(rc, 0)

        pid = agencos.project_id_for(self.repo)
        migrated_spec = mem_dir / pid / "specs" / "feature1.md"
        self.assertTrue(migrated_spec.is_file())
        self.assertEqual(migrated_spec.read_text(encoding="utf-8"), "# Feature 1\nDetails\n")

    def test_local_memory_root(self):
        """Test setting memory root to 'local' / in-repo."""
        args = [
            "install",
            str(self.src),
            "-o", str(self.repo),
            "--where", "project",
            "--with-memory",
            "--memory-root", "local",
            "-t", "claude",
            "--git", "skip",
        ]
        rc = agencos.main(args)
        self.assertEqual(rc, 0)

        profile = json.loads((self.repo / ".agent-profile.json").read_text(encoding="utf-8"))
        self.assertIn("memory_root", profile)
        self.assertEqual(profile["memory_root"], ".agents/memories")
        self.assertTrue((self.repo / ".agents" / "memories").is_dir())


    def test_git_ignore_shared_and_local(self):
        """Test git ignore options: shared (.gitignore) vs local (.git/info/exclude)."""
        import subprocess
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)

        # 1. Install with shared ignore
        args_shared = [
            "install", str(self.src), "-o", str(self.repo),
            "--where", "project", "-t", "claude",
            "--git", "ignore", "--scope", "shared"
        ]
        rc = agencos.main(args_shared)
        self.assertEqual(rc, 0)
        gitignore = self.repo / ".gitignore"
        self.assertTrue(gitignore.is_file())
        self.assertIn("/.claude/agents/agent-a.md", gitignore.read_text(encoding="utf-8"))

        # 2. Re-sync with local ignore
        args_local = [
            "sync", "-s", str(self.repo / ".agents"), "-o", str(self.repo),
            "--where", "project", "-t", "claude",
            "--git", "ignore", "--scope", "local"
        ]
        rc = agencos.main(args_local)
        self.assertEqual(rc, 0)
        exclude = self.repo / ".git" / "info" / "exclude"
        self.assertTrue(exclude.is_file())
        self.assertIn("/.claude/agents/agent-a.md", exclude.read_text(encoding="utf-8"))

        # 3. Track in repo removes ignore blocks
        args_track = [
            "sync", "-s", str(self.repo / ".agents"), "-o", str(self.repo),
            "--where", "project", "-t", "claude",
            "--git", "track"
        ]
        rc = agencos.main(args_track)
        self.assertEqual(rc, 0)
        self.assertNotIn("agents-sync (generated files)", gitignore.read_text(encoding="utf-8"))
        self.assertNotIn("agents-sync (generated files)", exclude.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
