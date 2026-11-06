import subprocess
import sys


def test_evaluation_module_is_executable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "local_coding_copilot.evaluation", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--dataset" in result.stdout
    assert result.stderr == ""
