"""Deletion endpoints operate on isolated files without model or service calls."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "policy_deletion_server", Path(__file__).resolve().parents[1] / "index_server.py"
)
assert SPEC is not None and SPEC.loader is not None
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class PolicyDeletionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        for name, filename in (
            ("POLICY", "policy.json"),
            ("POLICY_SETS", "policy_sets.json"),
            ("POLICY_CACHE", "policy_cache.json"),
        ):
            replacement = patch.object(server, name, root / filename)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.first = {
            "id": 1, "title": "Term", "instruction": "Limit the term.",
            "policySet": "NDA", "tags": ["term"], "severity": 2,
            "custom": {"retain": True},
        }
        self.second = {
            "id": 7, "title": "Liability", "instruction": "Cap liability.",
            "policySet": "Services", "groups": ["All"], "extra": "preserve",
        }
        self.write(server.POLICY, [self.first, self.second])
        self.write(server.POLICY_SETS, ["NDA", "Services", "Empty"])
        self.write(server.POLICY_CACHE, {"cached": "old vectors"})

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def post(self, route, body):
        encoded = json.dumps(body).encode("utf-8")
        handler = server.Handler.__new__(server.Handler)
        handler.path = route
        handler.server = SimpleNamespace(server_port=8084)
        handler.headers = {"Content-Length": str(len(encoded)), "Host": "localhost:3000", "Origin": "https://localhost:3000", "Content-Type": "application/json"}
        handler.rfile = io.BytesIO(encoded)
        handler.send_json = Mock()
        handler.do_POST()
        handler.send_json.assert_called_once()
        return handler.send_json.call_args.args

    def test_delete_policy_preserves_other_records_and_invalidates_cache(self):
        # The legacy value wrapper is accepted by the existing policies API.
        self.write(server.POLICY, {"value": [self.first, self.second]})
        sets_before = server.POLICY_SETS.read_bytes()
        status, result = self.post("/policies/delete", {"policy": self.first})
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertTrue(result["cacheInvalidated"])
        self.assertEqual(server.load_json(server.POLICY, []), [self.second])
        self.assertEqual(server.POLICY_SETS.read_bytes(), sets_before)
        self.assertFalse(server.POLICY_CACHE.exists())

    def test_stale_policy_object_is_rejected_without_deleting_newer_data(self):
        changed = dict(self.first, instruction="A newer rule.")
        self.write(server.POLICY, [changed, self.second])
        before = server.POLICY.read_bytes()
        status, _ = self.post("/policies/delete", {"policy": self.first})
        self.assertEqual(status, 409)
        self.assertEqual(server.POLICY.read_bytes(), before)
        self.assertTrue(server.POLICY_CACHE.exists())

    def test_duplicate_full_objects_are_rejected(self):
        self.write(server.POLICY, [self.first, copy.deepcopy(self.first), self.second])
        before = server.POLICY.read_bytes()
        status, _ = self.post("/policies/delete", {"policy": self.first})
        self.assertEqual(status, 409)
        self.assertEqual(server.POLICY.read_bytes(), before)

    def test_delete_checks_full_object_not_only_id(self):
        partial = {"id": self.first["id"]}
        status, _ = self.post("/policies/delete", {"policy": partial})
        self.assertEqual(status, 409)
        self.assertEqual(len(server.load_json(server.POLICY, [])), 2)

    def test_policy_payload_requires_object(self):
        for body in ({}, {"policy": None}, {"policy": []}, {"policy": "Term"}):
            with self.subTest(body=body):
                status, _ = self.post("/policies/delete", body)
                self.assertEqual(status, 400)

    def test_empty_policy_set_can_be_deleted_without_changing_policies(self):
        policy_before = server.POLICY.read_bytes()
        cache_before = server.POLICY_CACHE.read_bytes()
        status, result = self.post("/policy-sets/delete", {"name": "Empty"})
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        self.assertEqual(server.load_json(server.POLICY_SETS, []), ["NDA", "Services"])
        self.assertEqual(server.POLICY.read_bytes(), policy_before)
        self.assertEqual(server.POLICY_CACHE.read_bytes(), cache_before)

    def test_last_empty_set_can_be_deleted_and_stays_empty(self):
        self.write(server.POLICY, [])
        self.write(server.POLICY_SETS, ["Last"])
        status, _ = self.post("/policy-sets/delete", {"name": "Last"})
        self.assertEqual(status, 200)
        self.assertEqual(server.get_policy_sets(), [])

    def test_nonempty_set_is_rejected(self):
        before = server.POLICY_SETS.read_bytes()
        status, result = self.post("/policy-sets/delete", {"name": "NDA"})
        self.assertEqual(status, 409)
        self.assertIn("policies", result["error"].lower())
        self.assertEqual(server.POLICY_SETS.read_bytes(), before)

    def test_implicit_general_policies_prevent_set_deletion(self):
        for marker in ("missing", "", "   ", None):
            with self.subTest(policy_set=marker):
                policy = dict(self.first)
                if marker == "missing":
                    policy.pop("policySet")
                else:
                    policy["policySet"] = marker
                self.write(server.POLICY, [policy])
                self.write(server.POLICY_SETS, ["General Policies", "Empty"])
                status, _ = self.post("/policy-sets/delete", {"name": "General Policies"})
                self.assertEqual(status, 409)
                self.assertIn("General Policies", server.get_policy_sets())

    def test_missing_set_is_rejected(self):
        status, _ = self.post("/policy-sets/delete", {"name": "Missing"})
        self.assertEqual(status, 409)

    def test_policy_set_payload_requires_nonempty_name(self):
        for body in ({}, {"name": None}, {"name": []}, {"name": " "}):
            with self.subTest(body=body):
                status, _ = self.post("/policy-sets/delete", body)
                self.assertEqual(status, 400)

    def test_latest_policy_file_prevents_deleting_previously_empty_set(self):
        self.assertIn("Empty", server.get_policy_sets())
        self.write(server.POLICY, [self.first, self.second, dict(self.first, policySet="Empty")])
        status, _ = self.post("/policy-sets/delete", {"name": "Empty"})
        self.assertEqual(status, 409)
        self.assertIn("Empty", server.get_policy_sets())

    def test_set_deletion_waits_for_policy_save_and_checks_its_latest_result(self):
        save_entered = Event()
        allow_save = Event()
        deletion_finished = Event()
        results = {}
        real_save = server.save_json_atomic

        def delayed_save(path, value):
            if path == server.POLICY:
                save_entered.set()
                if not allow_save.wait(2):
                    raise RuntimeError("Test did not release the policy save")
            real_save(path, value)

        def save_policy():
            results["save"] = self.post("/policies", {
                "policies": [dict(self.first, policySet="Empty")]
            })

        def delete_set():
            results["delete"] = self.post("/policy-sets/delete", {"name": "Empty"})
            deletion_finished.set()

        save_thread = Thread(target=save_policy)
        delete_thread = Thread(target=delete_set)
        with patch.object(server, "save_json_atomic", side_effect=delayed_save):
            save_thread.start()
            try:
                self.assertTrue(save_entered.wait(2))
                delete_thread.start()
                self.assertFalse(deletion_finished.wait(0.05))
            finally:
                allow_save.set()
                save_thread.join(2)
                if delete_thread.ident is not None:
                    delete_thread.join(2)

        self.assertFalse(save_thread.is_alive())
        self.assertFalse(delete_thread.is_alive())
        self.assertEqual(results["save"][0], 200)
        self.assertEqual(results["delete"][0], 409)
        self.assertIn("Empty", server.get_policy_sets())

    def test_failed_atomic_delete_write_preserves_file(self):
        for route, body, path in (
            ("/policies/delete", {"policy": self.first}, server.POLICY),
            ("/policy-sets/delete", {"name": "Empty"}, server.POLICY_SETS),
        ):
            with self.subTest(route=route):
                before = path.read_bytes()
                with patch.object(server.os, "replace", side_effect=OSError("disk unavailable")):
                    status, _ = self.post(route, body)
                self.assertEqual(status, 500)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_cache_invalidation_failure_does_not_partially_delete_policy(self):
        before = server.POLICY.read_bytes()
        real_unlink = Path.unlink

        def fail_cache_unlink(path, *args, **kwargs):
            if path == server.POLICY_CACHE:
                raise PermissionError("Cache cannot be replaced")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_cache_unlink):
            status, _ = self.post("/policies/delete", {"policy": self.first})
        self.assertEqual(status, 500)
        self.assertEqual(server.POLICY.read_bytes(), before)

    def test_existing_set_save_accepts_empty_list_only_without_policies(self):
        before = server.POLICY_SETS.read_bytes()
        status, _ = self.post("/policy-sets", {"policySets": []})
        self.assertEqual(status, 400)
        self.assertEqual(server.POLICY_SETS.read_bytes(), before)
        self.write(server.POLICY, [])
        status, _ = self.post("/policy-sets", {"policySets": []})
        self.assertEqual(status, 200)
        self.assertEqual(server.get_policy_sets(), [])

    def test_existing_set_save_keeps_implicit_general_reference(self):
        policy = dict(self.first)
        policy.pop("policySet")
        self.write(server.POLICY, [policy])
        status, result = self.post("/policy-sets", {"policySets": ["Other"]})
        self.assertEqual(status, 400)
        self.assertEqual(result["policySetsInUse"], ["General Policies"])

    def test_policy_save_rejects_a_set_deleted_after_editor_was_opened(self):
        status, _ = self.post("/policy-sets/delete", {"name": "Empty"})
        self.assertEqual(status, 200)
        policy_before = server.POLICY.read_bytes()
        cache_before = server.POLICY_CACHE.read_bytes()

        status, result = self.post("/policies", {
            "policies": [self.first, self.second, dict(self.first, policySet="Empty")]
        })

        self.assertEqual(status, 409)
        self.assertIn("refresh", result["error"].lower())
        self.assertEqual(server.POLICY.read_bytes(), policy_before)
        self.assertEqual(server.POLICY_CACHE.read_bytes(), cache_before)

    def test_policy_save_resolves_implicit_general_before_checking_existing_sets(self):
        for marker in ("missing", "", "   ", None):
            with self.subTest(policy_set=marker):
                policy = dict(self.first)
                if marker == "missing":
                    policy.pop("policySet")
                else:
                    policy["policySet"] = marker
                self.write(server.POLICY_SETS, ["NDA", "Services"])
                self.write(server.POLICY_CACHE, {"cached": "old vectors"})
                policy_before = server.POLICY.read_bytes()
                cache_before = server.POLICY_CACHE.read_bytes()

                status, _ = self.post("/policies", {"policies": [policy]})
                self.assertEqual(status, 409)
                self.assertEqual(server.POLICY.read_bytes(), policy_before)
                self.assertEqual(server.POLICY_CACHE.read_bytes(), cache_before)

                self.write(server.POLICY_SETS, ["NDA", "Services", "General Policies"])
                status, _ = self.post("/policies", {"policies": [policy]})
                self.assertEqual(status, 200)

    def test_empty_policy_save_is_allowed_with_no_policy_sets(self):
        self.write(server.POLICY, [])
        self.write(server.POLICY_SETS, [])
        status, _ = self.post("/policies", {"policies": []})
        self.assertEqual(status, 200)
        self.assertEqual(server.load_policies(), [])
        self.assertEqual(server.get_policy_sets(), [])

    def test_nonempty_set_can_be_renamed_by_register_move_remove_sequence(self):
        status, _ = self.post("/policy-sets", {
            "policySets": ["NDA", "Services", "Empty", "New NDA"]
        })
        self.assertEqual(status, 200)
        status, _ = self.post("/policies", {
            "policies": [dict(self.first, policySet="New NDA"), self.second]
        })
        self.assertEqual(status, 200)
        status, _ = self.post("/policy-sets", {
            "policySets": ["New NDA", "Services", "Empty"]
        })
        self.assertEqual(status, 200)
        self.assertEqual(server.get_policy_sets(), ["New NDA", "Services", "Empty"])
        self.assertEqual(server.load_policies()[0]["policySet"], "New NDA")
        self.assertEqual(server.load_policies()[0]["instruction"], self.first["instruction"])


if __name__ == "__main__":
    unittest.main()
