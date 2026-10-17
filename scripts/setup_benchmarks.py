"""Fetch pinned native sources/inputs; skip RetailBench historical paper outputs."""
import json
import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True,
        env=dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0")).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["RetailBench", "FirmBench", "ICBE"], help="Prepare just one source, for example the small ICBE checkout in CI.")
    args = parser.parse_args()
    sources = json.loads((ROOT / "configs/sources.json").read_text(encoding="utf-8"))
    vendors = [("RetailBench", sources["retailbench"]), ("FirmBench", sources["reference_repositories"]["FirmBench"]),
               ("icbe-2026-strategic-behavior", sources["reference_repositories"]["ICBE"])]
    for name, source in vendors:
        if args.only and name != {"RetailBench": "RetailBench", "FirmBench": "FirmBench", "ICBE": "icbe-2026-strategic-behavior"}[args.only]:
            continue
        destination = ROOT / "vendor" / name
        if not (destination / ".git").exists():
            if destination.exists() and any(destination.iterdir()):
                raise RuntimeError(f"Refusing to replace nonempty directory {destination}")
            destination.mkdir(parents=True, exist_ok=True)
            git("init", str(destination))
            git("remote", "add", "origin", source["url"], cwd=destination)
            if name == "RetailBench":
                git("sparse-checkout", "init", "--no-cone", cwd=destination)
                git("sparse-checkout", "set", "--no-cone", "/retail_environment.py", "/run_env.py", "/module/", "/model/", "/util/", "/agents/", "/data/", "/LICENSE", cwd=destination)
            git("fetch", "--depth=1", "origin", source["commit"], cwd=destination)
            git("checkout", "--detach", source["commit"], cwd=destination)
        if git("rev-parse", "HEAD", cwd=destination) != source["commit"]:
            raise RuntimeError(f"Unexpected version of {name}; checkout was not changed.")
        if git("status", "--porcelain", "--untracked-files=no", cwd=destination):
            raise RuntimeError(f"Tracked vendor changes in {name}; inspect before proceeding.")
        if name == "RetailBench":
            sparse = subprocess.run(["git", "config", "--bool", "core.sparseCheckout"], cwd=destination,
                                    capture_output=True, text=True).stdout.strip()
            if sparse == "true":
                git("sparse-checkout", "add", "--no-cone", "/run_env.py", "/agents/", "/data/", cwd=destination)
            # Only native simulation inputs, never the large paper_data archive.
            git("lfs", "pull", "--include=data/**", "--exclude=", cwd=destination)
        print(f"Verified {name}: {source['commit']}")
    print("Selected native sources verified. Run scripts/check_benchmarks.py for local validation.")


if __name__ == "__main__":
    main()
