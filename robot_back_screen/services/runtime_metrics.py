"""使用电池实际安时和滑动平均放电电流估算剩余分钟数。"""

from collections import deque
import math
import time


def infer_battery_charge_status(voltage, percent, current, discharge_sign=1, current_deadband=0.2):
    """Infer charge state from measured values, without trusting the BMS status code.

    On this robot's observed BatteryState feed, negative current means charging
    and positive current means discharging. ``discharge_sign`` keeps that wiring
    convention configurable for deployments with the opposite sign.
    """
    try:
        voltage = float(voltage)
        current = float(current)
        percent = None if percent is None else float(percent)
    except (TypeError, ValueError):
        return None, 0
    if not math.isfinite(voltage) or voltage <= 1 or not math.isfinite(current):
        return None, 0
    if percent is not None and not math.isfinite(percent):
        percent = None

    discharge_current = current * (1 if discharge_sign >= 0 else -1)
    if discharge_current < -current_deadband:
        return "充电中", 1
    if discharge_current > current_deadband:
        return "放电中", 2
    if percent is not None and percent >= 99.5:
        return "已充满", 4
    return "未充电", 3


class BatteryRuntimeEstimator:
    def __init__(self, window_seconds=1200, discharge_sign=1, stale_seconds=5, clock=time.monotonic):
        self.window_seconds = max(5, float(window_seconds))
        self.discharge_sign = 1 if discharge_sign >= 0 else -1
        self.stale_seconds = stale_seconds
        self.clock = clock
        self.samples = deque()
        self.last_seen = None
        self.remaining_ah = None
        self.reason = "等待有效电池数据"

    def observe(self, remaining_ah, current_a, status):
        now = self.clock()
        if self.last_seen is not None and now - self.last_seen > self.stale_seconds:
            self.samples.clear()
        self.last_seen = now
        values = (remaining_ah, current_a)
        if any(v is None or not math.isfinite(v) for v in values) or remaining_ah < 0:
            self.samples.clear()
            self.remaining_ah = None
            self.reason = "缺少有效容量或电流"
            return
        self.remaining_ah = remaining_ah
        # 明确的 BatteryState 放电状态兼容标准负电流；状态未知时使用现场 BMS 电流方向配置。
        discharge_a = abs(current_a) if status == 2 else current_a * self.discharge_sign
        if status == 1 or discharge_a < 0:
            self.samples.clear()
            self.reason = "正在充电，暂不估算续航"
            return
        if not self.samples or now - self.samples[-1][0] >= 1:
            self.samples.append((now, max(0, discharge_a)))
        cutoff = now - self.window_seconds
        while len(self.samples) > 1 and self.samples[1][0] <= cutoff:
            self.samples.popleft()
        self.reason = "正在积累放电电流样本"

    def estimate(self):
        now = self.clock()
        result = {"remainingAh": self.remaining_ah, "averageCurrentA": None,
                  "sampleWindowMinutes": 0, "targetWindowMinutes": self.window_seconds / 60,
                  "reason": self.reason}
        if self.last_seen is None or now - self.last_seen > self.stale_seconds:
            result["reason"] = "电池数据未更新"
            return None, result
        if len(self.samples) < 2 or self.remaining_ah is None:
            return None, result
        area = duration = 0.0
        cutoff = now - self.window_seconds
        for (t0, a0), (t1, a1) in zip(self.samples, list(self.samples)[1:]):
            start = max(t0, cutoff)
            if t1 <= start:
                continue
            first_a = a0 + (a1 - a0) * (start - t0) / (t1 - t0)
            area += (first_a + a1) / 2 * (t1 - start)
            duration += t1 - start
        result["sampleWindowMinutes"] = round(duration / 60, 1)
        if duration < 5:
            return None, result
        average = area / duration
        result["averageCurrentA"] = round(average, 3)
        if average < 0.05:
            result["reason"] = "放电电流过小，暂不估算续航"
            return None, result
        result["reason"] = "按近期平均放电电流估算，负载变化会影响结果"
        return round(self.remaining_ah / average * 60, 1), result
