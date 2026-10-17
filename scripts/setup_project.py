"""Download verified data and check out only RetailBench code needed by the pilot.

Uses the public dataset API, never requires stored API keys, and does not fetch
RetailBench's 29 GB historical LFS artifacts. Existing source checkouts are not
rewritten. Run this script after installing requirements-research.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=None):
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                            text=True, env=dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0"))
    return result.stdout.strip()


def setup_vendor(project_root: Path, source: dict):
    destination = project_root / "vendor/RetailBench"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not (destination / ".git").exists():
        if destination.exists() and any(destination.iterdir()):
            raise RuntimeError(f"Refusing to replace nonempty directory: {destination}")
        destination.mkdir(exist_ok=True)
        git("init", str(destination))
        git("remote", "add", "origin", source["url"], cwd=destination)
        git("sparse-checkout", "init", "--no-cone", cwd=destination)
        git("sparse-checkout", "set", "--no-cone", "/retail_environment.py", "/module/", "/model/", "/util/", "/LICENSE", cwd=destination)
    try:
        head = git("rev-parse", "HEAD", cwd=destination)
    except subprocess.CalledProcessError:
        head = None
    if head is None:
        git("-c", "http.version=HTTP/1.1", "fetch", "--depth=1", "--filter=blob:none", "origin", source["commit"], cwd=destination)
        git("checkout", "--detach", source["commit"], cwd=destination)
        head = git("rev-parse", "HEAD", cwd=destination)
    if head != source["commit"]:
        raise RuntimeError(f"Existing RetailBench is at {head}, expected {source['commit']}; it was not changed.")
    if git("status", "--porcelain", "--untracked-files=no", cwd=destination):
        raise RuntimeError("RetailBench has tracked changes; use an unchanged pinned checkout.")
    if not (destination / "retail_environment.py").is_file():
        raise RuntimeError("RetailBench source is incomplete; inspect its sparse checkout.")
    print(f"RetailBench source verified: {head}")


def setup_data(project_root: Path, source: dict):
    destination = project_root / "data/raw/kaggle"
    csv_path = destination / source["csv_file"]
    if csv_path.exists():
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if digest != source["csv_sha256"]:
            raise RuntimeError("Existing CSV checksum differs from the pinned dataset; it was not changed.")
        if not (destination / "dataset_metadata.json").exists():
            raise RuntimeError("CSV exists but provenance metadata is missing; inspect data/raw/kaggle.")
        print("Existing Kaggle CSV verified.")
        return
    url = f"https://www.kaggle.com/api/v1/datasets/download/{source['reference']}?datasetVersionNumber={source['version']}"
    request = urllib.request.Request(url, headers={"User-Agent": "business-shocks-research-setup"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Downloaded archive failed its integrity check.")
        content = archive.read(source["csv_file"])
    digest = hashlib.sha256(content).hexdigest()
    if digest != source["csv_sha256"]:
        raise RuntimeError("Downloaded CSV differs from pinned version/checksum; no CSV was saved.")
    destination.mkdir(parents=True, exist_ok=True)
    archive_name = f"dataset-v{source['version']}.zip"
    metadata = {
        "dataset_reference": source["reference"], "source_url": source["url"],
        "version": source["version"], "download_url": url,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "csv_file": source["csv_file"], "csv_sha256": digest,
        "archive_file": archive_name, "archive_sha256": hashlib.sha256(payload).hexdigest(),
        "subtitle": "A synthetic dataset for inventory and demand forecasting.",
    }
    (destination / archive_name).write_bytes(payload)
    csv_path.write_bytes(content)
    (destination / "dataset_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Kaggle version {source['version']} downloaded and CSV checksum verified.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT,
                        help="Destination workspace; useful for checking a fresh installation.")
    args = parser.parse_args()
    sources = json.loads((ROOT / "configs/sources.json").read_text(encoding="utf-8"))
    setup_vendor(args.project_root.resolve(), sources["retailbench"])
    setup_data(args.project_root.resolve(), sources["dataset"])
    print("Inputs ready. Open notebooks/01_kaggle_retailbench_integration.ipynb.")


if __name__ == "__main__":
    main()
