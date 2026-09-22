import { normalizeSnapshot, normalizeWorkSummary } from '../api/robot-contract.js';
import { createRobotViewer } from '../three/robot-viewer.js';

// In API mode the server is the single source of truth for overall health.
// These are defined before any demo initialisation runs.
var ROBOT_DATA_ADAPTER = window.ROBOT_DATA_ADAPTER || null;
var ROBOT_API_BASE = window.ROBOT_DIAGNOSTIC_API || '';
// When an explicitly configured backend is unavailable, keep the page useful
// for demos without pretending that the backend is connected.
var DEMO_FALLBACK_ACTIVE = !ROBOT_DATA_ADAPTER && !ROBOT_API_BASE;
var robot3dViewer = null;
var latestRobotSnapshot = null;
// 信息框按打开顺序排列：左上、右上、左下、右下；关闭任一框后其余自动前移。
var robot3DDataViews = ['motion'];

function isDemoMode() {
  return !ROBOT_DATA_ADAPTER && (!ROBOT_API_BASE || DEMO_FALLBACK_ACTIVE);
}

// ==================== REAL-TIME CLOCK ====================
  function updateClock() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('clockDisplay').textContent = h + ':' + m;
  }
  updateClock();
  setInterval(updateClock, 10000); // update every 10s

  // ==================== STATUS DOT CYCLE ====================
  var statusColors = ['#52C41A', '#FADB14', '#FF4D4F'];
  var statusLabels = ['系统健康', '系统警告', '系统异常'];
  var statusIndex = 0;

  function cycleStatus() {
    statusIndex = (statusIndex + 1) % 3;
    var color = statusColors[statusIndex];
    var label = statusLabels[statusIndex];

    // Top bar dot
    var topDot = document.getElementById('topStatusDot');
    topDot.style.background = color;
    topDot.style.boxShadow = '0 0 8px ' + color;
    document.getElementById('topStatusText').textContent = label;

    // Big health dot
    var bigDot = document.getElementById('bigStatusDot');
    bigDot.style.background = color;
    bigDot.style.boxShadow = '0 0 14px ' + color.replace(')', ',0.5)').replace('rgb', 'rgba');
    // For hex colors, use manual mapping
    if (color === '#52C41A') bigDot.style.boxShadow = '0 0 14px rgba(82,196,26,0.5)';
    else if (color === '#FADB14') bigDot.style.boxShadow = '0 0 14px rgba(250,219,20,0.5)';
    else bigDot.style.boxShadow = '0 0 14px rgba(255,77,79,0.5)';

    var healthText = document.getElementById('healthText');
    healthText.textContent = label;
    healthText.style.color = color;
  }
  // Status must only change from the robot diagnostic service; never rotate it for display effect.

  // ==================== ALERT COUNT & SENSOR STATUS ====================
  function sensorVisualState(name, state) {
    // Collision strip is a three-state safety input. Keep true/false support
    // for older adapters while allowing the explicit real-robot values.
    if (name === 'bumper') {
      if (state === true || state === 'online') return 'green';
      if (state === 'triggered') return 'yellow';
      if (state === false || state === 'offline') return 'red';
      return 'unknown';
    }
    return state === true ? 'green' : (state === false ? 'red' : 'unknown');
  }

  function updateAlertIndicators() {
    var count = alertData.length;
    document.getElementById('alertCount').textContent = count;
    document.getElementById('alertBannerCount').textContent = count;
    document.getElementById('alertHeaderCount').textContent = count;
    document.getElementById('alertBanner').style.display = count ? 'flex' : 'none';

    // In API mode snapshot.health and snapshot.sensors are authoritative.
    // Do not let initial demo data overwrite the state received from server.
    if (!isDemoMode()) return;
    var sensors = document.querySelectorAll('#sensorRow .sensor-dot');
    var sensorNames = ['lidar', 'depthCamera', 'forceSensor', 'bumper', 'camera', 'network'];
    sensors.forEach(function(dot, i) {
      dot.className = 'sensor-dot ' + sensorVisualState(sensorNames[i], demoSensorState[sensorNames[i]]);
    });
    refreshOverallHealthFromAlarms();
  }

  function setOverallHealth(level, label) {
    var map = {
      normal: { color: '#52C41A', label: '系统健康' },
      info: { color: '#1890FF', label: '需注意' },
      warning: { color: '#FADB14', label: '系统警告' },
      critical: { color: '#FF4D4F', label: '系统异常' }
    };
    var item = map[level] || map.normal;
    var text = label || item.label;
    ['topStatusDot', 'bigStatusDot'].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) { el.style.background = item.color; el.style.boxShadow = '0 0 12px ' + item.color; }
    });
    setText('topStatusText', text); setText('healthText', text);
    var healthText = document.getElementById('healthText');
    if (healthText) healthText.style.color = item.color;
  }

  function refreshOverallHealthFromAlarms() {
    var rank = { normal: 0, info: 1, warning: 2, critical: 3, emergency: 4 };
    var level = alertData.reduce(function(highest, item) { return (rank[item.severity] || 0) > (rank[highest] || 0) ? item.severity : highest; }, 'normal');
    var hasDeviceFault = Object.keys(demoSensorState).some(function(key) { return demoSensorState[key] === false; });
    if (hasDeviceFault && (rank[level] || 0) < rank.critical) level = 'critical';
    setOverallHealth(level === 'emergency' ? 'critical' : level, level === 'emergency' ? '紧急停机' : undefined);
  }

  // ==================== TAB SWITCHING ====================
  function switchTab(tabId, btn) {
    // Hide all tab contents
    var contents = document.querySelectorAll('.tab-content');
    contents.forEach(function(c) { c.style.display = 'none'; });
    // Show selected
    document.getElementById('tab-' + tabId).style.display = 'flex';

    // Update nav active state
    var tabs = document.querySelectorAll('.nav-tab');
    tabs.forEach(function(t) { t.classList.remove('active'); });
    btn.classList.add('active');

    // Initialize page-specific logic when opened
    if (tabId === 'alerts') initAlertsView();
    if (tabId === 'detail') { renderSummary(); requestWorkSummary(); }
  }

  // ==================== DIAGNOSE BUTTON ====================
  function startDiagnose() {
    var btn = document.getElementById('btnDiagnose');
    if (btn.disabled) return;
    btn.disabled = true;
    btn.innerHTML = '&#x23F3; 诊断中...';
    setTimeout(function() {
      if (isDemoMode()) {
        btn.disabled = false;
        btn.innerHTML = '&#x2705; 诊断完成';
        addDemoAlert('warning');
        addLog('info', '诊断', '演示诊断已完成，并注入一条模拟告警', '演示控制');
        setTimeout(function() { btn.innerHTML = '&#x1F504; 一键诊断'; }, 2000);
      } else {
        invokeRobotCommand('/commands/diagnose', {}, '已请求一键诊断').then(function(success) {
          btn.disabled = false;
          btn.innerHTML = success ? '&#x2705; 已请求诊断' : '&#x26A0; 诊断未接入';
          setTimeout(function() { btn.innerHTML = '&#x1F504; 一键诊断'; }, 2000);
        });
      }
    }, 3000);
  }

  // ==================== FAULT CLEAR BUTTON ====================
  function clearFault() {
    if (!alertData.length) {
      alert('当前没有可清除的告警。');
      return;
    }
    if (!confirm('确认发送故障清除请求？\n\n实机运行时，仍在触发的故障不会被清除。')) return;

    var btn = document.getElementById('btnFaultClear');
    if (!btn || btn.disabled) return;
    var originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '&#x23F3; 清除中...';

    if (isDemoMode()) {
      alertData = [];
      currentAlertIndex = 0;
      updateAlertIndicators();
      renderAlertList();
      showNoActiveAlerts();
      addLog('info', '演示控制', '已清除全部模拟告警', '演示控制');
      btn.innerHTML = '&#x2705; 已清除';
      setTimeout(function() {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }, 1800);
      return;
    }

    invokeRobotCommand('/alarms/clear-recovered', {}, '已请求清除已恢复故障').then(function(success) {
      if (!success) {
        btn.disabled = false;
        btn.innerHTML = originalText;
        return;
      }
      // Ask the source again instead of pretending that the client cleared a
      // fault.  The server / real diagnosis engine remains authoritative.
      requestAlarms();
      requestSnapshot();
      btn.innerHTML = '&#x2705; 已清除';
      setTimeout(function() {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }, 1800);
    });
  }

  // ==================== ALERT BANNER CLICK ====================
  function goToAlerts() {
    alert('跳转至告警中心\n\n当前有 ' + alertData.length + ' 条未处理告警。');
    // Auto switch to alerts tab
    var alertsTab = document.querySelector('.nav-tab[data-tab="alerts"]');
    if (alertsTab) switchTab('alerts', alertsTab);
  }

  // ==================== ALERTS DATA & RENDER ====================
  // 这些示例只保留作开发参考；初始页面不能把它们当作当前真实告警。
  var initialAlertExamples = [
    {
      id: 'F001', title: '左臂电机温度过高', severity: 'critical', code: 'F001',
      time: '2024-01-15 14:32:18',
      desc: '左臂电机温度超过安全阈值，当前温度78℃，阈值70℃。',
      suggestion: '建议立即停机检查电机散热系统，清理散热片灰尘，检查风扇是否正常工作。',
      label: '实时曲线 · 电机温度 (°C)',
      values: [62, 63, 65, 67, 70, 72, 75, 78, 77, 76, 78, 79, 78, 77, 76, 75, 74, 73, 72, 71], axis: { min: 50, max: 90, threshold: 70 }
    },
    {
      id: 'F002', title: '右轮编码器异常', severity: 'critical', code: 'F002',
      time: '2024-01-15 14:28:05',
      desc: '右轮编码器反馈信号丢失，当前脉冲数0，预期>1200。',
      suggestion: '检查编码器接线是否松动，确认供电电压正常，必要时更换编码器。',
      label: '实时曲线 · 编码器脉冲 (counts)',
      values: [1200, 1180, 1150, 900, 600, 300, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], axis: { min: 0, max: 1400, threshold: 1200 }
    },
    {
      id: 'W001', title: '电池电量偏低', severity: 'warning', code: 'W001',
      time: '2024-01-15 14:15:30',
      desc: '当前电池电量18%，低于警告阈值20%，建议尽快充电。',
      suggestion: '降低运行功率或返回充电站，避免电池过放导致设备停机。',
      label: '实时曲线 · 电池电量 (%)',
      values: [35, 33, 31, 29, 27, 25, 23, 21, 19, 18, 18, 17, 17, 16, 16, 15, 15, 14, 14, 13], axis: { min: 0, max: 100, threshold: 20 }
    },
    {
      id: 'W002', title: '通信延迟波动', severity: 'warning', code: 'W002',
      time: '2024-01-15 13:45:22',
      desc: '网络通信延迟波动较大，当前延迟145ms，阈值100ms。',
      suggestion: '检查网络链路质量，重启通信模块，排查附近干扰源。',
      label: '实时曲线 · 通信延迟 (ms)',
      values: [45, 52, 68, 85, 110, 95, 130, 145, 160, 140, 120, 155, 145, 135, 125, 115, 105, 95, 90, 85], axis: { min: 0, max: 200, threshold: 100 }
    }
  ];
  var alertData = [];
  var demoSensorState = { lidar: true, depthCamera: true, forceSensor: true, bumper: 'online', camera: true, network: true };
  var currentAlertIndex = 0;

  function updateAlertPageTime() {
    var now = new Date();
    var y = now.getFullYear();
    var m = String(now.getMonth() + 1).padStart(2, '0');
    var d = String(now.getDate()).padStart(2, '0');
    var h = String(now.getHours()).padStart(2, '0');
    var min = String(now.getMinutes()).padStart(2, '0');
    var s = String(now.getSeconds()).padStart(2, '0');
    var t = y + '-' + m + '-' + d + ' ' + h + ':' + min + ':' + s;
    var el = document.getElementById('alertPageTime');
    if (el) el.textContent = t;
  }

  function renderAlertList() {
    var list = document.getElementById('alertList');
    list.innerHTML = '';
    if (!alertData.length) {
      list.innerHTML = '<div style="padding:24px;color:#888;text-align:center;">暂无未处理告警</div>';
      return;
    }
    alertData.forEach(function(item, index) {
      var div = document.createElement('div');
      div.className = 'alert-item' + (index === currentAlertIndex ? ' active' : '');
      div.innerHTML =
        '<div class="alert-item-top">' +
          '<span class="alert-severity ' + ((item.severity === 'critical' || item.severity === 'emergency') ? 'critical' : 'warning') + '">' +
            (item.severity === 'emergency' ? '紧急' : item.severity === 'critical' ? '严重' : item.severity === 'info' ? '提示' : '警告') +
          '</span>' +
          '<span class="alert-title">' + item.title + '</span>' +
        '</div>' +
        '<div class="alert-item-bottom">' +
          '<span>告警码: ' + item.code + '</span>' +
          '<span>' + item.time + '</span>' +
        '</div>';
      div.onclick = function() { selectAlert(index); };
      list.appendChild(div);
    });
  }

  function selectAlert(index) {
    currentAlertIndex = index;
    var item = alertData[index];
    if (!item) { showNoActiveAlerts(); return; }
    document.getElementById('btnInvestigate').disabled = false;
    document.getElementById('btnResolve').disabled = false;
    document.getElementById('detailCode').textContent = item.code;
    document.getElementById('detailTitle').textContent = item.title;
    document.getElementById('detailDesc').textContent = item.desc;
    document.getElementById('detailSuggestion').textContent = item.suggestion;
    document.getElementById('chartLabel').textContent = item.label;
    renderAlertList();
    drawAlertChart(item);
  }

  function drawAlertChart(item) {
    var values = item.values;
    var axis = item.axis || {};
    var canvas = document.getElementById('alertChart');
    var ctx = canvas.getContext('2d');
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    canvas.width = Math.floor(rect.width * dpr);
    canvas.height = Math.floor(rect.height * dpr);
    ctx.scale(dpr, dpr);
    var w = rect.width;
    var h = rect.height;

    ctx.clearRect(0, 0, w, h);

    var left = 42, right = 10, top = 10, bottom = 22;
    var plotW = w - left - right, plotH = h - top - bottom;
    var min = axis.min !== undefined ? axis.min : Math.min.apply(null, values);
    var max = axis.max !== undefined ? axis.max : Math.max.apply(null, values);
    if (axis.min === undefined || axis.max === undefined) {
      var range = max - min || 1;
      min -= range * 0.1;
      max += range * 0.1;
    }

    // Grid lines and a fixed scale appropriate for this measurement.
    ctx.strokeStyle = '#2A2A2A';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (var i = 0; i < 5; i++) {
      var gy = top + plotH * i / 4;
      ctx.moveTo(left, gy);
      ctx.lineTo(w - right, gy);
    }
    ctx.stroke();

    var step = plotW / (values.length - 1);
    var color = item.severity === 'critical' ? '#FF4D4F' : '#FADB14';

    // Threshold line uses the diagnostic rule's real threshold, not the data range.
    if (typeof axis.threshold === 'number' && axis.threshold >= min && axis.threshold <= max) {
      var thresholdY = top + plotH - ((axis.threshold - min) / (max - min)) * plotH;
      ctx.save();
      ctx.strokeStyle = '#FF7875';
      ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(left, thresholdY); ctx.lineTo(w - right, thresholdY); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#FF7875'; ctx.font = '10px "Courier New", monospace'; ctx.textAlign = 'right';
      ctx.fillText('阈值 ' + axis.threshold, w - right, Math.max(9, thresholdY - 3));
      ctx.restore();
    }

    // Draw line
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach(function(v, i) {
      var x = left + i * step;
      var y = top + plotH - ((v - min) / (max - min)) * plotH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Draw points
    ctx.fillStyle = color;
    values.forEach(function(v, i) {
      var x = left + i * step;
      var y = top + plotH - ((v - min) / (max - min)) * plotH;
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    });

    // Y-axis labels
    ctx.fillStyle = '#AAAAAA';
    ctx.font = '10px "Courier New", monospace';
    ctx.textAlign = 'right';
    for (var i = 0; i < 5; i++) {
      var val = min + (max - min) * (1 - i / 4);
      var ly = top + plotH * i / 4 + 3;
      ctx.fillText(Number.isInteger(val) ? val : val.toFixed(1), left - 5, ly);
    }

    ctx.textAlign = 'left'; ctx.fillText('-' + (values.length - 1) + 's', left, h - 5);
    ctx.textAlign = 'center'; ctx.fillText('-' + Math.floor((values.length - 1) / 2) + 's', left + plotW / 2, h - 5);
    ctx.textAlign = 'right'; ctx.fillText('当前', w - right, h - 5);
  }

  function investigateAlert() {
    var item = alertData[currentAlertIndex];
    if (!item) return;
    alert('已开始调查：' + item.code + ' ' + item.title);
  }

  function showNoActiveAlerts() {
    document.getElementById('detailCode').textContent = '--';
    document.getElementById('detailTitle').textContent = '暂无未处理告警';
    document.getElementById('detailDesc').textContent = '当前没有需要确认恢复的告警。';
    document.getElementById('detailSuggestion').textContent = '机器人状态正常。';
    document.getElementById('chartLabel').textContent = '暂无实时告警曲线';
    document.getElementById('btnInvestigate').disabled = true;
    document.getElementById('btnResolve').disabled = true;
    var canvas = document.getElementById('alertChart');
    var ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function acknowledgeAlertLocally(id) {
    var index = alertData.findIndex(function(alert) { return alert.id === id; });
    if (index < 0) return;
    var item = alertData[index];
    alertData.splice(index, 1);
    addLog('info', '告警恢复', '已确认恢复 ' + item.code + ' ' + item.title, '告警模块');
    updateAlertIndicators();
    renderAlertList();
    if (alertData.length) selectAlert(Math.min(index, alertData.length - 1));
    else showNoActiveAlerts();
  }

  function resolveAlert() {
    var item = alertData[currentAlertIndex];
    if (!item) return;
    if (confirm('确认恢复告警 ' + item.code + '？\n' + item.title)) {
      if (isDemoMode()) {
        acknowledgeAlertLocally(item.id);
        alert('演示模式：已确认恢复 ' + item.code);
        return;
      }
      invokeRobotCommand('/alarms/' + item.id + '/acknowledge', {}, '已确认恢复 ' + item.code)
        .then(function(success) { if (success) acknowledgeAlertLocally(item.id); });
    }
  }

  function demoTime() {
    var now = new Date();
    return now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0') + ' ' + String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0') + ':' + String(now.getSeconds()).padStart(2, '0');
  }

  var demoAlertTemplates = {
    critical: [
      { title: '演示：左臂关节温度异常', code: 'D-C001', desc: '演示数据：左臂关节温度超过安全阈值。', suggestion: '演示处理建议：停止相关动作并检查散热与传感器。', label: '实时曲线 · 演示温度 (°C)', values: [58, 61, 65, 69, 73, 77, 80, 83, 81, 79], axis: { min: 50, max: 90, threshold: 70 } },
      { title: '演示：右轮编码器信号丢失', code: 'D-C002', desc: '演示数据：右轮编码器连续丢失反馈脉冲。', suggestion: '演示处理建议：检查编码器接线、供电及机械联轴器。', label: '实时曲线 · 演示编码器脉冲 (counts)', values: [1220, 1205, 1180, 960, 650, 330, 80, 0, 0, 0], axis: { min: 0, max: 1400, threshold: 1200 } },
      { title: '演示：电池电压低于保护阈值', code: 'D-C003', desc: '演示数据：电池电压低于安全保护阈值，存在掉电风险。', suggestion: '演示处理建议：停止高功耗作业并立即连接充电设备。', label: '实时曲线 · 演示电池电压 (V)', values: [25.1, 24.7, 24.3, 23.9, 23.5, 23.1, 22.8, 22.6, 22.5, 22.4], axis: { min: 20, max: 26, threshold: 23 } },
      { title: '演示：激光雷达通信中断', code: 'D-C004', desc: '演示数据：激光雷达数据流超过 3 秒未更新。', suggestion: '演示处理建议：检查雷达供电、网线与通信进程。', label: '实时曲线 · 演示雷达帧率 (Hz)', values: [10, 10, 10, 9, 7, 4, 1, 0, 0, 0], axis: { min: 0, max: 12, threshold: 1 } }
    ],
    warning: [
      { title: '演示：电池电量偏低', code: 'D-W001', desc: '演示数据：电池电量低于预警阈值。', suggestion: '演示处理建议：尽快返回充电点，避免电池过放。', label: '实时曲线 · 演示电量 (%)', values: [38, 34, 31, 28, 25, 22, 19, 17, 16, 15], axis: { min: 0, max: 100, threshold: 20 } },
      { title: '演示：网络通信延迟升高', code: 'D-W002', desc: '演示数据：与核心节点的通信延迟持续高于预警阈值。', suggestion: '演示处理建议：检查网络信号、交换机和附近干扰源。', label: '实时曲线 · 演示通信延迟 (ms)', values: [42, 48, 55, 68, 74, 96, 118, 135, 121, 110], axis: { min: 0, max: 200, threshold: 100 } },
      { title: '演示：摄像头帧率波动', code: 'D-W003', desc: '演示数据：摄像头帧率短时下降，视觉任务可能受影响。', suggestion: '演示处理建议：检查带宽占用、相机接口和镜头遮挡。', label: '实时曲线 · 演示摄像头帧率 (fps)', values: [30, 30, 29, 27, 23, 19, 22, 25, 21, 24], axis: { min: 0, max: 35, threshold: 25 } },
      { title: '演示：碰撞条信号抖动', code: 'D-W004', desc: '演示数据：碰撞条输入在短时间内多次切换。', suggestion: '演示处理建议：检查防撞条固定状态、线束与灵敏度配置。', label: '实时曲线 · 演示碰撞条信号', values: [0, 0, 1, 0, 1, 1, 0, 1, 0, 0], axis: { min: 0, max: 1 } }
    ]
  };
  var lastDemoTemplateIndex = { critical: -1, warning: -1 };

  function addDemoAlert(severity) {
    if (!isDemoMode()) return;
    var templates = demoAlertTemplates[severity];
    var templateIndex = Math.floor(Math.random() * templates.length);
    if (templates.length > 1 && templateIndex === lastDemoTemplateIndex[severity]) templateIndex = (templateIndex + 1) % templates.length;
    lastDemoTemplateIndex[severity] = templateIndex;
    var template = templates[templateIndex];
    var isCritical = severity === 'critical';
    var id = 'DEMO-' + Date.now();
    var item = Object.assign({}, template, { id: id, severity: severity, time: demoTime(), values: template.values.slice() });
    alertData.unshift(item);
    currentAlertIndex = 0;
    updateAlertIndicators();
    renderAlertList();
    selectAlert(0);
    addLog(isCritical ? 'fault' : 'warn', isCritical ? '严重故障' : '警告', '已注入 ' + item.code + ' ' + item.title, '演示控制');
  }

  function clearDemoAlerts() {
    if (!isDemoMode() || !alertData.length) return;
    if (!confirm('确认清空全部演示告警？')) return;
    alertData = [];
    currentAlertIndex = 0;
    updateAlertIndicators();
    renderAlertList();
    showNoActiveAlerts();
    addLog('info', '演示控制', '已清空全部演示告警', '演示控制');
  }

  function demoValue(id) { return document.getElementById(id).value.trim(); }

  function openDemoControl() {
    if (!isDemoMode()) return;
    document.getElementById('demoEntry').style.display = 'none';
    document.getElementById('toolsPlaceholder').style.display = 'none';
    document.getElementById('demoTools').style.display = 'block';
    document.getElementById('toolsPageTitle').innerHTML = '演示控制 <span>仅用于开发与演示</span>';
  }

  function closeDemoControl() {
    document.getElementById('demoTools').style.display = 'none';
    document.getElementById('demoEntry').style.display = 'block';
    document.getElementById('toolsPlaceholder').style.display = 'flex';
    document.getElementById('toolsPageTitle').innerHTML = '工具 <span>辅助功能与本机设置</span>';
  }

  // ==================== READ-ONLY 3D ROBOT VIEW ====================
  function ensureRobot3DViewer() {
    if (robot3dViewer) return robot3dViewer;
    robot3dViewer = createRobotViewer({
      canvasHost: document.getElementById('robot3dCanvas'),
      loadingEl: document.getElementById('robot3dLoading'),
      statusEl: document.getElementById('robot3dStatus'),
      faultsEl: document.getElementById('robot3dFaults'),
      tooltipEl: document.getElementById('robot3dTooltip')
    });
    return robot3dViewer;
  }

  function openRobot3DView() {
    document.getElementById('robot3dEntry').style.display = 'none';
    document.getElementById('demoEntry').style.display = 'none';
    document.getElementById('demoTools').style.display = 'none';
    document.getElementById('toolsPlaceholder').style.display = 'none';
    document.getElementById('robot3dView').style.display = 'flex';
    document.getElementById('toolsPageTitle').innerHTML = '3D 视图 <span>只读实时机器人状态</span>';
    var viewer = ensureRobot3DViewer();
    viewer.open();
    if (latestRobotSnapshot) viewer.updateJointPositions(latestRobotSnapshot);
    viewer.setFaults(alertData);
    renderRobot3DDataPanels();
  }

  function closeRobot3DView() {
    document.getElementById('robot3dView').style.display = 'none';
    document.getElementById('robot3dEntry').style.display = 'block';
    document.getElementById('demoEntry').style.display = isDemoMode() ? 'block' : 'none';
    document.getElementById('toolsPlaceholder').style.display = 'flex';
    document.getElementById('toolsPageTitle').innerHTML = '工具 <span>辅助功能与本机设置</span>';
  }

  function resetRobot3DView() {
    if (robot3dViewer) robot3dViewer.resetView();
  }

  function toggleRobot3DOption(option) {
    if (!robot3dViewer) return;
    var enabled = robot3dViewer.toggleOption(option);
    var button = document.getElementById('robot3d' + option.charAt(0).toUpperCase() + option.slice(1) + 'Toggle');
    if (button) button.classList.toggle('active', enabled);
  }

  function getRobot3DDemoSnapshot() {
    var sensorNames = ['lidar', 'depthCamera', 'forceSensor', 'bumper', 'camera', 'network'];
    var sensors = {};
    document.querySelectorAll('#sensorRow .sensor-dot').forEach(function(dot, index) {
      var name = sensorNames[index];
      sensors[name] = dot.classList.contains('green') ? true : dot.classList.contains('yellow') ? 'triggered' : false;
    });
    return {
      motion: {
        position: document.getElementById('currentPosition').textContent,
        target: document.getElementById('targetPosition').textContent,
        speed: document.getElementById('currentSpeed').textContent,
        leftTcp: document.getElementById('leftTcpPosition').textContent,
        rightTcp: document.getElementById('rightTcpPosition').textContent,
        joints: [1, 2, 3, 4, 5, 6].map(function(index) { return document.getElementById('joint' + index).textContent; })
      },
      battery: {
        percent: document.getElementById('batteryLevel').textContent,
        voltage: document.getElementById('batteryVoltage').textContent,
        current: document.getElementById('batteryCurrent').textContent,
        temperature: document.getElementById('batteryTemperature').textContent,
        chargeStatus: document.getElementById('chargeStatus').textContent
      },
      sensors: sensors
    };
  }

  function getRobot3DDataPanel(view, data) {
    var motion = data.motion || {}, battery = data.battery || {}, sensors = data.sensors || {};
    var rows = [];
    var title = '';
    if (view === 'motion') {
      title = '运动状态';
      rows = [['当前位置', motion.position], ['目标点', motion.target], ['速度', motion.speed], ['左手 TCP', motion.leftTcp], ['右手 TCP', motion.rightTcp]];
    } else if (view === 'joints') {
      title = '关节状态';
      var positions = motion.jointPositions || {};
      var entries = Object.entries(positions).slice(0, 6);
      rows = entries.length ? entries.map(function(entry) {
        return [entry[0], (Number(entry[1]) * 180 / Math.PI).toFixed(1) + '°'];
      }) : (motion.joints || []).slice(0, 6).map(function(value, index) { return ['J' + (index + 1), value]; });
    } else if (view === 'battery') {
      title = '电池状态';
      rows = [['电量', displayValue(battery.percent, '%')], ['电压', displayValue(battery.voltage, 'V')], ['电流', displayValue(battery.current, 'A')], ['温度', displayValue(battery.temperature, '°C')], ['状态', battery.chargeStatus]];
    } else {
      title = '传感器状态';
      rows = [['激光雷达', sensors.lidar], ['深度相机', sensors.depthCamera], ['六维力', sensors.forceSensor], ['碰撞条', sensors.bumper], ['摄像头', sensors.camera], ['网络', sensors.network]].map(function(item) {
        var state = sensorVisualState(item[0] === '碰撞条' ? 'bumper' : 'sensor', item[1]);
        return [item[0], state === 'green' ? '正常' : state === 'yellow' ? '已触发' : state === 'red' ? '离线' : '未知', state];
      });
    }
    return { title: title, rows: rows };
  }

  function renderRobot3DDataPanels() {
    var leftDock = document.getElementById('robot3dDataLeft');
    var rightDock = document.getElementById('robot3dDataRight');
    if (!leftDock || !rightDock) return;
    var data = latestRobotSnapshot || getRobot3DDemoSnapshot();
    leftDock.innerHTML = '';
    rightDock.innerHTML = '';
    robot3DDataViews.forEach(function(view, index) {
      var panel = getRobot3DDataPanel(view, data);
      var card = document.createElement('section'); card.className = 'robot-3d-data-card';
      card.dataset.slot = String(index + 1);
      var title = document.createElement('div'); title.className = 'robot-3d-data-title'; title.textContent = panel.title;
      var close = document.createElement('button'); close.className = 'robot-3d-data-close'; close.type = 'button'; close.textContent = '×'; close.title = '关闭' + panel.title;
      close.addEventListener('click', function(event) { event.stopPropagation(); toggleRobot3DData(view); });
      title.appendChild(close);
      var list = document.createElement('div'); list.className = 'robot-3d-data-list';
      panel.rows.forEach(function(row) {
        var item = document.createElement('div'); item.className = 'robot-3d-data-item';
        var key = document.createElement('span'); key.textContent = row[0] || '--';
        var value = document.createElement('span'); value.textContent = row[1] === undefined || row[1] === null || row[1] === '' ? '--' : row[1];
        if (row[2]) value.className = 'data-' + row[2];
        item.appendChild(key); item.appendChild(value); list.appendChild(item);
      });
      card.appendChild(title); card.appendChild(list);
      // 第 1/3 个在左侧上/下角，第 2/4 个在右侧上/下角；关闭后数组收缩，
      // 后面的卡片自然向前补位，且空侧栏不会占据模型空间。
      (index % 2 === 0 ? leftDock : rightDock).appendChild(card);
    });
  }

  function toggleRobot3DData(view) {
    var index = robot3DDataViews.indexOf(view);
    if (index >= 0) robot3DDataViews.splice(index, 1);
    else robot3DDataViews.push(view);
    document.querySelectorAll('[data-robot3d-data]').forEach(function(control) {
      control.classList.toggle('active', robot3DDataViews.indexOf(control.dataset.robot3dData) >= 0);
    });
    renderRobot3DDataPanels();
  }

  function selectRobot3DData(view) {
    // 兼容旧的内联调用；现在支持同时显示多个信息框。
    toggleRobot3DData(view);
  }

  function applyDemoStatus() {
    if (!isDemoMode()) return;
    setText('robotModel', demoValue('demoRobotModel'));
    setText('currentPosition', demoValue('demoCurrentPosition'));
    setText('targetPosition', demoValue('demoTargetPosition'));
    setText('currentSpeed', demoValue('demoCurrentSpeed'));
    setText('leftTcpPosition', demoValue('demoLeftTcpPosition'));
    setText('rightTcpPosition', demoValue('demoRightTcpPosition'));
    setText('uptime', demoValue('demoUptime'));
    setText('remainingTime', demoValue('demoRemainingTime') + 'm');
    setText('payload', demoValue('demoPayload') + 'kg');
    setText('gripForce', demoValue('demoGripForce') + 'N');
    setText('operationMode', demoValue('demoOperationMode'));
    setText('networkIp', 'IP ' + demoValue('demoNetworkIp'));
    for (var i = 1; i <= 6; i++) setText('joint' + i, demoValue('demoJoint' + i) + '°');
    var percent = demoValue('demoBatteryPercent');
    setText('batteryLevel', percent + '%');
    setText('batteryTop', percent + '%');
    setText('batteryVoltage', demoValue('demoBatteryVoltage') + 'V');
    setText('batteryCurrent', demoValue('demoBatteryCurrent') + 'A');
    setText('batteryTemperature', demoValue('demoBatteryTemperature') + '°C');
    setText('cellVoltage', demoValue('demoCellVoltage') + 'V');
    var chargeStatus = demoValue('demoChargeStatus');
    setText('chargeStatus', chargeStatus);
    setText('chargeCycles', demoValue('demoChargeCycles'));
    var chargeEl = document.getElementById('chargeStatus');
    chargeEl.style.color = chargeStatus === '已充满' ? '#52C41A' : chargeStatus === '充电中' ? '#FADB14' : '#FFFFFF';
    document.querySelectorAll('[data-demo-sensor]').forEach(function(input) { demoSensorState[input.dataset.demoSensor] = input.checked; });
    demoSensorState.bumper = demoValue('demoBumperState');
    updateAlertIndicators();
    renderRobot3DDataPanels();
    addLog('info', '演示控制', '已应用状态页面参数', '演示控制');
  }

  function resetDemoStatus() {
    if (!isDemoMode()) return;
    var defaults = {
      demoRobotModel: 'R1', demoCurrentPosition: 'X1.23 Y2.34 Z0.56', demoTargetPosition: 'X5.00 Y3.00 Z1.20', demoCurrentSpeed: '0.45 m/s', demoLeftTcpPosition: 'X1.23 Y2.62 Z0.56', demoRightTcpPosition: 'X1.23 Y2.06 Z0.56',
      demoUptime: '2h23m', demoRemainingTime: '42', demoPayload: '2.3', demoGripForce: '12.5', demoOperationMode: '自动', demoNetworkIp: '192.168.1.10',
      demoJoint1: '15', demoJoint2: '23', demoJoint3: '-8', demoJoint4: '42', demoJoint5: '11', demoJoint6: '5',
      demoBatteryPercent: '85', demoBatteryVoltage: '14.8', demoBatteryCurrent: '3.2', demoBatteryTemperature: '28', demoCellVoltage: '3.70', demoChargeStatus: '充电中', demoChargeCycles: '12'
    };
    Object.keys(defaults).forEach(function(id) { document.getElementById(id).value = defaults[id]; });
    Object.keys(demoSensorState).forEach(function(key) { demoSensorState[key] = true; });
    demoSensorState.bumper = 'online';
    document.getElementById('demoBumperState').value = 'online';
    document.querySelectorAll('[data-demo-sensor]').forEach(function(input) { input.checked = true; });
    applyDemoStatus();
  }

  // ==================== SUMMARY DATA & RENDER ====================
  var summaryData = {
    // 上一次结束充电时的电量 (Ah)
    lastChargeAh: 100,
    // 触发时保存的电量 (Ah)
    triggerAh: 73.5,
    // 上一次结束充电的时间戳 (Unix seconds) — 2026-08-06 08:00:00
    lastChargeEndTs: 1754668800,
    // 本次开始充电的时间戳 (Unix seconds) — 2026-08-06 15:30:00
    chargeStartTs: 1754695800,
    // 额定最大载重 (kg)
    ratedLoad: 50,
    // 本次作业周期内的搬运任务
    tasks: [
      { name: '物料搬运 A-12',  weight: 42.5, time: '08:23' },
      { name: '零件转运 B-07',  weight: 38.0, time: '08:51' },
      { name: '成品下线 C-03',  weight: 45.2, time: '09:18' },
      { name: '半成品转运 A-08', weight: 35.8, time: '10:05' },
      { name: '重型物料 D-01',  weight: 48.1, time: '10:42' },
      { name: '标准搬运 B-15',  weight: 32.6, time: '11:30' },
      { name: '精密组件 C-09',  weight: 41.3, time: '13:15' },
      { name: '包装下线 A-20',  weight: 39.7, time: '14:08' }
    ]
  };

  function renderSummary() {
    var d = summaryData;

    // 本次消耗电量 (Ah) = 上一次结束充电的电量 - 触发时保存的电量
    var consumptionAh = d.consumptionAh !== undefined ? d.consumptionAh : d.lastChargeAh - d.triggerAh;
    document.getElementById('kpiConsumption').innerHTML = consumptionAh.toFixed(2) + '<span class="kpi-unit">Ah</span>';

    // 本次作业时长 (秒) = 开始充电的时间戳 - 上一次结束充电的时间戳
    var durationSec = d.durationSec !== undefined ? d.durationSec : d.chargeStartTs - d.lastChargeEndTs;
    var h = Math.floor(durationSec / 3600);
    var m = Math.floor((durationSec % 3600) / 60);
    var s = durationSec % 60;
    document.getElementById('kpiDuration').innerHTML = durationSec.toLocaleString() + '<span class="kpi-unit">s</span>';
    document.getElementById('kpiDurationHMS').textContent = h + 'h ' + m + 'm ' + s + 's';

    // 平均放电电流 (A) = 消耗电量(Ah) / 作业时长(h)
    var avgCurrent = d.avgCurrent !== undefined ? d.avgCurrent : consumptionAh / (durationSec / 3600);
    document.getElementById('kpiCurrent').innerHTML = avgCurrent.toFixed(2) + '<span class="kpi-unit">A</span>';

    // 累计总重 = Σ(单次任务重量)
    var totalWeight = d.tasks.reduce(function(acc, t) { return acc + t.weight; }, 0);
    document.getElementById('loadTotal').textContent = totalWeight.toFixed(1);

    // 平均负载率 = Σ(单次任务重量 / 额定最大载重) / 搬运次数 × 100%
    var sumRate = d.tasks.reduce(function(acc, t) { return acc + t.weight / d.ratedLoad; }, 0);
    var avgRate = sumRate / d.tasks.length * 100;
    document.getElementById('loadRate').textContent = avgRate.toFixed(1);

    // 任务数量
    document.getElementById('taskCount').textContent = d.tasks.length;

    // 任务明细表格
    var tbody = document.getElementById('taskTableBody');
    tbody.innerHTML = '';
    d.tasks.forEach(function(task, i) {
      var rate = task.weight / d.ratedLoad * 100;
      var cls = rate >= 90 ? 'danger' : rate >= 80 ? 'warn' : '';
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td style="color:#AAAAAA;">' + (i + 1) + '</td>' +
        '<td>' + task.name + '</td>' +
        '<td>' + task.weight.toFixed(1) + ' kg</td>' +
        '<td class="load-pct' + (cls ? ' ' + cls : '') + '">' + rate.toFixed(1) + '%</td>' +
        '<td style="color:#AAAAAA;">' + task.time + '</td>';
      tbody.appendChild(tr);
    });
  }

  function initAlertsView() {
    updateAlertPageTime();
    renderAlertList();
    setTimeout(function() {
      if (alertData.length) drawAlertChart(alertData[currentAlertIndex]);
      else showNoActiveAlerts();
    }, 50);
  }

  // Initialize alert indicators after alertData is defined
  updateAlertIndicators(); // initial run

  // ==================== ROBOT DATA ADAPTER ====================
  // The deployment may inject window.ROBOT_DATA_ADAPTER to obtain actual data
  // from the existing ROS2 SDK/bridge. HTTP is only a fallback, not a required
  // diagnostic-system architecture.
  function setDataSourceState(state) {
    var el = document.getElementById('dataSource');
    if (!el) return;
    var labels = {
      demo: ROBOT_API_BASE ? '后端模拟数据' : '本地演示数据',
      connecting: '接口连接中',
      waiting: '等待实机数据',
      // ROS 已连接只代表收到了某一路 ROS 消息；是否为完整实机数据要看
      // /healthz 的 activeSources，不能在背屏上笼统标成“实机数据”。
      connected: ROBOT_DATA_ADAPTER ? '本地数据' : 'ROS 数据',
      offline: '接口离线'
    };
    el.className = 'data-source ' + state;
    el.textContent = labels[state] || labels.demo;
  }

  function activateDemoFallback() {
    if (ROBOT_DATA_ADAPTER) return;
    DEMO_FALLBACK_ACTIVE = true;
    var entry = document.getElementById('demoEntry');
    var tools = document.getElementById('demoTools');
    var view3d = document.getElementById('robot3dView');
    // Health checks continue while the backend is offline. Do not make the
    // entry card reappear after the user has already opened the demo panel.
    if (entry && (!tools || tools.style.display === 'none') && (!view3d || view3d.style.display === 'none')) entry.style.display = 'block';
  }

  function deactivateDemoFallback() {
    if (!ROBOT_API_BASE || ROBOT_DATA_ADAPTER) return;
    DEMO_FALLBACK_ACTIVE = false;
    var entry = document.getElementById('demoEntry');
    var tools = document.getElementById('demoTools');
    var placeholder = document.getElementById('toolsPlaceholder');
    var view3d = document.getElementById('robot3dView');
    if (entry) entry.style.display = 'none';
    if (tools) tools.style.display = 'none';
    // 后端恢复连接时，不能把“扩展工具”占位区插回正在打开的 3D 页面。
    if (placeholder && (!view3d || view3d.style.display === 'none')) placeholder.style.display = 'flex';
  }

  setDataSourceState(ROBOT_DATA_ADAPTER || ROBOT_API_BASE ? 'connecting' : 'demo');
  if (ROBOT_DATA_ADAPTER || ROBOT_API_BASE) document.getElementById('demoEntry').style.display = 'none';
  // 演示模式保留样例日志；接口模式只能展示后端收到的真实 ROS 日志，不能
  // 用这些示例内容冒充实机记录。
  var localLogs = isDemoMode() ? [
    { time: '15:42:18', type: 'fault', label: '故障', text: 'F001 左臂电机温度过高，已触发安全策略', source: '诊断引擎' },
    { time: '15:38:05', type: 'warn', label: '警告', text: 'W014 核心节点通信延迟波动', source: '网络模块' },
    { time: '15:31:44', type: 'info', label: '提示', text: '电量低于建议值，建议任务结束后充电', source: '电池管理' },
    { time: '15:20:10', type: 'info', label: '信息', text: '作业任务 #A-1208 已开始', source: '任务模块' }
  ] : [];

  function renderLogs() {
    var list = document.getElementById('logList');
    if (!list) return;
    list.innerHTML = localLogs.map(function(log) {
      return '<div class="log-item"><span class="log-time">' + log.time + '</span><span class="log-tag ' + log.type + '">' + log.label + '</span><span>' + log.text + '</span><span style="color:#AAAAAA;font-size:11px;">' + log.source + '</span></div>';
    }).join('');
  }

  function applyLogs(data) {
    var payload = data && data.data ? data.data : data;
    if (!Array.isArray(payload)) return;
    localLogs = payload.map(function(log) {
      var type = ['info', 'warn', 'fault'].indexOf(log.type) >= 0 ? log.type : 'info';
      return {
        time: displayValue(log.time),
        type: type,
        label: displayValue(log.label),
        text: displayValue(log.text),
        source: displayValue(log.source)
      };
    }).slice(0, 200);
    renderLogs();
  }

  function requestLogs() {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.getLogs === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.getLogs());
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + '/history').then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    if (request) request.then(applyLogs).catch(function() { /* 保留上一次真实日志，不写入演示日志。 */ });
  }

  function applyWorkSummary(data) {
    data = normalizeWorkSummary(data);
    summaryData = Object.assign({}, summaryData, data);
    if (Array.isArray(data.tasks)) summaryData.tasks = data.tasks;
    renderSummary();
  }

  function requestWorkSummary() {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.getWorkSummary === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.getWorkSummary());
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + '/work-summary').then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    if (request) request.then(applyWorkSummary).catch(function() { addLog('warn', '警告', '未获取到本次作业数据，保留最近缓存', '作业模块'); });
  }

  function addLog(type, label, text, source) {
    var now = new Date();
    localLogs.unshift({ time: String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0') + ':' + String(now.getSeconds()).padStart(2, '0'), type: type, label: label, text: text, source: source });
    localLogs = localLogs.slice(0, 200);
    renderLogs();
  }

  function setText(id, value) { var el = document.getElementById(id); if (el && value !== undefined && value !== null) el.textContent = value; }
  function displayValue(value, suffix) {
    if (value === undefined || value === null || value === '') return '--';
    return String(value) + (suffix || '');
  }

  function applySnapshot(data) {
    // Expected snapshot: health, motion, battery, sensors and optional network fields.
    data = normalizeSnapshot(data);
    latestRobotSnapshot = data;
    renderRobot3DDataPanels();
    if (robot3dViewer) robot3dViewer.updateJointPositions(data);
    var health = data.health || {};
    var motion = data.motion || {}, battery = data.battery || {};
    setText('robotModel', displayValue(data.robotModel || (data.identity && data.identity.model)));
    setText('currentPosition', displayValue(motion.position)); setText('currentSpeed', displayValue(motion.speed)); setText('targetPosition', displayValue(motion.target));
    // 老接口只有 tcp 时不猜测它属于哪一只手；左右手字段齐全后才展示实时值。
    setText('leftTcpPosition', displayValue(motion.leftTcp)); setText('rightTcpPosition', displayValue(motion.rightTcp));
    setText('uptime', displayValue(data.uptime)); setText('remainingTime', displayValue(battery.remainingMinutes, 'm'));
    setText('batteryLevel', displayValue(battery.percent, '%')); setText('batteryTop', displayValue(battery.percent, '%'));
    setText('batteryVoltage', displayValue(battery.voltage, 'V')); setText('batteryCurrent', displayValue(battery.current, 'A'));
    setText('batteryTemperature', displayValue(battery.temperature, '°C')); setText('cellVoltage', displayValue(battery.cellVoltage, 'V')); setText('chargeStatus', displayValue(battery.chargeStatus)); setText('chargeCycles', displayValue(battery.cycles));
    var joints = motion.joints || data.joints || [];
    for (var jointIndex = 0; jointIndex < 6; jointIndex += 1) { var jointValue = joints[jointIndex]; setText('joint' + (jointIndex + 1), typeof jointValue === 'number' ? jointValue.toFixed(1) + '°' : displayValue(jointValue)); }
    setText('payload', displayValue(data.payloadKg, 'kg'));
    setText('gripForce', displayValue(data.gripForceN, 'N'));
    setText('operationMode', displayValue(data.operationMode));
    setText('networkIp', data.network && data.network.ip ? 'IP ' + data.network.ip : 'IP --');
    setText('alertCount', displayValue(health.alertCount)); setText('alertBannerCount', displayValue(health.alertCount));
    var sensorFault = false;
    if (data.sensors) { var sensorNames = ['lidar','depthCamera','forceSensor','bumper','camera','network']; document.querySelectorAll('#sensorRow .sensor-dot').forEach(function(dot, index) { var sensorState = data.sensors[sensorNames[index]]; var stateClass = sensorVisualState(sensorNames[index], sensorState); if (stateClass === 'red') sensorFault = true; dot.className = 'sensor-dot ' + stateClass; }); }
    var rank = { normal: 0, info: 1, warning: 2, critical: 3, emergency: 4 };
    var healthLevel = health.level || 'normal';
    if (sensorFault && (rank[healthLevel] || 0) < rank.critical) healthLevel = 'critical';
    setOverallHealth(healthLevel === 'emergency' ? 'critical' : healthLevel, sensorFault && health.level === 'normal' ? '设备异常' : health.label);
  }

  function requestSnapshot() {
    var request;
    // 接口模式不能保留 HTML 里的演示初始值。正式数据尚未到来时，先明确显示
    // “--”，避免把示例数字误认成机器人实时状态。
    if (latestRobotSnapshot === null && (ROBOT_DATA_ADAPTER || ROBOT_API_BASE)) {
      applySnapshot({
        health: { level: 'info', label: '等待 ROS 数据', alertCount: 0 },
        motion: { position: null, target: null, speed: null, leftTcp: null, rightTcp: null, joints: [], jointPositions: {} },
        battery: {}, sensors: {}, network: {}
      });
    }
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.getSnapshot === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.getSnapshot());
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + '/robot/snapshot').then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    else return;
    request.then(function(data) {
      applySnapshot(data);
      // HTTP mode is decided by /healthz. A successful snapshot can still be
      // mock data or a ROS adapter that has not received robot messages yet.
      if (ROBOT_DATA_ADAPTER) setDataSourceState('connected');
    }).catch(function() {
      activateDemoFallback();
      setDataSourceState('offline');
      addLog('warn', '警告', '实机数据暂不可用，已启用本地演示控制', '数据接口');
    });
  }

  function backendHealthUrl() {
    return ROBOT_API_BASE.replace(/\/api\/v1\/?$/, '') + '/healthz';
  }

  function requestBackendHealth() {
    if (!ROBOT_API_BASE || ROBOT_DATA_ADAPTER) return;
    fetch(backendHealthUrl()).then(function(res) {
      if (!res.ok) throw new Error(res.status);
      return res.json();
    }).then(function(status) {
      deactivateDemoFallback();
      if (status.telemetryMode === 'ros' && status.dataReady === true) {
        setDataSourceState('connected');
      } else if (status.telemetryMode === 'ros') {
        setDataSourceState('waiting');
      } else if (status.telemetryMode === 'mock') {
        setDataSourceState('demo');
      } else {
        setDataSourceState('connecting');
      }
    }).catch(function() {
      activateDemoFallback();
      setDataSourceState('offline');
    });
  }

  function applyAlarms(data) {
    var payload = data && data.data ? data.data : data;
    var items = Array.isArray(payload) ? payload : (payload && payload.alarms);
    if (!Array.isArray(items)) return;
    alertData = items;
    if (robot3dViewer) robot3dViewer.setFaults(alertData);
    currentAlertIndex = 0;
    updateAlertIndicators();
    if (document.getElementById('tab-alerts').style.display !== 'none') initAlertsView();
  }

  function requestAlarms() {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.getAlarms === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.getAlarms());
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + '/alarms').then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    else return;
    request.then(applyAlarms).catch(function() {
      activateDemoFallback();
      addLog('warn', '警告', '未获取到实时告警，已启用本地演示控制', '数据接口');
    });
  }

  function invokeRobotCommand(path, body, successText) {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.sendCommand === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.sendCommand(path, body || {}));
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + path, { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body || {}) }).then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    else { alert('未接入实机控制接口。演示模式下不会发送控制命令。'); return Promise.resolve(false); }
    return request.then(function(result) {
      if (result && result.accepted === false) {
        alert(result.message || '命令未执行：对应实机服务尚未接入。');
        return false;
      }
      addLog('info', '命令', successText, '背部屏幕');
      return true;
    }).catch(function() { alert('命令未执行，请检查实机连接和权限。'); return false; });
  }

  function softEmergencyStop() { if (confirm('确认急停？机器人将停止当前运动。')) invokeRobotCommand('/commands/soft-stop', {}, '已请求急停'); }
  function exportLogs() { var text = localLogs.map(function(log) { return [log.time, log.label, log.text, log.source].join(','); }).join('\n'); var blob = new Blob(['时间,等级,内容,来源\n' + text], {type:'text/csv;charset=utf-8'}); var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'R1-diagnostic-logs.csv'; a.click(); URL.revokeObjectURL(a.href); }
  renderLogs();
  if (ROBOT_DATA_ADAPTER || ROBOT_API_BASE) {
    requestBackendHealth();
    requestSnapshot();
    requestAlarms();
    requestLogs();
    setInterval(requestBackendHealth, 1000);
    // 实机快照和告警都按 1Hz 获取；3D 视图会在两次快照之间自行平滑过渡。
    setInterval(requestSnapshot, 1000);
    setInterval(requestAlarms, 1000);
    setInterval(requestLogs, 2000);
  }

  // HTML touch handlers intentionally use these stable global entry points.
  // New features should prefer imported modules and explicit event listeners.
  Object.assign(window, {
    switchTab: switchTab,
    startDiagnose: startDiagnose,
    clearFault: clearFault,
    softEmergencyStop: softEmergencyStop,
    goToAlerts: goToAlerts,
    investigateAlert: investigateAlert,
    resolveAlert: resolveAlert,
    exportLogs: exportLogs,
    openDemoControl: openDemoControl,
    closeDemoControl: closeDemoControl,
    openRobot3DView: openRobot3DView,
    closeRobot3DView: closeRobot3DView,
    resetRobot3DView: resetRobot3DView,
    toggleRobot3DOption: toggleRobot3DOption,
    selectRobot3DData: selectRobot3DData,
    toggleRobot3DData: toggleRobot3DData,
    applyDemoStatus: applyDemoStatus,
    resetDemoStatus: resetDemoStatus,
    addDemoAlert: addDemoAlert,
    clearDemoAlerts: clearDemoAlerts
  });
