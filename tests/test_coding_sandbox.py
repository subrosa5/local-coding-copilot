import shutil
import subprocess
from pathlib import Path

import pytest

from local_coding_copilot.auth import Principal
from local_coding_copilot.coding.models import CodingTask
from local_coding_copilot.coding.orchestrator import CodingOrchestrator
from local_coding_copilot.coding.patches import StaticPatchProvider
from local_coding_copilot.coding.sandbox import DockerSandbox, SandboxConfig
from local_coding_copilot.coding.worktree import GitWorktreeManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not docker_is_available(), reason="Docker CLI and daemon are required"
)


def test_container_has_no_network(exchange_repository: Path) -> None:
    result = DockerSandbox().run(
        exchange_repository,
        (
            "python",
            "-c",
            "import socket\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('Network access was not blocked')",
        ),
        "security",
    )

    assert result.exit_code == 0, result.stderr_tail


def test_host_paths_and_docker_socket_are_not_mounted(
    exchange_repository: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("synthetic", encoding="utf-8")
    result = DockerSandbox().run(
        exchange_repository,
        (
            "python",
            "-c",
            "from pathlib import Path\n"
            f"assert not Path({str(outside)!r}).exists()\n"
            "assert not Path('/var/run/docker.sock').exists()",
        ),
        "security",
    )

    assert result.exit_code == 0, result.stderr_tail


def test_read_only_root_writable_workspace_and_non_root_user(
    exchange_repository: Path,
) -> None:
    result = DockerSandbox().run(
        exchange_repository,
        (
            "python",
            "-c",
            "import os\n"
            "from pathlib import Path\n"
            "assert os.getuid() != 0\n"
            "Path('/workspace/sandbox-write-check').write_text('ok')\n"
            "try:\n"
            "    Path('/root-write-check').write_text('denied')\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            "    raise SystemExit('Root filesystem was writable')",
        ),
        "security",
    )

    assert result.exit_code == 0, result.stderr_tail
    assert (exchange_repository / "sandbox-write-check").read_text() == "ok"


def test_timeout_removes_container(exchange_repository: Path) -> None:
    result = DockerSandbox(SandboxConfig(timeout_seconds=10)).run(
        exchange_repository,
        ("python", "-c", "import time; time.sleep(30)"),
        "security",
        timeout_seconds=0.5,
    )

    assert result.timed_out
    assert result.exit_code == 124
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            "name=copilot-sandbox-",
            "--format",
            "{{.Names}}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert containers == ""


@pytest.mark.parametrize(
    "task_id", ["notional-boundary", "price-time-priority", "stale-threshold"]
)
def test_prepared_patch_passes_real_build_and_tests(
    exchange_repository: Path,
    tmp_path: Path,
    admin_principal: Principal,
    task_id: str,
) -> None:
    orchestrator = CodingOrchestrator(
        worktrees=GitWorktreeManager(tmp_path / "worktrees"),
        sandbox=DockerSandbox(SandboxConfig(timeout_seconds=30)),
        patches=StaticPatchProvider.from_file(PROJECT_ROOT / "evals/coding_tasks.json"),
        audit=RecordingAudit(),
    )

    result = orchestrator.run(
        exchange_repository,
        CodingTask(task_id, "Apply the prepared synthetic fix"),
        "default",
        principal=admin_principal,
    )

    assert result.status == "awaiting_review", result.message
    assert result.build is not None and result.build.exit_code == 0
    assert result.test is not None and result.test.exit_code == 0, (
        result.test.stdout_tail + result.test.stderr_tail
    )
    assert result.diff
    assert result.tests_changed


class RecordingAudit:
    def record_audit(self, *args: object, **kwargs: object) -> None:
        pass
