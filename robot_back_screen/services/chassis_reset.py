"""Read-only feedback state machine and guarded chassis reset orchestration.

This module does not own robot motion. The prepare callback must be supplied by
the motion owner and keep its gate closed after reset; no local flag substitutes
for that interlock. Caller serializes access with the telemetry lock.
"""

import math
import time


class ChassisResetState:
    def __init__(self, stale_seconds=3, timeout_seconds=10, clock=time.monotonic):
        if stale_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("复位状态超时必须大于零")
        self.clock = clock
        self.stale_seconds = stale_seconds
        self.timeout_seconds = timeout_seconds
        self.state = None
        self.emergency = None
        self.collision = None
        self.feedback_code = None
        self.feedback_description = ""
        self.feedback_at = None
        self.speed_at = None
        self.stationary = False
        self.sequence = 0
        self.sent_sequence = None
        self.service_accepted = False
        self.requested_at = None
        self.request_id = 0
        self.error = None
        self.fault_locked = False

    def update_chassis(self, emergency, collision, code, description):
        now = self.clock()
        previous_emergency = self.emergency
        self.sequence += 1
        self.feedback_at = now
        self.emergency = emergency
        self.collision = collision
        self.feedback_code = code
        self.feedback_description = str(description).strip()
        if emergency:
            self.request_id += 1
            self.state = "E_STOP_ACTIVE"
            self.requested_at = None
            self.sent_sequence = None
            self.error = None
            self.fault_locked = False
            return
        self.tick()
        if self.state is None or (self.state == "E_STOP_ACTIVE" and not self.fault_locked):
            self.state = "E_STOP_RELEASED"
            self.error = None
        elif self.state == "E_STOP_ACTIVE" and self.fault_locked and code in (0, 1, 2, 3, 5):
            # A cleared chassis fault permits a NEW manual retry. Do not add
            # an undocumented requirement to press/release the physical button again.
            self.fault_locked = False
            self.state = "E_STOP_RELEASED"
            self.error = "底盘故障已解除，请重新点击复位"
        if previous_emergency is True:
            self.fault_locked = False
            self.state = "E_STOP_RELEASED"
        self._check_reset_feedback()

    def _check_reset_feedback(self):
        # 服务回执与状态话题属于不同通道，二者可能以任意顺序到达。
        # 必须同时具备成功回执和发送之后的新鲜反馈，不能复用发送前的状态。
        if (self.state != "RESET_REQUESTED" or self.sent_sequence is None
                or not self.service_accepted or self.sequence <= self.sent_sequence
                or not self.fresh() or self.emergency is not False):
            return
        if self.feedback_code == 4:
            if self.feedback_description != "等待复位":
                self.fail("复位失败，请检查底盘故障", lock=True)
        elif self.feedback_code in (0, 1, 2, 3, 5):
            self.state = "RESET_DONE"
            self.requested_at = None
            self.error = None

    def update_velocity(self, linear, angular):
        values = list(linear) + list(angular)
        valid = len(values) == 6 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
        self.speed_at = self.clock() if valid else None
        # No rounded speed string: rotation must also be zero for reset.
        self.stationary = valid and all(abs(v) <= 1e-4 for v in values)

    def fresh(self):
        return self.feedback_at is not None and self.clock() - self.feedback_at <= self.stale_seconds

    def tick(self):
        if self.state == "RESET_REQUESTED":
            if self.requested_at is not None and self.clock() - self.requested_at >= self.timeout_seconds:
                self.fail("复位超时，请重试", lock=not self.fresh())
                # Loss of communication is locked while feedback is missing;
                # it is not proof of a persistent hardware fault.
                self.fault_locked = False
        elif self.state is not None and not self.fresh():
            self.state = "E_STOP_ACTIVE"
            self.error = "底盘通信中断，保持锁定"

    def block_reason(self):
        self.tick()
        if not self.fresh():
            return "底盘状态未收到或已过期"
        if self.emergency is not False:
            return "请先释放急停按钮"
        if self.state == "RESET_REQUESTED":
            return "复位中，请等待，不能重复发送"
        if self.state != "E_STOP_RELEASED":
            return "当前状态不允许复位" if not self.error else self.error
        if self.speed_at is None or self.clock() - self.speed_at > self.stale_seconds:
            return "底盘速度未收到或已过期，无法确认静止"
        if not self.stationary:
            return "机器人未静止"
        return None

    def begin(self):
        reason = self.block_reason()
        if reason:
            raise RuntimeError(reason)
        self.request_id += 1
        self.state = "RESET_REQUESTED"
        self.requested_at = self.clock()
        self.sent_sequence = None
        self.service_accepted = False
        self.error = None
        return self.request_id

    def ensure_pending(self, token):
        self.tick()
        if token != self.request_id or self.state != "RESET_REQUESTED":
            raise RuntimeError(self.error or "复位流程已被急停或超时中断")
        if not self.fresh() or self.emergency is not False:
            raise RuntimeError("复位条件发生变化，保持锁定")
        if self.speed_at is None or self.clock() - self.speed_at > self.stale_seconds or not self.stationary:
            raise RuntimeError("机器人未静止或速度反馈已过期")

    def mark_sent(self, token, require_ack=False):
        self.ensure_pending(token)
        self.sent_sequence = self.sequence
        self.service_accepted = not require_ack

    def accept_response(self, token):
        self.ensure_pending(token)
        self.service_accepted = True
        self._check_reset_feedback()

    def fail(self, message, lock=False):
        self.request_id += 1
        self.error = message
        self.fault_locked = lock
        self.state = "E_STOP_ACTIVE" if lock or self.emergency is not False else "E_STOP_RELEASED"
        self.requested_at = None
        self.sent_sequence = None

    def view(self, interlock_ready=False, controls_enabled=False, service_ready=False):
        reason = self.block_reason()
        reasons = [reason] if reason else []
        if not interlock_ready:
            reasons.append("主控运动联锁未接入，暂不可复位")
        if not controls_enabled:
            reasons.append("实机复位控制未启用")
        if not service_ready:
            reasons.append("底盘复位服务不可用")
        velocity_fresh = self.speed_at is not None and self.clock() - self.speed_at <= self.stale_seconds
        return {"state": self.state, "requestId": self.request_id, "resetAllowed": not reasons,
                "blockReason": reasons[0] if reasons else None,
                "blockReasons": reasons, "error": self.error,
                "feedbackFresh": self.fresh(), "motionInterlockReady": interlock_ready,
                "checks": {"feedbackFresh": self.fresh(), "emergencyReleased": self.emergency is False,
                           "stationary": velocity_fresh and self.stationary,
                           "stateAllowsReset": self.state == "E_STOP_RELEASED",
                           "motionInterlockReady": interlock_ready,
                           "controlsEnabled": controls_enabled, "resetServiceReady": service_ready}}
