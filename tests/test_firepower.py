"""Check timing, unit composition, unknown data, and relative rankings."""

import unittest

from firepower import annotate_firepower, weapon_firepower


def weapon(rate=60, capacity=3, reload_time=2, caliber=7.62, mounts=1):
    return {
        "rate_of_fire_rpm": rate, "rounds_before_reload": capacity,
        "reload_time_seconds": reload_time, "caliber_mm": caliber,
        "mount_count": mounts,
    }


def infantry(count=1, weapons=None, cp=2):
    return {
        "unit_class": "infantry", "unit": {"cp": cp},
        "members": [{"count": count, "weapons": weapons if weapons is not None else [weapon()]}],
    }


class FirepowerTests(unittest.TestCase):
    def test_burst_includes_reloads_and_excludes_shot_at_window_end(self):
        # Shots at 0, 1, 2, 4, 5: the fifth shot is outside [0, 5).
        metrics = weapon_firepower(weapon())
        self.assertEqual(metrics["burst_rounds_5s"], 4)
        self.assertEqual(metrics["sustained_rpm"], 45)
        self.assertEqual(metrics["firing_endurance_seconds"], 2)

    def test_single_shot_gun(self):
        metrics = weapon_firepower(weapon(rate=15, capacity=1, reload_time=4, caliber=40))
        self.assertEqual(metrics["burst_rounds_5s"], 2)
        self.assertEqual(metrics["sustained_rpm"], 15)
        self.assertEqual(metrics["firing_endurance_seconds"], 0)

    def test_reload_cannot_exceed_cyclic_fire_rate(self):
        metrics = weapon_firepower(weapon(rate=120, capacity=1, reload_time=0))
        self.assertEqual(metrics["sustained_rpm"], 120)
        self.assertEqual(metrics["burst_rounds_5s"], 10)

    def test_missing_reload_keeps_burst_when_magazine_lasts_long_enough(self):
        metrics = weapon_firepower(weapon(rate=60, capacity=10, reload_time=None))
        self.assertEqual(metrics["burst_rounds_5s"], 5)
        self.assertIsNone(metrics["sustained_rpm"])

    def test_missing_reload_makes_reloading_burst_unknown(self):
        self.assertIsNone(weapon_firepower(weapon(reload_time=None))["burst_rounds_5s"])

    def test_missing_rate_or_capacity_does_not_become_zero(self):
        self.assertIsNone(weapon_firepower(weapon(rate=None))["burst_rounds_5s"])
        self.assertIsNone(weapon_firepower(weapon(capacity=0))["sustained_rpm"])

    def test_caliber_weighting_is_linear_and_missing_caliber_is_unknown(self):
        self.assertAlmostEqual(weapon_firepower(weapon(caliber=15.24))["caliber_weighted_rpm"], 90)
        self.assertIsNone(weapon_firepower(weapon(caliber=None))["caliber_weighted_rpm"])

    def test_squad_quantities_and_main_weapon_only(self):
        node = infantry(count=3, weapons=[weapon(), weapon(rate=900)], cp=6)
        annotate_firepower([{"nodes": [node]}])
        self.assertEqual(node["firepower"]["burst_rounds_5s"], 12)
        self.assertEqual(node["firepower"]["sustained_rpm"], 135)
        self.assertEqual(node["firepower"]["rounds_per_minute_per_cp"], 22.5)
        self.assertEqual(node["firepower"]["firing_endurance_seconds"], 2)

    def test_vehicle_counts_mounts_and_excludes_crew_weapons(self):
        node = infantry(count=5)
        node["vehicle_weapons"] = [weapon(mounts=2)]
        annotate_firepower([{"nodes": [node]}])
        self.assertEqual(node["firepower"]["weapon_count"], 2)
        self.assertEqual(node["firepower"]["sustained_rpm"], 90)

    def test_zero_cp_has_no_efficiency_score(self):
        node = infantry(cp=0)
        annotate_firepower([{"nodes": [node]}])
        self.assertIsNone(node["firepower"]["rounds_per_minute_per_cp"])

    def test_missing_member_weapon_does_not_silently_reduce_score(self):
        node = infantry()
        node["members"].append({"count": 1, "weapons": []})
        annotate_firepower([{"nodes": [node]}])
        self.assertIsNone(node["firepower"]["sustained_rpm"])

    def test_percentiles_handle_ties_and_stay_within_faction_and_role(self):
        low, tied, high = infantry(), infantry(), infantry(count=2)
        vehicle = {"unit_class": "tanks", "branch_types": ["tanks"], "vehicle_weapons": [weapon()]}
        other_faction = infantry(count=20)
        annotate_firepower([{"nodes": [low, tied, high, vehicle]}, {"nodes": [other_faction]}])
        for node in (low, tied):
            self.assertEqual(node["firepower"]["percentiles"]["sustained_rpm"], 25)
        self.assertEqual(high["firepower"]["percentiles"]["sustained_rpm"], 100)
        self.assertEqual(vehicle["firepower"]["percentiles"]["sustained_rpm"], 50)
        self.assertEqual(other_faction["firepower"]["percentiles"]["sustained_rpm"], 50)

    def test_unarmed_object_is_unknown(self):
        node = {"unit_class": "other", "unit": {"cp": 2}}
        annotate_firepower([{"nodes": [node]}])
        self.assertIsNone(node["firepower"]["sustained_rpm"])
        self.assertEqual(node["firepower"]["percentiles"], {})


if __name__ == "__main__":
    unittest.main()
