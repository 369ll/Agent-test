from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_TESTS = [
    "tests/test_smoke.py",
    "tests/test_public_contract.py",
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("运行公开自检测试...")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *PUBLIC_TESTS],
        cwd=ROOT,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        print("公开自检通过。正式评分会使用私有隐藏测试。")
    else:
        print("公开自检未通过，请先修复环境或公开契约问题。")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

