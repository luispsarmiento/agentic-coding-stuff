#!/usr/bin/env python3
"""Compatibility wrapper for agencos (formerly harness).

Exports all attributes from agencos so scripts and tests importing `harness`
continue to work without modification.
"""
import agencos
from agencos import *  # noqa: F401, F403

# Re-export key modules and functions explicitly for mock.patch compatibility
subprocess = agencos.subprocess
sync_agents = agencos.sync_agents
os = agencos.os
sys = agencos.sys
shutil = agencos.shutil
json = agencos.json

if __name__ == "__main__":
    raise SystemExit(agencos.main())
