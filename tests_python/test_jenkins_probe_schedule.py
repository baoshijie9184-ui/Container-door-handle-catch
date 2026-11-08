"""Fixture collector cadence contracts; execute only on the admitted ECS."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


MODULE = Path(__file__).resolve().parents[1] / 'script/jenkins/prepare-compact-fixtures.py'
SPEC = importlib.util.spec_from_file_location('fixture_probe_schedule_preparer', MODULE)
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FakeStop:
    def __init__(self, clock):
        self.clock = clock
        self.stopped = False
        self.waits = []

    def wait(self, duration):
        if duration < 0:
            raise AssertionError('Negative event wait')
        self.waits.append(duration)
        if self.stopped:
            return True
        self.clock.now += duration
        return False


class ProbeScheduleTests(unittest.TestCase):
    def make_monitor(self, durations):
        clock = FakeClock()
        stop = FakeStop(clock)
        starts = []
        monitor = preparer.PreparationMonitor.__new__(preparer.PreparationMonitor)
        monitor.stop = stop
        monitor.fail = Mock()

        def measure():
            starts.append(clock.now)
            clock.now += durations[len(starts) - 1]
            if len(starts) == len(durations):
                stop.stopped = True

        monitor.measure = Mock(side_effect=measure)
        return monitor, clock, stop, starts

    def collect(self, monitor, clock):
        with patch.object(preparer, 'time', SimpleNamespace(monotonic=clock.monotonic)):
            monitor.collect()

    def assert_times(self, expected, actual):
        self.assertEqual(len(expected), len(actual))
        for left, right in zip(expected, actual):
            self.assertAlmostEqual(left, right)

    def test_fast_probe_waits_only_remainder_of_start_cadence(self):
        monitor, clock, stop, starts = self.make_monitor([0.05, 0.05])
        self.collect(monitor, clock)
        self.assert_times([0.5, 1.0], starts)
        self.assert_times([0.5, 0.45, 0.45], stop.waits)
        monitor.fail.assert_not_called()

    def test_slow_probe_has_no_additional_half_second_wait(self):
        monitor, clock, stop, starts = self.make_monitor([0.8, 0.8])
        self.collect(monitor, clock)
        self.assert_times([0.5, 1.3], starts)
        self.assert_times([0.5, 0.0, 0.0], stop.waits)
        self.assertEqual(2, monitor.measure.call_count)

    def test_slow_probe_does_not_accumulate_catch_up_runs(self):
        monitor, clock, stop, starts = self.make_monitor([1.7, 0.05, 0.05])
        self.collect(monitor, clock)
        self.assert_times([0.5, 2.2, 2.7], starts)
        self.assert_times([0.5, 0.0, 0.45, 0.45], stop.waits)
        monitor.fail.assert_not_called()

    def test_stop_is_observed_even_when_next_wait_is_zero(self):
        monitor, clock, stop, starts = self.make_monitor([0.8])
        self.collect(monitor, clock)
        self.assert_times([0.5], starts)
        self.assert_times([0.5, 0.0], stop.waits)
        self.assertEqual(1, monitor.measure.call_count)
        monitor.fail.assert_not_called()

    def test_measurement_exception_still_fails_as_collector(self):
        monitor, clock, stop, starts = self.make_monitor([0.05])
        error = KeyboardInterrupt('synthetic collector interruption')
        monitor.measure.side_effect = error
        self.collect(monitor, clock)
        monitor.fail.assert_called_once_with(error, worker='collector')
        self.assert_times([0.5], stop.waits)
        self.assertEqual([], starts)


if __name__ == '__main__':
    unittest.main()
