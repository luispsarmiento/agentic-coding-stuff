import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.mem = self.root / "mem"
        self.pid = "proj-1"
        base = self.mem / self.pid
        (base / "notes").mkdir(parents=True)
        (base / "specs").mkdir(parents=True)
        (base / "notes" / "a.md").write_text("hello world decision\n", encoding="utf-8")
        (base / "specs" / "spec1.md").write_text("# Spec\ncontent here\n", encoding="utf-8")
        self.server = Path(__file__).resolve().parents[1] / "scripts" / "agent-memory-server.py"
        self.proc = subprocess.Popen(
            [sys.executable, str(self.server), "--root", str(self.mem), "--project", self.pid],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def tearDown(self):
        self.proc.kill()
        self.proc.wait()
        self.td.cleanup()

    def rpc(self, method, params=None, rid=1):
        req = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        return json.loads(line)

    def test_initialize_and_tools(self):
        r = self.rpc("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(r["result"]["serverInfo"]["name"], "agent-memory")
        r = self.rpc("tools/list")
        names = [t["name"] for t in r["result"]["tools"]]
        self.assertIn("memory_search", names)
        self.assertIn("memory_save", names)

    def test_memory_search(self):
        r = self.rpc("tools/call", {"name": "memory_search", "arguments": {"query": "decision"}})
        self.assertIn("decision", r["result"]["content"][0]["text"])

    def test_spec_get(self):
        r = self.rpc("tools/call", {"name": "spec_get", "arguments": {"name": "spec1.md"}})
        self.assertIn("content here", r["result"]["content"][0]["text"])

    def test_memory_save(self):
        r = self.rpc("tools/call", {"name": "memory_save", "arguments": {"title": "T", "content": "body"}})
        self.assertIn("Saved:", r["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()