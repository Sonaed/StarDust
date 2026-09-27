from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORE_BINARY = ROOT / "native" / "build" / "stardust-core"


class StellarDustCore:
    """Python orchestration layer; graph state lives in the native process."""

    def __init__(self, creator: str = "brush_engine", binary: Path = CORE_BINARY):
        self.binary = Path(binary)
        if not self.binary.exists():
            raise FileNotFoundError(f"StellarDustCore absent: {self.binary}")
        self.process = subprocess.Popen(
            [str(self.binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self.command("reset", creator=creator)

    def command(self, command: str, **payload):
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("StellarDustCore process is closed")
        self.process.stdin.write(json.dumps({"command": command, **payload}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("StellarDustCore ne répond plus")
        return json.loads(line)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
