"""Read aggregate native-run progress; no credentials, mutation or API calls."""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.run / "run_manifest.json").read_text(encoding="utf-8"))
    path = args.run / "api_attempts.jsonl"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    events = []
    lines = content.splitlines()
    for index, line in enumerate(lines):
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if index == len(lines) - 1 and not content.endswith("\n"):
                break  # A concurrently appended event has not finished writing.
            raise
    starts = [e for e in events if e["event"] == "started"]
    finishes = [e for e in events if e["event"] == "finished"]
    complete = [e for e in finishes if e["status"] == "completed"]
    result = {"task": manifest["task"], "status": manifest["status"], "attempts_started": len(starts),
              "completed_responses": len(complete), "failed_responses": len(finishes) - len(complete),
              "attempts_without_observed_outcome": len(starts) - len(finishes),
              "invalid_responses": sum(e["event"] == "parse_checked" and e["parse_status"] != "valid" for e in events),
              "estimated_known_credits": sum(e.get("cost_usd") or 0 for e in finishes)}
    if manifest["task"] == "icbe":
        rounds = defaultdict(set)
        replay_path = args.run / "icbe_replays.jsonl"
        replays = [json.loads(line) for line in replay_path.read_text(encoding="utf-8").splitlines()] if replay_path.exists() else []
        for event in replays:
            pair, round_number, actor = event["logical_choice"].split(":")
            rounds[(pair, int(round_number))].add(actor)
        for event in complete:
            ctx = event["context"]
            rounds[(ctx["case_id"], ctx["round"])].add(ctx["actor"])
        completed = [key for key, actors in rounds.items() if actors == {"A", "B"}]
        pairs = sorted({key[0] for key in completed})
        result["completed_rounds_total"] = len(completed)
        result["replayed_observed_decisions"] = len(replays)
        result["accounted_decisions_total"] = len(complete) + len(replays)
        result["completed_matches"] = sum(sum(pair == key[0] for key in completed) == manifest["configured_horizon"] for pair in pairs)
        if complete:
            latest = complete[-1]["context"]
            result.update(current_match=int(latest["case_id"].rsplit("_", 1)[1]) + 1,
                          latest_round=latest["round"], current_phase=(latest["round"] - 1) // 25 + 1)
    elif manifest["task"] == "firm:consulting":
        result["new_judgments"] = sum(e["context"].get("validation_kind") == "judge" for e in complete)
        result["completed_session_checkpoints"] = len(list((args.run / "consulting_completed_cases").glob("*.json")))
    else:
        result["saved_reasoning_cases"] = len(list((args.run / "case_records").glob("*.json")))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
