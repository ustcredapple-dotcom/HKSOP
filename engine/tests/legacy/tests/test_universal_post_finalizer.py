"""Offline policy-baseline resolution; production policy is never modified."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'qa'))
from finalize_universal_post_release import deployment_start_policy, resolve_access_baseline


class FinalizerPolicyBaselineTests(unittest.TestCase):
    def setUp(self):
        self.before = {'capturedAt': '2026-09-28T14:13:56.743558+08:00', 'policy': {'guestAccessEnabled': False, 'revision': 0, 'updatedAt': None}}
        self.current = {'guestAccessEnabled': True, 'revision': 1, 'updatedAt': '2026-09-28T06:19:43.598Z'}
        self.deployment = {'created_at': '2026-09-28T14:20:35.714571+08:00',
                           'access_verification': {'guest_access_enabled': True, 'policy_revision': 1, 'production_settings_changed_by_verification': False}}

    def test_predeployment_change_preserves_original_snapshot_and_reports_both_policies(self):
        original = copy.deepcopy(self.before)
        startup = {'policy': dict(self.current), 'path': 'read-only-backup', 'sha256': 'proof'}
        result = resolve_access_baseline(self.before, self.deployment, self.current, startup)
        self.assertEqual(self.before, original)
        self.assertEqual(result['capturedBaseline']['revision'], 0)
        self.assertEqual(result['effectiveDeploymentPolicy']['revision'], 1)
        self.assertTrue(result['preDeploymentPolicyChangeObserved'])
        self.assertEqual(result['observedPolicyUpdatedAt'], self.current['updatedAt'])
        self.assertEqual(result['operatorAttribution'], 'not_inferred')
        self.assertTrue(result['originalBaselinePreserved'])
        self.assertFalse(result['productionSettingsChangedByThisScript'])

    def test_unchanged_baseline_keeps_original_policy(self):
        deployment = copy.deepcopy(self.deployment)
        deployment['access_verification'].update(guest_access_enabled=False, policy_revision=0)
        result = resolve_access_baseline(self.before, deployment, self.before['policy'])
        self.assertFalse(result['preDeploymentPolicyChangeObserved'])
        self.assertEqual(result['basis'], 'unchanged_captured_baseline')

    def test_outside_or_equal_interval_and_unzoned_times_are_rejected(self):
        for stamp in ['2026-09-28T06:10:00Z', '2026-09-28T06:13:56.743558Z',
                      '2026-09-28T06:20:35.714571Z', '2026-09-28T06:21:00Z',
                      '2026-09-28T06:19:43', 'not-a-date', None]:
            with self.subTest(stamp=stamp), self.assertRaises(RuntimeError):
                resolve_access_baseline(self.before, self.deployment, {**self.current, 'updatedAt': stamp})
        before = {**self.before, 'capturedAt': '2026-09-28T15:00:00+08:00'}
        with self.assertRaises(RuntimeError):
            resolve_access_baseline(before, self.deployment, self.current)

    def test_deployment_report_mismatch_or_mutation_never_becomes_permission(self):
        for changes in [{'policy_revision': 2}, {'guest_access_enabled': False},
                        {'production_settings_changed_by_verification': True}, {'policy_revision': True}]:
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                deployment = copy.deepcopy(self.deployment)
                deployment['access_verification'].update(changes)
                resolve_access_baseline(self.before, deployment, self.current)
        with self.assertRaises(RuntimeError):
            resolve_access_baseline(self.before, {'created_at': self.deployment['created_at']}, self.current)

    def test_startup_backup_mismatch_rejects_even_plausible_timestamps(self):
        with self.assertRaises(RuntimeError):
            resolve_access_baseline(self.before, self.deployment, self.current, {'policy': self.before['policy']})
        before = copy.deepcopy(self.before)
        before['policy']['revision'] = 1
        with self.assertRaises(RuntimeError):
            resolve_access_baseline(before, self.deployment, self.current)

    def test_policy_changes_after_deployment_are_rejected_even_if_original_baseline_matches_again(self):
        # The deployment report is independently checked in the unchanged path.
        with self.assertRaises(RuntimeError):
            resolve_access_baseline(self.before, self.deployment, self.before['policy'])

    def test_sqlite_startup_snapshot_is_read_without_mutating_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'shared-kits.sqlite3'
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE optics_access_settings(singleton INTEGER,guest_enabled INTEGER,revision INTEGER,updated_at TEXT)')
            connection.execute('INSERT INTO optics_access_settings VALUES(1,1,1,?)', (self.current['updatedAt'],))
            connection.commit(); connection.close()
            original = path.read_bytes()
            record = deployment_start_policy({'backup': temp})
            self.assertEqual(record['policy'], self.current)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(record['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(list(Path(temp).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
