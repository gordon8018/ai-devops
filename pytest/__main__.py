from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path
import sys
import tempfile
import traceback


def _discover_test_files(paths: list[str]) -> list[Path]:
    if not paths:
        paths = ["tests"]

    discovered: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            discovered.extend(sorted(path.rglob("test_*.py")))
        elif path.is_file():
            discovered.append(path)
    return discovered


def _load_module(path: Path, index: int):
    module_name = f"_pytest_shim_{index}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to import test module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run_test(func) -> None:
    kwargs = {}
    temp_dirs: list[tempfile.TemporaryDirectory[str]] = []
    for name in inspect.signature(func).parameters:
        if name == "tmp_path":
            temp_dir = tempfile.TemporaryDirectory()
            temp_dirs.append(temp_dir)
            kwargs[name] = Path(temp_dir.name)
            continue
        raise RuntimeError(f"Unsupported fixture: {name}")

    try:
        func(**kwargs)
    finally:
        for temp_dir in temp_dirs:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    quiet = False
    filtered_args: list[str] = []
    for arg in argv:
        if arg == "-q":
            quiet = True
            continue
        filtered_args.append(arg)

    test_files = _discover_test_files(filtered_args)
    total = 0
    failures = 0

    for index, path in enumerate(test_files):
        module = _load_module(path, index)
        for name, func in sorted(vars(module).items()):
            if not name.startswith("test_") or not callable(func):
                continue
            total += 1
            try:
                _run_test(func)
                if quiet:
                    sys.stdout.write(".")
                    sys.stdout.flush()
                else:
                    print(f"PASS {path}:{name}")
            except Exception:
                failures += 1
                if quiet:
                    sys.stdout.write("F")
                    sys.stdout.flush()
                else:
                    print(f"FAIL {path}:{name}")
                traceback.print_exc()

    if quiet:
        sys.stdout.write("\n")

    if failures:
        print(f"{failures} failed, {total - failures} passed")
        return 1

    print(f"{total} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
