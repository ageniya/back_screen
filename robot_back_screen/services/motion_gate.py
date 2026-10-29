"""Motion ownership state. Caller holds the supervisor lock for every mutation."""

import math


class MotionGate:
    def __init__(self):
        # Never restore an open gate from disk after a process restart.
        self.locked = True
        self.reason = "上电等待人工复位"
        self.target_velocity = [0.0] * 6
        self.tasks = {}
        self.interrupted_goals = set()
        self.dropped_commands = 0
        self.needs_confirmation = True

    def observe_goals(self, statuses):
        for goal_id, status in statuses:
            record = self.tasks.setdefault(goal_id, {"id": goal_id})
            record["actionStatus"] = int(status)
            if self.locked and status in (1, 2, 3):
                record["state"] = "已中断，需重新确认"
                self.interrupted_goals.add(goal_id)
            elif status in (4, 5, 6):
                record.setdefault("state", "已结束")
        # Bounded diagnostic record; never an executable task queue.
        if len(self.tasks) > 100:
            self.tasks = dict(list(self.tasks.items())[-100:])

    def latch(self, reason):
        self.locked = True
        self.reason = reason
        self.needs_confirmation = True
        self.target_velocity = [0.0] * 6
        for goal_id, record in self.tasks.items():
            if record.get("actionStatus") in (1, 2, 3):
                record["state"] = "已中断，需重新确认"
                self.interrupted_goals.add(goal_id)

    def confirm_new_task(self, reset_done, stationary, active_goals):
        if not reset_done or not stationary or active_goals:
            raise RuntimeError("需先完成复位、确认静止并结束旧任务")
        self.locked = False
        self.reason = "已人工确认新任务"
        self.needs_confirmation = False
        self.target_velocity = [0.0] * 6

    def accept_velocity(self, values):
        valid = all(isinstance(v, (float, int)) and math.isfinite(v) for v in values)
        if self.locked or not valid:
            self.dropped_commands += 1
            return False
        self.target_velocity = list(values)
        return True

    def status(self):
        return {"locked": self.locked, "reason": self.reason,
                "targetVelocity": list(self.target_velocity), "queuedCommands": 0,
                "taskReconfirmationRequired": self.needs_confirmation,
                "droppedCommands": self.dropped_commands,
                "tasks": list(self.tasks.values())}
