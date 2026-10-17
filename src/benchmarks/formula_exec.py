"""Windows substitute for FirmBench's fork/SIGALRM formula execution helper.

    Uses a separate process with a parent-enforced timeout and no API credentials.
    Numeric code has restricted imports/builtins; this is not an OS security sandbox.
    Native formula assembly, test generation, tolerances and scoring are unchanged.
"""
import ast
import builtins
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def exec_python_windows(code, timeout=1.0):
    root = Path(__file__).resolve().parents[2]
    cache = root / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        target = Path(directory).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError("Formula worker directory is outside this workspace.")
        env = {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if name in os.environ}
        env.update(TEMP=directory, TMP=directory, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
        try:
            result = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve())], input=json.dumps({"code": code}),
                text=True, capture_output=True, cwd=directory, env=env, timeout=timeout + 2)
            if result.returncode:
                return {"return_val": None, "failure_reason": "formula_worker_failed"}
            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            return {"return_val": None, "failure_reason": "timeout"}


def main():
    code = json.load(sys.stdin)["code"]
    allowed = {"math", "statistics", "decimal", "fractions", "itertools", "functools", "collections", "random", "typing", "numpy", "scipy", "pandas", "datetime", "re", "dataclasses"}
    original_import = builtins.__import__

    def restricted_import(name, *args, **kwargs):
        if name.split(".")[0] not in allowed:
            raise ImportError("Unsupported import in formula worker")
        return original_import(name, *args, **kwargs)
    safe = {name: value for name, value in vars(builtins).items() if name not in
            {"open", "input", "eval", "exec", "compile", "breakpoint", "exit", "quit", "help"}}
    safe["__import__"] = restricted_import
    result = {"return_val": None, "failure_reason": None}
    try:
        block = ast.parse(code, mode="exec")
        if any(isinstance(n, ast.Attribute) and n.attr.startswith("__") and n.attr != "__init__" for n in ast.walk(block)):
            raise ValueError("Unsupported attribute in formula worker")
        if not block.body or not isinstance(block.body[-1], ast.Expr):
            raise ValueError("Formula must finish with a value expression")
        final = ast.Expression(block.body.pop().value)
        namespace = {"__builtins__": safe, "__name__": "formula_worker"}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exec(compile(block, "<formula>", "exec"), namespace, namespace)
            result["return_val"] = eval(compile(final, "<formula>", "eval"), namespace, namespace)
    except BaseException as exc:
        result["failure_reason"] = type(exc).__name__
    print(json.dumps(result, default=lambda value: value.item() if hasattr(value, "item") else str(value)))


if __name__ == "__main__":
    main()
