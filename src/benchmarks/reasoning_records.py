"""Durable case-level scoring records; no implicit replay or result reuse."""
import hashlib
import json
import os
import threading
from pathlib import Path

from .errors import DecisionFailure


def recording_evaluator(evaluator, directory, case_ids):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stopped = threading.Event()

    def evaluate_case(arguments, processor):
        if stopped.is_set():
            raise DecisionFailure("Earlier case failed; queued cases must not make additional paid calls.")
        index, sample = arguments[:2]
        destination = directory / f"{index:04d}.json"
        if destination.exists():
            raise DecisionFailure("Existing case record requires explicit reviewed reuse; refusing a duplicate paid case.")
        result, error = evaluator(arguments, processor)
        if error or not result or not result.get("success"):
            stopped.set()
            raise DecisionFailure("Native case evaluation failed; partial records are retained and no default score is substituted.")
        record = {"case_id": case_ids[index], "index": index,
                  "sample_sha256": hashlib.sha256(json.dumps(sample, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                  "result": result}
        temporary = destination.with_suffix(".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return result, error

    def evaluate(arguments, processor):
        try:
            return evaluate_case(arguments, processor)
        except BaseException:
            stopped.set()
            raise

    return evaluate
