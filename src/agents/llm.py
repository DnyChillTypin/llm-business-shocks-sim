"""Frozen daily policy with one repair and an explicit adaptive fallback."""
import json
import math

from src.agents.baselines import choose_actions
from src.benchmarks.common import ROOT
from src.benchmarks.gateway import request_context


def serialize_observation(observation):
    """The sole policy input, shared with baselines; never accepts an environment."""
    return json.dumps(observation, sort_keys=True, ensure_ascii=False, allow_nan=False)


def validate_actions(actions, observation):
    if not isinstance(actions, dict) or set(actions) != set(observation["products"]):
        raise ValueError("Action keys must exactly match the observed products.")
    cost = 0.0
    for sku, action in actions.items():
        product = observation["products"][sku]
        if not isinstance(action, dict) or set(action) != {"order_quantity", "price_multiplier"}:
            raise ValueError("Each action needs exactly order_quantity and price_multiplier.")
        quantity, multiplier = action["order_quantity"], action["price_multiplier"]
        if type(quantity) is not int or not 0 <= quantity <= product["max_order_quantity"]:
            raise ValueError("Quantity must be a nonnegative integer within the observed order limit.")
        if type(multiplier) not in (int, float) or not math.isfinite(multiplier) or multiplier not in observation["price_multipliers"]:
            raise ValueError("Price multiplier must be one of the observed allowed values.")
        cost += quantity * product["unit_cost"]
    if cost > observation["funds"]:
        raise ValueError("Combined purchase cost exceeds current funds.")
    return actions


def decode_action(text, observation):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result
    return validate_actions(json.loads(text, object_pairs_hook=unique), observation)


class LLMPolicy:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings
        self.system = (ROOT / settings["system_prompt"]).read_text(encoding="utf-8")
        self.repair = (ROOT / settings["repair_prompt"]).read_text(encoding="utf-8")

    def __call__(self, observation):
        messages = [{"role": "system", "content": self.system},
                    {"role": "user", "content": serialize_observation(observation)}]
        errors, responses = [], []
        for repair_index in range(2):
            with request_context(logical_request_id=f"day:{observation['date']}:repair:{repair_index}",
                                 case_id=observation["date"], role="kaggle_policy", validation_kind="kaggle"):
                response = self.client.chat.completions.create(model=self.settings["requested_id"],
                    messages=messages, temperature=self.settings["temperature"],
                    max_tokens=self.settings["max_output_tokens"], response_format={"type": "json_object"})
            choice = response.choices[0] if response.choices else None
            text = (choice.message.content or "") if choice else ""
            responses.append(text)
            try:
                if choice is None or choice.finish_reason != "stop":
                    raise ValueError("Completion did not finish normally.")
                if getattr(choice.message, "tool_calls", None) or getattr(choice.message, "refusal", None):
                    raise ValueError("Expected an action object without tool calls or refusal.")
                action = decode_action(text, observation)
                return action, {"source": "llm", "repair_attempted": bool(repair_index),
                                "invalid_responses": len(errors), "fallback_used": False,
                                "validation_errors": errors, "responses": responses}
            except (ValueError, TypeError, KeyError) as exc:
                errors.append(str(exc))
                messages += [{"role": "assistant", "content": text},
                             {"role": "user", "content": self.repair + "\nValidation error: " + str(exc)}]
        return choose_actions(observation, "adaptive"), {"source": "adaptive_fallback", "repair_attempted": True,
            "invalid_responses": 2, "fallback_used": True, "validation_errors": errors, "responses": responses}
