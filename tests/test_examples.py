"""从 tests/examples.md 逐行读取命令并执行，验证 @expect 标记。"""

import shlex, sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from console.api import exec_cmd


def _parse_examples(path: str) -> list[tuple[str, str]]:
    """解析 examples.md，返回 [(命令文本, 期望状态)]。"""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    cases = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("##"):
            continue
        if line.startswith("/"):
            # 下一行是 @expect 标记
            cases.append((line, ""))
        elif line.startswith("@expect success") and cases:
            cases[-1] = (cases[-1][0], "success")
        elif line.startswith("@expect fail") and cases:
            cases[-1] = (cases[-1][0], "fail")
        elif line.startswith("@"):
            continue
    return [(c, e) for c, e in cases if c and e]


def test_all_examples():
    root = Path(__file__).resolve().parent
    (root / "test_firmware.bin").write_bytes(b"\x00\x01\x02\x03" * 64)

    cases = _parse_examples(str(root / "examples.md"))
    assert len(cases) > 0, "no examples found"

    results = []
    for cmd_text, expected in cases:
        parts = shlex.split(cmd_text)
        cmd_name = parts[0].lstrip("/")
        args = {}
        i = 1
        while i < len(parts):
            a = parts[i]
            if a.startswith("--"):
                key = a[2:]
                if "=" in key:
                    k, v = key.split("=", 1)
                    args[k] = v
                    i += 1
                elif i + 1 < len(parts) and not parts[i+1].startswith("--"):
                    args[key] = parts[i+1]
                    i += 2
                else:
                    args[key] = "true"
                    i += 1
            else:
                args.setdefault("_", []).append(a)
                i += 1

        result = exec_cmd(cmd_name, args)
        ok = result.get("status") == "success"
        expected_ok = expected == "success"
        short = cmd_text[:70]

        if ok == expected_ok:
            results.append(f"✓ {short}")
        else:
            err = result.get("error", "?")
            results.append(f"✗ FAIL: {short}\n     error: {err}")

    print("\n".join(results))
    fails = [r for r in results if r.startswith("✗")]
    assert not fails, f"{len(fails)}/{len(results)} failed:\n" + "\n".join(fails)
    print(f"\n  {len(results)} examples all passed")
