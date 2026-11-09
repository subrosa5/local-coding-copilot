import math
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from local_coding_copilot.coding.models import SandboxResult

_OUTPUT_TAIL = 4000


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    image: str = "python:3.11-slim"
    memory: str = "512m"
    cpus: str = "1.0"
    pids_limit: int = 128
    timeout_seconds: float = 30.0


class DockerSandbox:
    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()

    def run(
        self,
        worktree: Path,
        command: Sequence[str],
        stage: str,
        timeout_seconds: float | None = None,
    ) -> SandboxResult:
        if not command:
            raise ValueError("Sandbox command must not be empty")
        worktree = worktree.resolve()
        if not worktree.is_dir():
            raise ValueError(f"Sandbox worktree does not exist: {worktree}")

        config = self._config
        name = f"copilot-sandbox-{uuid.uuid4().hex}"
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            uid, gid = 65532, 65532
        arguments = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{uid}:{gid}",
            "--memory",
            config.memory,
            "--cpus",
            config.cpus,
            "--pids-limit",
            str(config.pids_limit),
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--mount",
            f"type=bind,source={worktree},target=/workspace",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONPATH=/workspace/src",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            config.image,
            *command,
        ]
        effective_timeout = (
            config.timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if (
            isinstance(effective_timeout, bool)
            or not isinstance(effective_timeout, (int, float))
            or not math.isfinite(effective_timeout)
            or effective_timeout <= 0
        ):
            raise ValueError("Sandbox timeout must be finite and positive")
        started = time.monotonic()
        process = subprocess.Popen(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_tail = bytearray()
        stderr_tail = bytearray()
        readers = (
            threading.Thread(
                target=_drain_tail,
                args=(process.stdout, stdout_tail),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_tail,
                args=(process.stderr, stderr_tail),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                subprocess.run(
                    ["docker", "rm", "--force", name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                process.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                process.kill()
                process.wait()
        for reader in readers:
            reader.join()
        duration_ms = round((time.monotonic() - started) * 1000)
        return SandboxResult(
            stage=stage,
            command=tuple(command),
            exit_code=124 if timed_out else process.returncode,
            duration_ms=duration_ms,
            timed_out=timed_out,
            stdout_tail=stdout_tail.decode("utf-8", errors="replace"),
            stderr_tail=stderr_tail.decode("utf-8", errors="replace"),
        )


def _drain_tail(stream, tail: bytearray) -> None:
    while chunk := stream.read(8192):
        tail.extend(chunk)
        if len(tail) > _OUTPUT_TAIL:
            del tail[: len(tail) - _OUTPUT_TAIL]
