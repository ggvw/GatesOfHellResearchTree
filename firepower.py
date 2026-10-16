"""Transparent fire-volume estimates, not damage or armour-penetration scores."""

import math
from collections import defaultdict


BURST_WINDOW_SECONDS = 5
REFERENCE_CALIBER_MM = 7.62
METRIC_KEYS = (
    "burst_rounds_5s",
    "sustained_rpm",
    "rounds_per_minute_per_cp",
    "caliber_weighted_rpm",
    "firing_endurance_seconds",
)


def weapon_firepower(weapon: dict) -> dict:
    """Estimate fully loaded, uninterrupted fire, excluding aiming and AI pauses."""
    result = dict.fromkeys(METRIC_KEYS)
    rate = weapon.get("rate_of_fire_rpm")
    capacity = weapon.get("rounds_before_reload")
    reload_time = weapon.get("reload_time_seconds")
    caliber = weapon.get("caliber_mm")
    if rate is None or rate <= 0 or capacity is None or capacity < 1:
        return result

    interval = 60 / rate
    endurance = (capacity - 1) * interval
    result["firing_endurance_seconds"] = endurance
    # The window includes the first shot at t=0, but excludes shots at t=5.
    shots_without_reload = math.ceil(BURST_WINDOW_SECONDS / interval - 1e-9)
    if shots_without_reload <= capacity:
        result["burst_rounds_5s"] = shots_without_reload
    if reload_time is None or reload_time < 0:
        return result

    # A new magazine cannot fire sooner than the weapon's shot interval.
    cycle = endurance + max(reload_time, interval)
    cycles = int(BURST_WINDOW_SECONDS // cycle)
    remaining = max(0, BURST_WINDOW_SECONDS - cycles * cycle)
    result["burst_rounds_5s"] = cycles * capacity + min(
        capacity, max(0, math.ceil(remaining / interval - 1e-9))
    )
    result["sustained_rpm"] = 60 * capacity / cycle
    if caliber is not None and caliber > 0:
        result["caliber_weighted_rpm"] = result["sustained_rpm"] * caliber / REFERENCE_CALIBER_MM
    return result


def firepower_group(node: dict) -> str:
    """Keep percentile comparisons within one faction and a similar unit role."""
    if not node.get("vehicle_weapons") and node.get("unit_class") == "infantry":
        return "Infantry"
    branches = node.get("branch_types") or []
    if "tanks" in branches:
        return "Tanks and tank destroyers"
    if "recon-vehicles" in branches:
        return "Recon vehicles"
    if node.get("unit_class") in {"artillery", "at-cannon"} or any(
        branch in branches for branch in ("machine-guns", "mortars", "anti-air", "anti-tank-guns")
    ):
        return "Support weapons"
    return "Other armed vehicles"


def summarize_weapons(weapons: list[tuple[dict, int]], cp: float | None) -> dict:
    """Combine quantities within one weapon slot, never across weapon slots."""
    profiles = [(weapon_firepower(weapon), count) for weapon, count in weapons]
    metrics = dict.fromkeys(METRIC_KEYS)
    if profiles:
        for key in ("burst_rounds_5s", "sustained_rpm", "caliber_weighted_rpm"):
            if all(profile[key] is not None for profile, _ in profiles):
                metrics[key] = sum(profile[key] * count for profile, count in profiles)
        if all(profile["firing_endurance_seconds"] is not None for profile, _ in profiles):
            metrics["firing_endurance_seconds"] = min(
                profile["firing_endurance_seconds"] for profile, _ in profiles
            )
        if cp is not None and cp > 0 and metrics["sustained_rpm"] is not None:
            metrics["rounds_per_minute_per_cp"] = metrics["sustained_rpm"] / cp
    metrics["weapon_count"] = sum(count for _, count in weapons)
    metrics["weapons"] = [
        {"name": weapon.get("display_name") or weapon.get("id") or "Unknown weapon", "count": count}
        for weapon, count in weapons
    ]
    metrics["percentiles"] = {}
    return metrics


def annotate_firepower(trees: list[dict]) -> None:
    """Keep primary, secondary and additional weapon output separate."""
    for tree in trees:
        cohorts = defaultdict(list)
        for node in tree["nodes"]:
            slots = {"primary": [], "secondary": []}
            other_weapons = defaultdict(list)
            if node.get("vehicle_weapons"):
                for index, weapon in enumerate(node["vehicle_weapons"]):
                    entry = (weapon, weapon.get("mount_count", 1))
                    if index < 2:
                        slots[("primary", "secondary")[index]].append(entry)
                    else:
                        other_weapons[index].append(entry)
            elif node.get("unit_class") == "infantry" and not (node.get("unit") or {}).get("vehicle"):
                for member in node.get("members") or []:
                    weapons = member.get("weapons") or []
                    if member.get("count", 0) > 0:
                        # An unknown main weapon must not silently lower the primary score.
                        slots["primary"].append((weapons[0] if weapons else {}, member["count"]))
                        if len(weapons) > 1:
                            slots["secondary"].append((weapons[1], member["count"]))
                        for index, weapon in enumerate(weapons[2:], start=2):
                            identity = weapon.get("id") or weapon.get("display_name") or index
                            other_weapons[identity].append((weapon, member["count"]))

            cp = (node.get("unit") or {}).get("cp")
            group = firepower_group(node)
            node["firepower"] = {"group": group, "other": [
                summarize_weapons(weapons, cp) for weapons in other_weapons.values()
            ]}
            for slot, weapons in slots.items():
                metrics = summarize_weapons(weapons, cp)
                node["firepower"][slot] = metrics
                if weapons:
                    cohorts[(group, slot)].append(metrics)

        for cohort in cohorts.values():
            for key in METRIC_KEYS:
                values = sorted(metrics[key] for metrics in cohort if metrics[key] is not None)
                for metrics in cohort:
                    value = metrics[key]
                    if value is None:
                        continue
                    # Ties share the middle rank; a one-unit cohort has rank 50.
                    less = sum(other < value for other in values)
                    equal = values.count(value)
                    rank = 50 if len(values) == 1 else 100 * (less + (equal - 1) / 2) / (len(values) - 1)
                    metrics["percentiles"][key] = round(rank, 1)
