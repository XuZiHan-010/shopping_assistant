"""在无数据库的隔离 pytest 子进程中检验安全门禁退出码。"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import pytest\ndef test_first(): pytest.skip('missing database')\n"
            "def test_last(): pass\n",
            1,
        ),
        ("def test_first(): pass\ndef test_last(): pass\n", 0),
        ("import pytest\ndef test_only(): pytest.skip('missing database')\n", 1),
        (
            "import pytest\n@pytest.mark.skip(reason='missing database')\n"
            "def test_first(): pass\ndef test_last(): pass\n",
            1,
        ),
        ("import pytest\npytest.skip('missing database', allow_module_level=True)\n", 1),
    ],
)
def test_security_gate_skip_exit_code(tmp_path: Path, source: str, expected: int) -> None:
    backend = Path(__file__).resolve().parents[2]
    suite = tmp_path / "tests" / "eval"
    suite.mkdir(parents=True)
    (suite / "conftest.py").write_text(
        (backend / "tests/eval/conftest.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (suite / "test_security_gate.py").write_text(source, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(backend), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--confcutdir",
            str(tmp_path),
            "tests/eval/test_security_gate.py",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert "skip" in result.stderr
