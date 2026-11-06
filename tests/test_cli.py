import subprocess
import sys


def test_cli_runs_the_fake_provider_smoke_path() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "local_coding_copilot", "Hello"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "Fake provider response.\n"
    assert result.stderr == ""
