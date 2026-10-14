import unittest

from robot_back_screen.services.runtime_metrics import BatteryRuntimeEstimator


class RuntimeEstimatorTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.estimator = BatteryRuntimeEstimator(clock=lambda: self.now)

    def sample(self, seconds, remaining=12, current=2, status=0):
        self.now = seconds
        self.estimator.observe(remaining, current, status)

    def test_warmup_average_and_capacity(self):
        self.sample(0, current=1)
        self.assertIsNone(self.estimator.estimate()[0])
        self.sample(5, current=3)
        minutes, info = self.estimator.estimate()
        self.assertEqual(minutes, 360)
        self.assertEqual(info['averageCurrentA'], 2)

    def test_charging_and_no_capacity_do_not_return_runtime(self):
        self.sample(0)
        self.sample(5)
        self.sample(6, status=1)
        self.assertIsNone(self.estimator.estimate()[0])
        self.sample(7, remaining=None)
        self.assertIsNone(self.estimator.estimate()[0])

    def test_stale_data_and_reconnect_need_new_samples(self):
        self.sample(0)
        self.sample(5)
        self.now = 11
        self.assertIsNone(self.estimator.estimate()[0])
        self.sample(11)
        self.assertIsNone(self.estimator.estimate()[0])

    def test_discharge_direction_and_empty_battery(self):
        self.sample(0, current=-2, status=2)
        self.sample(5, current=-2, status=2)
        self.assertEqual(self.estimator.estimate()[0], 360)
        self.sample(6, remaining=0, current=-2, status=2)
        self.assertEqual(self.estimator.estimate()[0], 0)

    def test_time_weighted_window(self):
        self.estimator = BatteryRuntimeEstimator(window_seconds=10, clock=lambda: self.now)
        self.sample(0, remaining=10, current=1)
        self.sample(5, remaining=10, current=1)
        self.sample(10, remaining=10, current=3)
        self.sample(15, remaining=10, current=3)
        self.assertEqual(self.estimator.estimate()[0], 240)


if __name__ == '__main__':
    unittest.main()
