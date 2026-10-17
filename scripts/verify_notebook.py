r"""Execute the integration notebook with this interpreter in a fresh kernel.

No global kernel registration, API calls, or edits to vendor/raw inputs.
Run: .\.venv\Scripts\python.exe scripts/verify_notebook.py
"""
import json
import argparse
import sys
import tempfile
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager
from nbclient import NotebookClient

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--notebook", default="notebooks/01_kaggle_retailbench_integration.ipynb")
args = parser.parse_args()
path = (root / args.notebook).resolve()
if not path.is_relative_to(root / "notebooks"):
    raise ValueError("Choose a notebook inside this project's notebooks directory.")
cache = root / ".cache"
cache.mkdir(exist_ok=True)
notebook = nbformat.read(path, as_version=4)
nbformat.validate(notebook)
with tempfile.TemporaryDirectory(dir=cache) as temporary:
    temporary = Path(temporary)
    spec = temporary / "paper-project"
    spec.mkdir()
    (spec / "kernel.json").write_text(json.dumps({
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Project environment", "language": "python",
    }), encoding="utf-8")
    manager = KernelManager(kernel_name="paper-project",
                            kernel_spec_manager=KernelSpecManager(kernel_dirs=[str(temporary)]),
                            connection_file=str(temporary / "connection.json"))
    client = NotebookClient(notebook, km=manager, timeout=180,
                            resources={"metadata": {"path": str(root)}})
    try:
        client.execute()
    finally:
        if manager.has_kernel:
            manager.shutdown_kernel(now=True)
nbformat.write(notebook, path)
print(f"Executed and saved: {path}")
print(f"Code cells: {sum(cell.cell_type == 'code' for cell in notebook.cells)}")
