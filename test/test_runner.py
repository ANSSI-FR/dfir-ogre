import multiprocessing
import time
from unittest import TestCase

from ogre.runner import _run_process_with_timeout


def _append_success(result):
    result.append("ok")


def _produce_no_result(result):
    return None


def _sleep_too_long(result):
    time.sleep(2)


class TestRunner(TestCase):
    def test_run_process_with_timeout_returns_success_result(self):
        with multiprocessing.Manager() as manager:
            result = _run_process_with_timeout(_append_success, (), 1, manager)

        self.assertEqual(result, "ok")

    def test_run_process_with_timeout_reports_missing_result(self):
        with multiprocessing.Manager() as manager:
            with self.assertRaisesRegex(Exception, "crashed"):
                _run_process_with_timeout(_produce_no_result, (), 1, manager)

    def test_run_process_with_timeout_reports_timeout(self):
        with multiprocessing.Manager() as manager:
            with self.assertRaisesRegex(Exception, "timed out"):
                _run_process_with_timeout(_sleep_too_long, (), 0.1, manager)
