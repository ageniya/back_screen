import unittest

from robot_back_screen.services.chassis_reset import ChassisResetState


class ResetStateTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.state = ChassisResetState(clock=lambda: self.now)

    def released(self):
        self.state.update_chassis(False, False, 4, '等待复位')
        self.state.update_velocity((0, 0, 0), (0, 0, 0))

    def test_startup_requires_manual_reset_even_if_chassis_is_idle(self):
        self.assertFalse(self.state.view(True, True, True)['resetAllowed'])
        self.state.update_chassis(False, False, 1, '空闲中')
        self.assertEqual(self.state.state, 'E_STOP_RELEASED')
        self.assertIsNone(self.state.sent_sequence)

    def test_press_release_is_driven_by_feedback(self):
        self.state.update_chassis(True, False, 4, '等待复位 (急停中)')
        self.assertEqual(self.state.state, 'E_STOP_ACTIVE')
        self.assertIn('释放急停', self.state.block_reason())
        self.released()
        self.assertEqual(self.state.state, 'E_STOP_RELEASED')

    def test_rotation_and_missing_velocity_prevent_reset(self):
        self.state.update_chassis(False, False, 4, '等待复位')
        self.assertIn('速度', self.state.block_reason())
        self.state.update_velocity((0, 0, 0), (0, 0, .01))
        self.assertEqual(self.state.block_reason(), '机器人未静止')

    def test_collision_feedback_does_not_add_a_reset_condition_to_fr02(self):
        self.released()
        self.state.update_chassis(False, True, 4, '等待复位')
        self.assertTrue(self.state.collision)
        self.assertTrue(self.state.view(True, True, True)['resetAllowed'])
        token = self.state.begin()
        self.state.mark_sent(token)
        self.assertEqual(self.state.state, 'RESET_REQUESTED')

    def test_nan_and_stale_speed_prevent_reset(self):
        self.released()
        self.state.update_velocity((float('nan'), 0, 0), (0, 0, 0))
        self.assertIsNotNone(self.state.block_reason())
        self.released()
        self.now = 4
        self.state.update_chassis(False, False, 4, '等待复位')
        self.assertIn('速度', self.state.block_reason())

    def test_request_is_single_and_needs_new_feedback_after_send(self):
        self.released()
        token = self.state.begin()
        with self.assertRaises(RuntimeError):
            self.state.begin()
        self.state.update_chassis(False, False, 1, '空闲中')
        self.assertEqual(self.state.state, 'RESET_REQUESTED')
        self.state.mark_sent(token)
        self.state.update_chassis(False, False, 4, '等待复位')
        self.assertEqual(self.state.state, 'RESET_REQUESTED')
        self.state.update_chassis(False, False, 1, '空闲中')
        self.assertEqual(self.state.state, 'RESET_DONE')
        self.assertFalse(self.state.view(True, True, True)['resetAllowed'])

    def test_pre_ack_feedback_is_not_reset_success(self):
        self.released()
        token = self.state.begin()
        self.state.mark_sent(token, require_ack=True)
        self.state.update_chassis(False, False, 1, '空闲中')
        self.assertEqual(self.state.state, 'RESET_REQUESTED')
        self.state.accept_response(token)
        self.assertEqual(self.state.state, 'RESET_REQUESTED')
        self.state.update_chassis(False, False, 1, '空闲中')
        self.assertEqual(self.state.state, 'RESET_DONE')

    def test_other_fault_latches_until_feedback_confirms_fault_cleared(self):
        self.released()
        token = self.state.begin()
        self.state.mark_sent(token)
        self.state.update_chassis(False, False, 4, '驱动故障')
        self.assertEqual(self.state.state, 'E_STOP_ACTIVE')
        self.state.update_chassis(False, False, 4, '驱动故障')
        self.assertEqual(self.state.state, 'E_STOP_ACTIVE')
        self.state.update_chassis(False, False, 1, '空闲中')
        self.assertEqual(self.state.state, 'E_STOP_RELEASED')
        self.assertIn('重新点击复位', self.state.error)

    def test_timeout_allows_manual_retry_only_with_fresh_feedback(self):
        self.released()
        self.state.begin()
        self.now = 11
        self.state.update_chassis(False, False, 4, '等待复位')
        self.state.update_velocity((0, 0, 0), (0, 0, 0))
        self.assertEqual(self.state.state, 'E_STOP_RELEASED')
        self.assertIn('超时', self.state.error)
        self.assertTrue(self.state.view(True, True, True)['resetAllowed'])

    def test_disconnect_during_reset_stays_pending_until_timeout(self):
        self.released()
        self.state.begin()
        self.now = 4
        self.assertEqual(self.state.view(True, True, True)['state'], 'RESET_REQUESTED')
        self.now = 11
        self.assertEqual(self.state.view(True, True, True)['state'], 'E_STOP_ACTIVE')
        self.assertFalse(self.state.view(True, True, True)['resetAllowed'])

    def test_estop_during_prepare_invalidates_request(self):
        self.released()
        token = self.state.begin()
        self.state.update_chassis(True, False, 4, '等待复位 (急停中)')
        with self.assertRaises(RuntimeError):
            self.state.mark_sent(token)
        self.assertEqual(self.state.state, 'E_STOP_ACTIVE')

    def test_interlock_unavailable_is_not_a_successful_reset(self):
        self.released()
        view = self.state.view(False, True, True)
        self.assertEqual(view['state'], 'E_STOP_RELEASED')
        self.assertFalse(view['resetAllowed'])
        self.assertIn('主控运动联锁', view['blockReason'])

    def test_reports_all_blockers_instead_of_hiding_disabled_controls(self):
        self.released()
        view = self.state.view(False, False, True)
        self.assertTrue(view['checks']['stationary'])
        self.assertTrue(view['checks']['stateAllowsReset'])
        self.assertFalse(view['checks']['motionInterlockReady'])
        self.assertFalse(view['checks']['controlsEnabled'])
        self.assertEqual(len(view['blockReasons']), 2)


if __name__ == '__main__':
    unittest.main()
