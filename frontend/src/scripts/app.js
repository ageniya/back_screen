import { normalizeSnapshot, normalizeWorkSummary } from '../api/robot-contract.js';
import { createRobotViewer } from '../three/robot-viewer.js';

// In API mode the server is the single source of truth for overall health.
// Initialise the configured data source before rendering.
var ROBOT_DATA_ADAPTER = window.ROBOT_DATA_ADAPTER || null;
var ROBOT_API_BASE = window.ROBOT_DIAGNOSTIC_API || '';
var robot3dViewer = null;
var latestRobotSnapshot = null;
// 信息框按打开顺序排列：左上、右上、左下、右下；关闭任一框后其余自动前移。
var robot3DDataViews = ['motion'];

// ==================== REAL-TIME CLOCK ====================
  function updateClock() {
    var now = new Date();
    var h = String(now.getHours()).padStart(2, '0');
    var m = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('clockDisplay').textContent = h + ':' + m;
  }
  updateClock();
  setInterval(updateClock, 10000); // update every 10s

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

  // ==================== TAB SWITCHING ====================
  function switchTab(tabId, btn) {
    // 离开工具页时暂停隐藏的 3D WebGL 渲染，避免在状态页仍占用 Pico CPU。
    // 3D 初始化/销毁异常不能影响最基本的页面导航。
    if (tabId !== 'tools' && robot3dViewer && typeof robot3dViewer.pause === 'function') {
      try { robot3dViewer.pause(); } catch (error) { console.warn('暂停 3D 视图失败，不影响切页：', error); }
    }
    // Hide all tab contents
    var contents = document.querySelectorAll('.tab-content');
    contents.forEach(function(c) { c.style.display = 'none'; });
    // Show selected
    var selectedContent = document.getElementById('tab-' + tabId);
    if (!selectedContent) return;
    selectedContent.style.display = 'flex';

    // Update nav active state
    var tabs = document.querySelectorAll('.nav-tab');
    tabs.forEach(function(t) { t.classList.remove('active'); });
    if (btn) btn.classList.add('active');

    // Initialize page-specific logic when opened
    if (tabId === 'alerts') initAlertsView();
    if (tabId === 'detail') { renderSummary(); requestWorkSummary(); }
    // 3D 视图仍处于工具页内。离开工具页时已暂停 WebGL 以节省 Pico
    // 性能；切回工具页时若该视图此前打开，必须在容器重新可见后恢复渲染
    // 与尺寸计算，否则 OrbitControls 虽收到鼠标事件却没有新画面可绘制。
    if (tabId === 'tools' && robot3dViewer) {
      var robot3dView = document.getElementById('robot3dView');
      if (robot3dView && robot3dView.style.display !== 'none') {
        requestAnimationFrame(function() { robot3dViewer.open(); });
      }
    }
  }

  // ==================== DIAGNOSE BUTTON ====================
  function startDiagnose() {
    var btn = document.getElementById('btnDiagnose');
    if (btn.disabled) return;
    btn.disabled = true;
    btn.innerHTML = '&#x23F3; 诊断中...';
    invokeRobotCommand('/commands/diagnose', {}, '已刷新当前已接入数据的诊断结果').then(function(success) {
      btn.disabled = false;
      btn.innerHTML = success ? '&#x2705; 诊断已刷新' : '&#x26A0; 诊断未接入';
      setTimeout(function() { btn.innerHTML = '&#x1F504; 刷新诊断'; }, 2000);
    });
  }

  // ==================== FAULT CLEAR BUTTON ====================
  function clearFault() {
    if (!alertData.length) {
      alert('当前没有需要确认恢复的告警。');
      return;
    }
    if (!confirm('确认已人工排除故障？\n\n系统只会清除已经恢复的告警；仍在触发的故障会保留。')) return;

    var btn = document.getElementById('btnFaultClear');
    if (!btn || btn.disabled) return;
    var originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '&#x23F3; 确认中...';

    invokeRobotCommand('/alarms/clear-recovered', {}, '已请求确认已恢复告警').then(function(success) {
      if (!success) {
        btn.disabled = false;
        btn.innerHTML = originalText;
        return;
      }
      // Ask the source again instead of pretending that the client cleared a
      // fault.  The server / real diagnosis engine remains authoritative.
      requestAlarms();
      requestSnapshot();
      btn.innerHTML = '&#x2705; 已确认';
      setTimeout(function() {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }, 1800);
    });
  }

  var chassisResetPending = false;

  function updateChassisControlState(chassisState, controlState, resetStatus) {
    resetStatus = resetStatus || {};
    var emergency = chassisState && chassisState.emergency;
    var estop = document.getElementById('controlStatusBanner');
    if (estop) {
      estop.className = 'control-status-banner';
      if (resetStatus.feedbackFresh === false) {
        estop.classList.add('waiting'); estop.textContent = resetStatus.error || '等待有效底盘状态，暂不可复位';
      } else if (emergency === true) {
        estop.classList.add('triggered'); estop.textContent = '急停已触发，请释放按钮';
      } else if (resetStatus.error) {
        estop.classList.add('waiting'); estop.textContent = resetStatus.error;
      } else if (controlState === 'RESET_REQUESTED' || chassisResetPending) {
        estop.classList.add('pending'); estop.textContent = '复位中，请等待…';
      } else if (controlState === 'E_STOP_RELEASED') {
        estop.classList.add('waiting'); estop.textContent = resetStatus.resetAllowed === true
          ? '急停已释放，请点击复位' : '急停已释放；' + (resetStatus.blockReason || '暂不可复位');
      } else if (controlState === 'RESET_DONE') {
        estop.classList.add(emergency === false ? 'clear' : 'waiting');
        stop.textContent = emergency === false ? '复位完成；' : '复位完成，等待底盘急停状态确认';
      } else estop.textContent = '等待有效底盘状态';
    }
    var reset = document.getElementById('btnChassisReset');
    if (reset && !chassisResetPending) reset.disabled = resetStatus.resetAllowed !== true || controlState !== 'E_STOP_RELEASED' || emergency !== false;
    if (reset) reset.title = (resetStatus.blockReasons || []).join('\n') || resetStatus.blockReason || '点击后需二次确认';
    if (reset) reset.classList.toggle('btn-control-attention', !reset.disabled);
  }

  function runConfirmedRobotCommand(buttonId, path, promptText, pendingText, successText) {
    if (!confirm(promptText)) return;
    var button = document.getElementById(buttonId);
    if (!button || button.disabled) return;
    var originalText = button.innerHTML;
    if (buttonId === 'btnChassisReset') chassisResetPending = true;
    button.disabled = true;
    button.innerHTML = '&#x23F3; ' + pendingText;
    invokeRobotCommand(path, {}, successText).then(function(success) {
      if (buttonId === 'btnChassisReset') {
        chassisResetPending = false;
        // 等待下一份快照决定是否允许再次操作，避免沿用请求前的状态。
        button.disabled = true;
        button.innerHTML = originalText;
        requestSnapshot();
        return;
      } else button.disabled = false;
      button.innerHTML = success ? '&#x2713; 已处理' : originalText;
      if (success) setTimeout(function() { button.innerHTML = originalText; }, 2200);
    });
  }

  function requestChassisReset() {
    runConfirmedRobotCommand(
      'btnChassisReset', '/commands/chassis-reset',
      '确认向底盘发送复位指令？请先确保机器人周围安全、实体急停已释放且机器人已静止。',
      '复位中…', '复位请求已受理；请等待处理结果和底盘反馈'
    );
  }

  // ==================== ALERT BANNER CLICK ====================
  function goToAlerts() {
    alert('跳转至告警中心\n\n当前有 ' + alertData.length + ' 条未处理告警。');
    // Auto switch to alerts tab
    var alertsTab = document.querySelector('.nav-tab[data-tab="alerts"]');
    if (alertsTab) switchTab('alerts', alertsTab);
  }

  // ==================== ALERTS DATA & RENDER ====================
  var alertData = [];
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
    var values = Array.isArray(item.values) ? item.values.filter(function(value) {
      return typeof value === 'number' && Number.isFinite(value);
    }) : [];
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
    if (values.length < 2) {
      ctx.fillStyle = '#AAAAAA';
      ctx.font = '13px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('此告警未提供数值曲线，请查看告警描述。', w / 2, h / 2);
      return;
    }

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
      ctx.fillText(Number(val).toFixed(2), left - 5, ly);
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
      invokeRobotCommand('/alarms/' + item.id + '/acknowledge', {}, '已确认恢复 ' + item.code)
        .then(function(success) { if (success) acknowledgeAlertLocally(item.id); });
    }
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
    if (robot3dViewer) robot3dViewer.pause();
    document.getElementById('robot3dView').style.display = 'none';
    document.getElementById('robot3dEntry').style.display = 'block';
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

  function getRobot3DDataPanel(view, data) {
    var motion = data.motion || {}, battery = data.battery || {}, sensors = data.sensors || {}, hands = data.hands || {}, wristForces = data.wristForces || {}, upperLimbState = data.upperLimbState || {};
    var rows = [];
    var title = '';
    if (view === 'motion') {
      title = '运动状态';
      rows = [['当前位置', motion.position], ['目标点', motion.target], ['速度', motion.speed], ['左手 TCP', motion.leftTcp], ['右手 TCP', motion.rightTcp]];
    } else if (view === 'joints') {
      title = '关节状态';
      var positions = motion.jointPositions || {};
      var entries = Object.entries(positions);
      if (upperLimbState.commandName) rows.push(['上肢命令', upperLimbState.commandName]);
      if (upperLimbState.commandName || upperLimbState.commandNumber !== undefined) {
        rows.push(['左臂奇异位形', upperLimbState.leftArmSingular ? '是' : '否']);
        rows.push(['右臂奇异位形', upperLimbState.rightArmSingular ? '是' : '否']);
      }
      rows = rows.concat(entries.length ? entries.map(function(entry) {
        return [entry[0], (Number(entry[1]) * 180 / Math.PI).toFixed(2) + '°'];
      }) : (motion.joints || []).slice(0, 6).map(function(value, index) { return ['J' + (index + 1), value]; }));
    } else if (view === 'battery') {
      title = '电池状态';
      [battery, data.battery2 || {}].forEach(function(pack, index) {
        var name = '电池' + (index + 1) + ' ';
        rows = rows.concat([[name + '电量', displayValue(pack.percent, '%')], [name + '电压', displayValue(pack.voltage, 'V')], [name + '电流', displayValue(pack.current, 'A')], [name + '温度', displayValue(pack.temperature, '°C')], [name + '状态', pack.chargeStatus]]);
      });
    } else {
      title = '传感器状态';
      rows = [['雷达①', sensors.lidar1], ['雷达②', sensors.lidar2], ['头部相机', sensors.headCamera], ['左腕相机', sensors.leftWristCamera], ['右腕相机', sensors.rightWristCamera], ['六维力', sensors.forceSensor], ['碰撞条', sensors.bumper], ['网络', sensors.network]].map(function(item) {
        var state = sensorVisualState(item[0] === '碰撞条' ? 'bumper' : 'sensor', item[1]);
        return [item[0], state === 'green' ? '正常' : state === 'yellow' ? '已触发' : state === 'red' ? '离线' : '未知', state];
      });
      ['left', 'right'].forEach(function(side) {
        var force = wristForces[side] && wristForces[side].force;
        var joints = hands[side] && hands[side].jointPositions;
        var sideLabel = side === 'left' ? '左' : '右';
        if (force && force.x !== null && force.y !== null && force.z !== null) rows.push([sideLabel + '腕力', 'X' + Number(force.x).toFixed(2) + ' Y' + Number(force.y).toFixed(2) + ' Z' + Number(force.z).toFixed(2) + ' N']);
        if (joints && Object.keys(joints).length) rows.push([sideLabel + '手关节', Object.keys(joints).length + ' 个实时数据']);
      });
    }
    return { title: title, rows: rows };
  }

  function renderRobot3DDataPanels() {
    var leftDock = document.getElementById('robot3dDataLeft');
    var rightDock = document.getElementById('robot3dDataRight');
    if (!leftDock || !rightDock) return;
    var data = latestRobotSnapshot || {};
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

  // ==================== SUMMARY DATA & RENDER ====================
  var summaryData = {
    lastChargeAh: null, triggerAh: null, lastChargeEndTs: null,
    chargeStartTs: null, ratedLoad: null, tasks: []
  };

  function renderSummary() {
    var d = summaryData;
    var tasks = Array.isArray(d.tasks) ? d.tasks.filter(function(task) {
      return task && typeof task === 'object';
    }) : [];
    var numberOrNull = function(value) {
      if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
      var number = Number(value);
      return Number.isFinite(number) ? number : null;
    };
    var consumptionAh = numberOrNull(d.consumptionAh);
    if (consumptionAh === null) {
      var lastChargeAh = numberOrNull(d.lastChargeAh);
      var triggerAh = numberOrNull(d.triggerAh);
      consumptionAh = lastChargeAh !== null && triggerAh !== null ? lastChargeAh - triggerAh : null;
    }
    var durationSec = numberOrNull(d.durationSec);
    if (durationSec === null) {
      var lastChargeEndTs = numberOrNull(d.lastChargeEndTs);
      var chargeStartTs = numberOrNull(d.chargeStartTs);
      durationSec = lastChargeEndTs !== null && chargeStartTs !== null ? chargeStartTs - lastChargeEndTs : null;
    }
    if (durationSec !== null && durationSec < 0) durationSec = null;
    if (consumptionAh !== null && consumptionAh < 0) consumptionAh = null;
    var avgCurrent = numberOrNull(d.avgCurrent);
    if (avgCurrent === null && consumptionAh !== null && durationSec && durationSec > 0) avgCurrent = consumptionAh / (durationSec / 3600);
    var ratedLoad = numberOrNull(d.ratedLoad);
    var weights = tasks.map(function(task) { return numberOrNull(task.weight); });
    var completeWeights = tasks.length > 0 && weights.every(function(weight) { return weight !== null && weight >= 0; });
    var totalWeight = completeWeights ? weights.reduce(function(acc, weight) { return acc + weight; }, 0) : null;
    var avgRate = ratedLoad && ratedLoad > 0 && completeWeights ? totalWeight / tasks.length / ratedLoad * 100 : null;
    var hasRecord = tasks.length > 0 || consumptionAh !== null || durationSec !== null;

    document.getElementById('summaryStatus').textContent = hasRecord ? '本次作业数据' : '暂未接入作业记录';
    document.getElementById('kpiConsumption').innerHTML = consumptionAh === null ? '--' : consumptionAh.toFixed(1) + '<span class="kpi-unit">Ah</span>';
    document.getElementById('kpiDuration').innerHTML = durationSec === null ? '--' : durationSec.toLocaleString() + '<span class="kpi-unit">s</span>';
    if (durationSec === null) {
      document.getElementById('kpiDurationHMS').textContent = '等待作业开始与结束时间';
    } else {
      var h = Math.floor(durationSec / 3600);
      var m = Math.floor((durationSec % 3600) / 60);
      var s = Math.floor(durationSec % 60);
      document.getElementById('kpiDurationHMS').textContent = h + 'h ' + m + 'm ' + s + 's';
    }
    document.getElementById('kpiCurrent').innerHTML = avgCurrent === null ? '--' : avgCurrent.toFixed(1) + '<span class="kpi-unit">A</span>';
    document.getElementById('loadTotal').textContent = totalWeight === null ? '--' : totalWeight.toFixed(1);
    document.getElementById('loadRate').textContent = avgRate === null ? '--' : avgRate.toFixed(1);
    document.getElementById('loadRateLabel').textContent = ratedLoad && ratedLoad > 0 ? '平均负载率（额定 ' + ratedLoad.toFixed(1) + 'kg）' : '平均负载率（额定负载未提供）';
    document.getElementById('taskTableTitle').innerHTML = hasRecord
      ? '任务明细 · 搬运 <strong style="color:#FFFFFF;font-family:\'Courier New\',monospace;">' + tasks.length + '</strong> 次'
      : '任务明细 · 暂未接入任务系统';

    var tbody = document.getElementById('taskTableBody');
    tbody.innerHTML = '';
    if (!tasks.length) {
      tbody.innerHTML = '<tr><td class="summary-empty" colspan="5">暂无搬运记录。需任务系统提供任务明细；连接充电器不会自动生成搬运记录。</td></tr>';
      return;
    }
    tasks.forEach(function(task, i) {
      var weight = numberOrNull(task.weight);
      if (weight !== null && weight < 0) weight = null;
      var rate = ratedLoad && ratedLoad > 0 && weight !== null ? weight / ratedLoad * 100 : null;
      var cls = rate >= 90 ? 'danger' : rate >= 80 ? 'warn' : '';
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td style="color:#AAAAAA;">' + (i + 1) + '</td>' +
        '<td></td>' +
        '<td>' + (weight === null ? '--' : weight.toFixed(1) + ' kg') + '</td>' +
        '<td class="load-pct' + (cls ? ' ' + cls : '') + '">' + (rate === null ? '--' : rate.toFixed(1) + '%') + '</td>' +
        '<td style="color:#AAAAAA;"></td>';
      tr.children[1].textContent = task.name || '未命名任务';
      tr.children[4].textContent = task.time || '--';
      tbody.appendChild(tr);
    });
  }

  function initAlertsView() {
    updateAlertPageTime();
    renderAlertList();
    setTimeout(function() {
      if (alertData.length) selectAlert(Math.min(currentAlertIndex, alertData.length - 1));
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
      connecting: '接口连接中',
      waiting: '等待实机数据',
      // ROS 已连接只代表收到了某一路 ROS 消息；是否为完整实机数据要看
      // /healthz 的 activeSources，不能在背屏上笼统标成“实机数据”。
      connected: ROBOT_DATA_ADAPTER ? '本地数据' : 'ROS 数据',
      offline: '接口离线'
    };
    el.className = 'data-source ' + state;
    el.textContent = labels[state] || labels.offline;
  }

  function setDataFreshness(status) {
    var el = document.getElementById('dataFreshness');
    var note = document.getElementById('dataQualityNote');
    if (!el) return;
    var age = Number(status && status.lastMessageAgeSeconds);
    el.className = 'data-freshness';
    if (note) note.className = 'data-note';
    if (!status || status.dataReady !== true || !Number.isFinite(age)) {
      el.classList.add('stale');
      el.textContent = '等待 ROS 数据';
      if (note) { note.classList.add('waiting'); note.textContent = '等待 ROS 数据：后端已启动，但尚未收到任何实机消息。'; }
      return;
    }
    if (age > 5) {
      el.classList.add('stale');
      el.textContent = '数据过期 ' + age.toFixed(1) + 's';
      if (note) { note.classList.add('stale'); note.textContent = '数据已过期：最后一帧来自 ' + age.toFixed(1) + ' 秒前，请检查对应 ROS 节点。'; }
      return;
    }
    el.classList.add('fresh');
    el.textContent = '更新 ' + age.toFixed(1) + 's 前';
    if (note) { note.classList.add('fresh'); note.innerHTML = '数据正常更新；<b>--</b> 表示未接入或当前无消息，<b>0.0</b> 表示收到的真实数值为零。'; }
  }

  function clearRealtimeSnapshot(label) {
    // 失去后端连接时，不能把最后一帧继续留在状态页冒充实时值，
    // 也不能自动切换成演示数据；静态页面功能仍可继续使用。
    applySnapshot({
      health: { level: 'info', label: label || '接口离线', alertCount: 0 },
      motion: { position: null, target: null, speed: null, leftTcp: null, rightTcp: null, joints: [], jointSummary: [], jointPositions: {} },
      battery: {}, battery2: {}, sensors: {}, network: {}, wristForces: {},
      diagnosticMetrics: {}, operationMode: null, uptime: null, payloadKg: null
    });
  }

  setDataSourceState(ROBOT_DATA_ADAPTER || ROBOT_API_BASE ? 'connecting' : 'offline');
  var localLogs = [];

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
    summaryData = Object.assign({ tasks: [] }, data);
    setText('summaryUpdated', '来源：作业记录接口 · 更新于 ' + new Date().toLocaleTimeString() + ' · 每 5 秒刷新');
    renderSummary();
  }

  function requestWorkSummary() {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.getWorkSummary === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.getWorkSummary());
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + '/work-summary').then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    if (request) request.then(applyWorkSummary).catch(function() { setText('summaryStatus', '作业记录接口离线'); setText('summaryUpdated', '本次刷新失败，以下为上次缓存，不代表实时记录。'); });
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

  function displayNumber(value, suffix) {
    if (value === undefined || value === null || value === '') return '--';
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(1) + (suffix || '') : String(value) + (suffix || '');
  }

  function displayJointName(name) {
    var names = {
      Shoulder_Y_L: '左肩 Y', Shoulder_X_L: '左肩 X', Shoulder_Z_L: '左肩 Z', Elbow_L: '左肘', Wrist_Z_L: '左腕 Z', Wrist_Y_L: '左腕 Y', Wrist_X_L: '左腕 X',
      Shoulder_Y_R: '右肩 Y', Shoulder_X_R: '右肩 X', Shoulder_Z_R: '右肩 Z', Elbow_R: '右肘', Wrist_Z_R: '右腕 Z', Wrist_Y_R: '右腕 Y', Wrist_X_R: '右腕 X',
      Neck_Z: '颈部 Z', Neck_Y: '颈部 Y', Lifting_Z: '升降轴'
    };
    return names[name] || name || '--';
  }

  function setResourceAlertText(elementId, hasAlert, unavailable) {
    var element = document.getElementById(elementId);
    if (!element) return;
    if (unavailable) {
      element.textContent = '--';
      element.style.color = '#AAAAAA';
      return;
    }
    element.textContent = hasAlert ? '存在告警' : '正常';
    // 不继承演示模式初始页面写入的黄色；资源告警统一为红/绿两种语义。
    element.style.color = hasAlert ? '#FF4D4F' : '#52C41A';
  }

  function renderResource(data, source) {
    var metrics = (data.diagnosticMetrics || {})[source === 'orin' ? 'systemResource' : 'picoResource'];
    // 原始资源标志可能每一帧跳变。资源栏只使用后端确认满 5 秒后的结果。
    var errors = (data.resourceAlerts || {})[source] || {};
    var hasMetrics = metrics && Object.keys(metrics).some(function(key) { return metrics[key] !== null && metrics[key] !== undefined; });
    if (!hasMetrics) {
      ['Cpu', 'Memory', 'Disk', 'Gpu', 'Temperature'].forEach(function(field) { setText(source + field, '--'); });
      setResourceAlertText(source + 'ResourceError', false, true);
      setText(source + 'ResourceSource', '--');
      return;
    }
    setText(source + 'Cpu', displayNumber(metrics.cpuUsage, '%'));
    setText(source + 'Memory', displayNumber(metrics.memoryUsage));
    setText(source + 'Disk', displayNumber(metrics.diskUsage));
    setText(source + 'Gpu', displayNumber(metrics.gpuUsage, '%'));
    setText(source + 'Temperature', displayNumber(metrics.temperature, '°C'));
    setResourceAlertText(source + 'ResourceError', Object.keys(errors).some(function(key) { return errors[key] === true; }));
    setText(source + 'ResourceSource', source === 'orin' ? 'Orin' : 'Pico');
  }

  function applySnapshot(data) {
    // Expected snapshot: health, motion, battery, sensors and optional network fields.
    data = normalizeSnapshot(data);
    latestRobotSnapshot = data;
    var chassisState = (data.diagnosticMetrics || {}).chassisState;
    updateChassisControlState(chassisState, data.controlState, data.chassisReset);
    // 3D 页面未打开时不重建隐藏的信息卡片，避免状态页刷新时产生额外布局开销。
    var robot3dPage = document.getElementById('robot3dView');
    if (robot3dPage && robot3dPage.style.display !== 'none') renderRobot3DDataPanels();
    if (robot3dViewer) robot3dViewer.updateJointPositions(data);
    var health = data.health || {};
    var motion = data.motion || {}, battery = data.battery || {}, wristForces = data.wristForces || {};
    setText('robotModel', displayValue(data.robotModel || (data.identity && data.identity.model)));
    setText('currentPosition', displayValue(motion.position)); setText('currentSpeed', displayValue(motion.speed)); setText('targetPosition', displayValue(motion.target));
    // 老接口只有 tcp 时不猜测它属于哪一只手；左右手字段齐全后才展示实时值。
    setText('leftTcpPosition', displayValue(motion.leftTcp)); setText('rightTcpPosition', displayValue(motion.rightTcp));
    setText('uptime', displayValue(data.uptime));
    var battery2 = data.battery2 || {};
    setText('remainingTime', '1: ' + displayValue(battery.remainingMinutes, 'm') + ' / 2: ' + displayValue(battery2.remainingMinutes, 'm'));
    setText('batteryLevel', displayNumber(battery.percent, '%')); setText('batteryTop', displayNumber(battery.percent, '%'));
    setText('batteryVoltage', displayNumber(battery.voltage, 'V')); setText('batteryCurrent', displayNumber(battery.current, 'A'));
    setText('batteryTemperature', displayNumber(battery.temperature, '°C')); setText('cellVoltage', displayNumber(battery.cellVoltage, 'V')); setText('chargeStatus', displayValue(battery.chargeStatus));
    setText('battery2Top', displayNumber(battery2.percent, '%'));
    setText('battery2Level', displayNumber(battery2.percent, '%'));
    setText('battery2Voltage', displayNumber(battery2.voltage, 'V'));
    setText('battery2Current', displayNumber(battery2.current, 'A'));
    setText('battery2Temperature', displayNumber(battery2.temperature, '°C'));
    setText('battery2CellVoltage', displayNumber(battery2.cellVoltage, 'V'));
    setText('battery2ChargeStatus', displayValue(battery2.chargeStatus));
    [['chargeStatus', battery.chargeStatus], ['battery2ChargeStatus', battery2.chargeStatus]].forEach(function(item) {
      var statusElement = document.getElementById(item[0]);
      if (statusElement) statusElement.style.color = !item[1] || item[1] === '未知'
        ? '#AAAAAA' : item[1] === '充电中' ? '#FADB14' : '#52C41A';
    });
    // 电池和两台计算单元各自占一行，电池恢复后不能覆盖 Orin 资源。
    renderResource(data, 'orin');
    renderResource(data, 'pico');
    var joints = motion.joints || data.joints || [];
    var jointSummary = motion.jointSummary || [];
    for (var jointIndex = 0; jointIndex < 6; jointIndex += 1) {
      var summaryItem = jointSummary[jointIndex] || {};
      var jointValue = summaryItem.degrees !== undefined ? summaryItem.degrees : joints[jointIndex];
      setText('jointLabel' + (jointIndex + 1), summaryItem.name ? displayJointName(summaryItem.name) : '关节 ' + (jointIndex + 1));
      setText('joint' + (jointIndex + 1), typeof jointValue === 'number' ? jointValue.toFixed(1) + '°' : displayValue(jointValue));
    }
    setText('payload', displayNumber(data.payloadKg, 'kg'));
    // 当前实机没有提供已经标定的夹爪压力。这里展示左右腕部六维力的合力，
    // 让两只手各自有实时数值；它是腕部受力，不应和未来的手指夹爪压力混用。
    ['left', 'right'].forEach(function(side) {
      var force = wristForces[side] && wristForces[side].force;
      var components = force ? [Number(force.x), Number(force.y), Number(force.z)] : [];
      var hasForce = components.length === 3 && components.every(Number.isFinite);
      var magnitude = hasForce ? Math.sqrt(components[0] * components[0] + components[1] * components[1] + components[2] * components[2]) : null;
      setText(side === 'left' ? 'leftGripForce' : 'rightGripForce', displayNumber(magnitude, 'N'));
    });
    setText('operationMode', displayValue(data.operationMode));
    var network = data.network || {};
    var ipText = [];
    var picoIp = network.picoIp || (network.deviceRole === 'pico' ? network.ip : null);
    var orinIp = network.orinIp || (network.deviceRole === 'orin' ? network.ip : null);
    if (picoIp) ipText.push('Pico ' + picoIp);
    if (orinIp) ipText.push('Orin ' + orinIp);
    if (!ipText.length && network.ip) ipText.push('IP ' + network.ip);
    setText('networkIp', ipText.length ? ipText.join('\n') : 'IP --');
    setText('alertCount', displayValue(health.alertCount)); setText('alertBannerCount', displayValue(health.alertCount));
    var sensorFault = false;
    if (data.sensors) { var sensorNames = ['lidar1','lidar2','headCamera','leftWristCamera','rightWristCamera','forceSensor','bumper','network']; document.querySelectorAll('#sensorRow .sensor-dot').forEach(function(dot, index) { var sensorState = data.sensors[sensorNames[index]]; var stateClass = sensorVisualState(sensorNames[index], sensorState); if (stateClass === 'red') sensorFault = true; dot.className = 'sensor-dot ' + stateClass; }); }
    var rank = { normal: 0, info: 1, warning: 2, critical: 3, emergency: 4 };
    var healthLevel = health.level || 'normal';
    if (sensorFault && (rank[healthLevel] || 0) < rank.critical) healthLevel = 'critical';
    setOverallHealth(chassisState && chassisState.emergency === true ? 'critical' : (healthLevel === 'emergency' ? 'critical' : healthLevel),
      chassisState && chassisState.emergency === true ? '底盘急停已触发' : (sensorFault && health.level === 'normal' ? '设备异常' : health.label));
  }

  function requestSnapshot() {
    var request;
    // 接口模式不能保留 HTML 里的演示初始值。正式数据尚未到来时，先明确显示
    // “--”，避免把示例数字误认成机器人实时状态。
    if (latestRobotSnapshot === null) {
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
      // a ROS adapter that has not received robot messages yet.
      if (ROBOT_DATA_ADAPTER) setDataSourceState('connected');
    }).catch(function() {
      clearRealtimeSnapshot('接口离线');
      setDataSourceState('offline');
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
      setDataFreshness(status);
      if (status.telemetryMode === 'ros' && status.dataReady === true) {
        setDataSourceState('connected');
      } else if (status.telemetryMode === 'ros') {
        setDataSourceState('waiting');
      } else {
        setDataSourceState('connecting');
      }
    }).catch(function() {
      clearRealtimeSnapshot('接口离线');
      setDataSourceState('offline');
      var freshness = document.getElementById('dataFreshness');
      if (freshness) { freshness.className = 'data-freshness offline'; freshness.textContent = '后端离线'; }
      var note = document.getElementById('dataQualityNote');
      if (note) { note.className = 'data-note offline'; note.textContent = '后端离线：当前页面不能代表机器人实时状态。'; }
    });
  }

  function applyAlarms(data) {
    var payload = data && data.data ? data.data : data;
    var items = Array.isArray(payload) ? payload : (payload && payload.alarms);
    if (!Array.isArray(items)) return;
    var selectedId = alertData[currentAlertIndex] && alertData[currentAlertIndex].id;
    alertData = items;
    if (robot3dViewer) robot3dViewer.setFaults(alertData);
    var selectedIndex = alertData.findIndex(function(item) { return item.id === selectedId; });
    currentAlertIndex = selectedIndex >= 0 ? selectedIndex : 0;
    updateAlertIndicators();
    if (document.getElementById('tab-alerts').style.display !== 'none') initAlertsView();
  }

  function requestAlarms() {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.getAlarms === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.getAlarms());
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + '/alarms').then(function(res) { if (!res.ok) throw new Error(res.status); return res.json(); });
    else return;
    request.then(applyAlarms).catch(function() {
      applyAlarms([]);
    });
  }

  function invokeRobotCommand(path, body, successText) {
    var request;
    if (ROBOT_DATA_ADAPTER && typeof ROBOT_DATA_ADAPTER.sendCommand === 'function') request = Promise.resolve(ROBOT_DATA_ADAPTER.sendCommand(path, body || {}));
    else if (ROBOT_API_BASE) request = fetch(ROBOT_API_BASE + path, { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(body || {}) }).then(function(res) {
      return res.json().catch(function() { return {}; }).then(function(data) {
        if (!res.ok) throw new Error(data.detail || '命令未执行，请检查实机连接和权限。');
        return data;
      });
    });
    else { alert('未接入实机控制接口，未发送控制命令。'); return Promise.resolve(false); }
    return request.then(function(result) {
      if (result && result.accepted === false) {
        alert(result.message || '命令未执行：对应实机服务尚未接入。');
        return false;
      }
      var controlCommand = path === '/commands/soft-stop' || path === '/commands/chassis-reset';
      if (controlCommand && (!result || result.accepted !== true)) {
        alert('命令未得到后端确认，请检查控制接口。');
        return false;
      }
      var message = controlCommand && result.message ? result.message : successText;
      addLog('info', '命令', message, '背部屏幕');
      if (controlCommand) alert(message);
      return true;
    }).catch(function(error) { alert(error.message || '命令未执行，请检查实机连接和权限。'); return false; });
  }

  function exportLogs() { var text = localLogs.map(function(log) { return [log.time, log.label, log.text, log.source].join(','); }).join('\n'); var blob = new Blob(['时间,等级,内容,来源\n' + text], {type:'text/csv;charset=utf-8'}); var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'R1-diagnostic-logs.csv'; a.click(); URL.revokeObjectURL(a.href); }
  renderLogs();

  // Pico 的 Firefox/触摸驱动有时只会可靠地产生按下事件：按钮会出现
  // :active 高亮，但不会随后合成 pointerup/click。因此导航以按下事件
  // 为主，其他事件只是电脑端与旧驱动的兼容兜底。
  document.querySelectorAll('.nav-tab').forEach(function(tab) {
    var lastActivationAt = 0;
    function activate(event) {
      // 多种事件可能连续到达；短时间去重以免重复初始化页面。
      var now = Date.now();
      if (now - lastActivationAt < 350) return;
      lastActivationAt = now;
      switchTab(tab.dataset.tab, tab);
    }
    tab.addEventListener('pointerdown', activate);
    tab.addEventListener('mousedown', activate);
    tab.addEventListener('touchstart', activate, { passive: true });
    tab.addEventListener('pointerup', activate);
    tab.addEventListener('click', activate);
  });

  if (!ROBOT_DATA_ADAPTER && !ROBOT_API_BASE) clearRealtimeSnapshot('接口未配置');
  if (ROBOT_DATA_ADAPTER || ROBOT_API_BASE) {
    requestBackendHealth();
    requestSnapshot();
    requestAlarms();
    requestLogs();
    // 健康状态不是高频运动数据，降低轮询频率，给触摸和页面渲染留出余量。
    setInterval(requestBackendHealth, 3000);
    // 实机快照和告警都按 1Hz 获取；3D 视图会在两次快照之间自行平滑过渡。
    setInterval(requestSnapshot, 1000);
    setInterval(requestAlarms, 2000);
    setInterval(requestLogs, 5000);
    setInterval(function() {
      var page = document.getElementById('tab-detail');
      if (page && page.style.display !== 'none') requestWorkSummary();
    }, 5000);
  }

  // HTML touch handlers intentionally use these stable global entry points.
  // New features should prefer imported modules and explicit event listeners.
  Object.assign(window, {
    switchTab: switchTab,
    startDiagnose: startDiagnose,
    clearFault: clearFault,
    requestChassisReset: requestChassisReset,
    goToAlerts: goToAlerts,
    investigateAlert: investigateAlert,
    resolveAlert: resolveAlert,
    exportLogs: exportLogs,
    openRobot3DView: openRobot3DView,
    closeRobot3DView: closeRobot3DView,
    resetRobot3DView: resetRobot3DView,
    toggleRobot3DOption: toggleRobot3DOption,
    selectRobot3DData: selectRobot3DData,
    toggleRobot3DData: toggleRobot3DData
  });
