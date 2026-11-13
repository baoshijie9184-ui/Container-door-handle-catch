"""Resource-gate contract; executed only by ECS source validation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("observability_preflight", Path(__file__).resolve().parents[1] / "deploy/observability/resource_preflight.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class ResourcePreflightTests(unittest.TestCase):
    def test_current_16_gib_cannot_be_claimed_full_production(self):
        result = gate.decide("production", "production-reviewed", 16*gate.GIB, 14*gate.GIB, 50*gate.GIB, 0)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("total_memory", result["failedGates"])
        self.assertFalse(result["productionCapacityVerified"])

    def test_business_reserve_is_added_not_overwritten(self):
        result = gate.decide("production", "production-reviewed", 64*gate.GIB, 40*gate.GIB, 35*gate.GIB, 10*gate.GIB)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["requiredBytes"]["free_disk"], 40*gate.GIB)

    def test_smoke_requires_separate_approval_and_is_not_production_evidence(self):
        result = gate.decide("isolated-smoke", "production-reviewed", 16*gate.GIB, 8*gate.GIB, 20*gate.GIB, 0)
        self.assertEqual(result["failedGates"], ["approval"])
        result = gate.decide("isolated-smoke", "isolated-smoke-reviewed", 16*gate.GIB, 8*gate.GIB, 20*gate.GIB, 0)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["productionCapacityVerified"])

    def test_budget_boundary_is_exact(self):
        result = gate.decide("production", "production-reviewed", 32*gate.GIB, 24*gate.GIB, 30*gate.GIB, 0)
        self.assertEqual(result["status"], "PASS")
        result = gate.decide("production", "production-reviewed", 32*gate.GIB, 24*gate.GIB, 30*gate.GIB-1, 0)
        self.assertEqual(result["failedGates"], ["free_disk"])

    def test_invalid_mode_and_negative_reserve_rejected(self):
        for mode,reserve in (("auto",0),("production",-1)):
            with self.assertRaises(ValueError):
                gate.decide(mode, "", 0, 0, 0, reserve)
