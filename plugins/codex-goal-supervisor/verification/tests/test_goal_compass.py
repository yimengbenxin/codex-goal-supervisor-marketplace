from __future__ import annotations

import importlib
import sys
import unittest


TEST_MODULES = [
    "verification.tests.test_acceptance",
    "verification.tests.test_validation_status",
    "verification.tests.test_request_gate",
    "verification.tests.test_janitor",
    "verification.tests.test_goal_detect",
    "verification.tests.test_onboard_scan",
    "verification.tests.test_install",
    "verification.tests.test_plugin_auto_update",
    "verification.tests.test_release_editions",
    "verification.tests.test_performance",
    "verification.tests.test_status",
    "verification.tests.test_mdcp",
    "verification.tests.test_plugin_hook",
    "verification.tests.test_runtime_contracts",
    "verification.tests.test_parallel_tickets",
    "verification.tests.test_state_concurrency",
    "verification.tests.test_execution_supervisor_feedback",
    "verification.tests.test_feedback_and_reuse",
    "verification.tests.test_feedback_receiver",
    "verification.tests.test_v2_tool_mode",
    "verification.tests.test_convergence",
    "verification.tests.test_context_continuity",
    "verification.tests.test_goal_return",
    "verification.tests.test_deviation_incidents",
    "verification.tests.test_agency_role_pack",
    "verification.tests.test_cross_domain_benchmark",
    "verification.tests.test_long_run_industry_stress",
    "verification.tests.test_packaging_manufacturing_stress",
]


def load_tests(loader: unittest.TestLoader, _: unittest.TestSuite, __: str | None) -> unittest.TestSuite:
    if "discover" in sys.argv:
        return unittest.TestSuite()
    suite = unittest.TestSuite()
    for module_name in TEST_MODULES:
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(module_name)))
    return suite


if __name__ == "__main__":
    unittest.main()
