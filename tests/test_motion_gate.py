import unittest

from robot_back_screen.services.motion_gate import MotionGate


class MotionGateTests(unittest.TestCase):
    def test_startup_drops_commands_without_buffering(self):
        gate = MotionGate()
        self.assertFalse(gate.accept_velocity([1, 0, 0, 0, 0, 0]))
        self.assertEqual(gate.target_velocity, [0] * 6)
        self.assertEqual(gate.status()['queuedCommands'], 0)

    def test_reset_latches_target_zero_and_interrupts_active_tasks(self):
        gate = MotionGate()
        gate.confirm_new_task(True, True, set())
        self.assertTrue(gate.accept_velocity([.2, 0, 0, 0, 0, 0]))
        gate.observe_goals([('goal1', 2), ('goal2', 1)])
        gate.latch('reset')
        self.assertEqual(gate.target_velocity, [0] * 6)
        self.assertEqual(gate.interrupted_goals, {'goal1', 'goal2'})
        self.assertTrue(all(t['state'] == '已中断，需重新确认' for t in gate.tasks.values()))
        self.assertFalse(gate.accept_velocity([1, 0, 0, 0, 0, 0]))

    def test_new_automatic_goals_during_lock_are_not_allowed_to_move(self):
        gate = MotionGate()
        gate.observe_goals([('new-goal', 2)])
        self.assertIn('new-goal', gate.interrupted_goals)
        self.assertFalse(gate.accept_velocity([.1, 0, 0, 0, 0, 0]))

    def test_reset_done_does_not_implicitly_confirm_a_task(self):
        gate = MotionGate()
        self.assertFalse(gate.accept_velocity([.1, 0, 0, 0, 0, 0]))
        for done, still, active in [(False, True, set()), (True, False, set()), (True, True, {'old'})]:
            with self.assertRaises(RuntimeError):
                gate.confirm_new_task(done, still, active)
        gate.confirm_new_task(True, True, set())
        self.assertTrue(gate.accept_velocity([.1, 0, 0, 0, 0, 0]))
        self.assertFalse(gate.accept_velocity([float('nan'), 0, 0, 0, 0, 0]))
