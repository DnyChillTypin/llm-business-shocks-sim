"""Verify and reuse completed independent Consulting sessions, never partial ones."""
import hashlib
import json
import math
import random
from pathlib import Path

from .common import ROOT, settings
from src.research.design import canonical_hash, load_native_file, text_hash

FIELDS = ("structure", "quant", "business_sense", "communication", "overall")
END = "<|CASE_INTERVIEW_END|>"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def recover_case(folder, case, events, config):
    """Return genuine history/judgment only after complete raw-evidence checks."""
    folder = Path(folder)
    starts = [e for e in events if e["event"] == "started" and e["context"].get("case_id") == case["case_id"]]
    judges = [e for e in starts if e["context"].get("validation_kind") == "judge"]
    if not judges:
        return None
    if len(judges) != 1 or starts[-1]["attempt_id"] != judges[0]["attempt_id"]:
        raise ValueError("Ambiguous Consulting judgment provenance; inspect instead of selecting a score.")
    finished = {e["attempt_id"]: e for e in events if e["event"] == "finished"}
    parsed = {e["attempt_id"]: e for e in events if e["event"] == "parse_checked"}
    history, evidence, judge_request, judge_scores = [], [], None, None
    ended = False
    for start in starts:
        key = start["attempt_id"]
        finish, parse = finished.get(key), parsed.get(key)
        if not finish or finish["status"] != "completed" or finish.get("cost_usd") is None or not parse or parse["parse_status"] != "valid":
            raise ValueError("A judged session contains incomplete/invalid API evidence; manual review required.")
        request_path, response_path = folder / "attempts" / key / "request.json", folder / "attempts" / key / "response.json"
        request, response = read(request_path), read(response_path)
        digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if digest != start["request_sha256"] or digest != finish["request_sha256"]:
            raise ValueError("Saved request hash differs from its durable attempt journal.")
        kind = start["context"].get("validation_kind")
        expected_model = config["primary_model"] if kind == "candidate" else config["judge_model"]
        expected_ceiling = min(512, config["max_output_tokens"]) if kind == "candidate" else config["max_output_tokens"]
        if request["model"] != expected_model or request["max_tokens"] != expected_ceiling:
            raise ValueError("Recovered session model or generation ceiling differs from the freeze.")
        if response.get("id") != finish.get("response_id") or response.get("usage") != finish.get("usage"):
            raise ValueError("Raw response identity/usage differs from the durable journal.")
        message = response["choices"][0]["message"]
        if not isinstance(message.get("content"), str) or not message["content"].strip() or message.get("tool_calls"):
            raise ValueError("Recovered Consulting evidence requires actual nonempty model text.")
        content = message["content"]
        if kind == "judge":
            judge_scores, judge_request = json.loads(content), request
        elif kind == "candidate":
            if not history or history[-1]["role"] != "interviewer":
                raise ValueError("Recovered candidate message is out of native dialogue order.")
            reply = json.loads(content)["reply"]
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError("Recovered candidate reply is empty.")
            history.append({"role": "candidate", "content": reply.strip()})
        else:
            if history and history[-1]["role"] != "candidate":
                raise ValueError("Recovered interviewer message is out of native dialogue order.")
            ended |= END in content
            history.append({"role": "interviewer", "content": content})
        evidence.append({"attempt_id": key, "request_digest": text_hash(request_path), "response_digest": text_hash(response_path)})
    if not history or len(history) > config["consulting_turns"] or (len(history) < config["consulting_turns"] and not ended):
        raise ValueError("Recovered dialogue did not reach native termination or its configured message limit.")
    history = [{**turn, "content": turn["content"].replace(END, "").strip() if END in turn["content"] else turn["content"]} for turn in history]
    transcript = "\n".join(f"{turn['role'].upper()}: {turn['content']}" for turn in history)
    user = judge_request["messages"][-1]["content"]
    if f"=== CASE TEXT ===\n{case['case_text']}\n\n" not in user or f"=== DIALOGUE TRANSCRIPT ===\n{transcript}\n\n" not in user:
        raise ValueError("The observed judgment does not match the frozen case and reconstructed dialogue.")
    if any(type(judge_scores.get(k)) not in (int, float) or not math.isfinite(judge_scores[k]) or not 0 <= judge_scores[k] <= 10 for k in FIELDS):
        raise ValueError("Recovered judgment contains an invalid rubric score.")
    judge_scores.setdefault("ended_by_interviewer", ended)
    judge_scores.setdefault("turns_used", len(history))
    return {"case_id": case["case_id"], "case_content_sha256": canonical_hash(case), "history": history,
            "judge_scores": judge_scores, "source_folder": str(folder.resolve()), "evidence": evidence}


def build_recovery(source_runs):
    config = settings()
    loader = load_native_file(ROOT, "vendor/FirmBench/Consulting/run.py", "recovery_consulting_loader")
    cases = loader.load_consulting_cases(str(ROOT / "vendor/FirmBench/Consulting/agsm_cases_all.json"))
    cases = random.Random(config["seed"]).sample(cases, config["consulting_cases"])
    frozen_ids = [c["case_id"] for c in cases]
    folders = [Path(p).resolve() for p in source_runs]
    for folder in folders:
        if not folder.is_relative_to(ROOT / "results/benchmarks/firm_consulting"):
            raise ValueError("Recovery sources must stay inside local Consulting evidence.")
    folders.sort(key=lambda p: read(p / "run_manifest.json")["started_at_utc"])
    recovered = {}
    for folder in folders:
        manifest, prior = read(folder / "run_manifest.json"), read(folder / "run_config.json")
        identity = read(folder / "runtime_identity.json")
        if (manifest["task"] != "firm:consulting" or manifest["purpose"] != "evaluation"
                or manifest["selected_case_ids"] != frozen_ids or any(prior.get(k) != v for k, v in config.items())
                or identity["study_manifest_sha256"] != text_hash(ROOT / "docs/results/study_design_manifest.json")
                or identity["source_pins"] != read(ROOT / "configs/sources.json")):
            raise ValueError("Recovery source differs from frozen models, method, cases or pinned sources.")
        events = [json.loads(line) for line in (folder / "api_attempts.jsonl").read_text().splitlines()]
        for case in cases:
            if case["case_id"] not in recovered:
                record = recover_case(folder, case, events, config)
                if record:
                    recovered[case["case_id"]] = record
    return {"version": 1, "selection_rule": "earliest fully evidenced completed judgment per frozen independent case; never score-based",
            "source_runs": [str(p) for p in folders], "frozen_case_ids": frozen_ids, "cases": recovered}


def verify_recovery(path):
    stored = read(path)
    derived = build_recovery(stored["source_runs"])
    if canonical_hash(stored) != canonical_hash(derived):
        raise ValueError("Recovery manifest differs from independently re-audited source responses.")
    return derived
