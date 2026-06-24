"""Run server.py as a subprocess over stdio, speak a few MCP messages, dump
the responses. Manual sanity check that the MCP layer wires up correctly —
not part of the automated suite (it spawns a subprocess and depends on the
real Python interpreter).

Usage:
    uv run python tests/manual_stdio_probe.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def send(proc: subprocess.Popen, msg: dict) -> None:
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def read_response(proc: subprocess.Popen, timeout: float = 5.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        try:
            return json.loads(line.decode())
        except json.JSONDecodeError:
            print("non-JSON line:", line[:200])
    return None


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=REPO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "manual-probe", "version": "0.1"},
            },
        })
        init = read_response(proc)
        assert init and init.get("id") == 1, f"bad initialize response: {init}"
        print("initialize ok — server:", init["result"]["serverInfo"]["name"])

        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listed = read_response(proc)
        assert listed and listed.get("id") == 2, f"bad tools/list: {listed}"
        tools = listed["result"]["tools"]
        print(f"tools/list ok — {len(tools)} tools:")
        for t in sorted(tools, key=lambda x: x["name"]):
            print(f"  {t['name']}")

        send(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_agencies", "arguments": {}},
        })
        called = read_response(proc, timeout=10.0)
        assert called and called.get("id") == 3, f"bad tools/call: {called}"
        # list_agencies returns a list[str]; FastMCP serializes it as content blocks.
        content = called["result"]["content"]
        print(f"tools/call list_agencies -> {len(content)} content block(s):")
        for block in content[:1]:
            print(" ", block.get("text", "")[:200])

        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
