"""极简测试运行器：python tests/run_tests.py（无 pytest 依赖）。"""

import importlib.util
import inspect
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, TESTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    passed, failed = [], []
    for file in sorted(TESTS_DIR.glob("test_*.py")):
        module = load_module(file.stem)
        tests = [fn for name, fn in vars(module).items()
                 if name.startswith("test_") and callable(fn)]
        for fn in tests:
            tmp = Path(tempfile.mkdtemp(prefix=f"payqr_{fn.__name__}_"))
            needs_tmp = bool(inspect.signature(fn).parameters)
            try:
                fn(tmp) if needs_tmp else fn()
                print(f"PASS  {file.stem}::{fn.__name__}")
                passed.append(fn.__name__)
            except Exception:
                print(f"FAIL  {file.stem}::{fn.__name__}")
                traceback.print_exc()
                failed.append(f"{file.stem}::{fn.__name__}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(passed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
