from asyncio import subprocess


def adb_tap(x, y):
    result = subprocess.run(
        ["adb", "shell", "input", "tap", str(int(x)), str(int(y))],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Comando adb tap fallito.")

    return True