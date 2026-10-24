"""Stdlib reference evaluator. Run directly for the eight frozen worked cases.

CLI: python eval_rules.py [--case input.json] [--rules dispatch_rules.json]
Suitable means eligible for human review, never authority to deploy.
Rules accumulate in listed order; severity can only increase. All matching
reasons and citations are retained, including lower-severity constraints.
"""
import argparse
import copy
import json
import math
from pathlib import Path

SEVERITY = {"suitable": 0, "caution": 1, "unsafe": 2}


def get(context, path):
    value = context
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def match(condition, context):
    if "all" in condition:
        return all(match(c, context) for c in condition["all"])
    if "any" in condition:
        return any(match(c, context) for c in condition["any"])
    value = get(context, condition["field"])
    op, target = condition["op"], condition.get("value")
    if op == "eq":
        return value == target
    if op == "ne":
        return value != target
    if op == "in":
        return value in target
    if op == "not_in":
        return value not in target
    if op in ("lt", "lte", "gt", "gte"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        return {"lt": value < target, "lte": value <= target,
                "gt": value > target, "gte": value >= target}[op]
    raise ValueError("Unknown condition operator: " + op)


def validate_case(case):
    if not isinstance(case, dict):
        raise ValueError("Input must be an object")
    h = case.get("hazards", {})
    if not isinstance(h, dict) or not isinstance(case.get("assigned_assets", {}), dict):
        raise ValueError("hazards and assigned_assets must be objects")
    for field in ("people_count", "children", "infants", "elderly", "wheelchair", "bedridden", "pets"):
        value = case.get(field, 0 if field != "people_count" else None)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(field + " must be a nonnegative integer")
    people = case.get("people_count")
    if people is not None:
        if people < 1 or any(case.get(f, 0) > people for f in ("children", "infants", "elderly", "wheelchair", "bedridden")):
            raise ValueError("Invalid person counts; demographic categories may overlap")
    for field in ("depth_m", "route_min_depth_m", "route_max_depth_m", "shelter_distance_m"):
        value = h.get(field)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(field + " must be finite and nonnegative or null")
    for field, allowed in {"current": ("still", "slow", "strong", "unknown"),
                           "depth_confidence": ("high", "medium", "low", "unknown"),
                           "electricity": ("isolated", "suspected_live", "live", "unknown"),
                           "debris": ("clear", "moderate", "heavy", "unknown")}.items():
        if h.get(field) is not None and h[field] not in allowed:
            raise ValueError("Invalid " + field)
    for value in h.values():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite hazard")
    boolean_hazards = ("hazards_current", "inside_flood_extent", "extent_date_matches",
                       "nearby_road_closure", "route_closed", "pump_station_outage",
                       "post_outage_reassessment", "overhead_clearance", "night",
                       "duplicate_check_complete")
    for field in boolean_hazards:
        if h.get(field) is not None and type(h[field]) is not bool:
            raise ValueError(field + " must be boolean or null")
    if case.get("mission") not in (None, "rescue", "search", "supply"):
        raise ValueError("Invalid mission")
    if case.get("location_type") not in (None, "house", "rooftop", "building_upper_floor", "public_building", "unknown"):
        raise ValueError("Invalid location_type")
    for asset in case.get("assigned_assets", {}).values():
        if not isinstance(asset, dict):
            raise ValueError("Each assigned asset must be an object")
        for field, value in asset.items():
            if value is not None and type(value) is not bool:
                raise ValueError("Asset attestation " + field + " must be boolean or null")


def evaluate(document, case):
    validate_case(case)
    c = copy.deepcopy(case)
    h = c.get("hazards", {})
    depth = h.get("depth_m")
    band = "unknown"
    if depth is not None and h.get("depth_confidence") == "high" and h.get("hazards_current") is True:
        for b in document["depth_bands"]:
            if b["id"] == "unknown":
                continue
            lower = b["min_inclusive_m"]
            upper = b["max_exclusive_m"]
            lower_ok = depth > lower if b.get("lower_exclusive") else depth >= lower
            upper_ok = upper is None or (depth <= upper if b.get("upper_inclusive") else depth < upper)
            if lower_ok and upper_ok:
                band = b["id"]
                break
    d = {
        "depth_band": band,
        "wet": depth is None or depth > 0 or h.get("inside_flood_extent") is not False,
        "elevated": c.get("location_type") in ("rooftop", "building_upper_floor"),
        "needs_stretcher": c.get("wheelchair", 0) > 0 or c.get("bedridden", 0) > 0,
        "vulnerable": any(c.get(f, 0) > 0 for f in ("children", "infants", "elderly", "wheelchair", "bedridden")),
        "infant_or_elderly": c.get("infants", 0) > 0 or c.get("elderly", 0) > 0,
        "known_people": type(c.get("people_count")) is int and c["people_count"] > 0,
        "demographics_known": all(type(c.get(f)) is int for f in ("children", "infants", "elderly", "wheelchair", "bedridden", "pets")),
    }
    results = {}
    for asset_id, asset in document["assets"].items():
        a = c.get("assigned_assets", {}).get(asset_id, {})
        if not isinstance(a, dict):
            raise ValueError("Each assigned asset must be an object")
        context = {"c": c, "h": h, "d": d, "a": a}
        result = {"status": "suitable", "role": asset["role"], "reason": "", "source_ids": [], "matched_rules": [], "constraints": []}
        for rule in document["rules"]:
            if asset_id not in rule["assets"] or not match(rule["when"], context):
                continue
            status = rule["status"]
            result["matched_rules"].append(rule["id"])
            result["constraints"].append({"rule_id": rule["id"], "status": status, "reason": rule["reason"], "source_ids": rule["source_ids"]})
            for sid in rule["source_ids"]:
                if sid not in result["source_ids"]:
                    result["source_ids"].append(sid)
            if SEVERITY[status] > SEVERITY[result["status"]] or not result["reason"]:
                result["status"], result["reason"] = status, rule["reason"]
        results[asset_id] = result
    return {"depth_band": band, "human_approval_required": True, "assets": results}


def check_examples(document):
    count = 0
    for example in document["examples"]:
        actual = evaluate(document, example["input"])
        assert actual["depth_band"] == example["expected_depth_band"], example["id"]
        statuses = {aid: r["status"] for aid, r in actual["assets"].items()}
        assert statuses == example["expected_statuses"], (example["id"], statuses, example["expected_statuses"])
        for aid, rule_ids in example.get("expected_rule_ids", {}).items():
            assert set(rule_ids) <= set(actual["assets"][aid]["matched_rules"]), (example["id"], aid, rule_ids)
        count += 1
    return count

