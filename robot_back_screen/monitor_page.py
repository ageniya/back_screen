"""只读实时监控页面。保留在独立模块，避免接口入口文件过于臃肿。"""

MONITOR_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>机器人背屏 · 实时数据监控</title>
  <style>
    *{box-sizing:border-box} body{margin:0;background:#111;color:#eee;font:14px -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
    main{max-width:1280px;margin:auto;padding:22px}.head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:16px}h1{font-size:22px;margin:0}.sub{color:#aaa;font-size:12px;line-height:1.6;margin-top:6px}.badge{padding:7px 10px;border-radius:5px;background:#333;color:#ddd;font-size:12px;font-weight:600;white-space:nowrap}.badge.ok{background:rgba(82,196,26,.16);color:#78df47}.badge.wait{background:rgba(250,219,20,.14);color:#fadb14}.badge.error{background:rgba(255,77,79,.15);color:#ff7875}
    .tabs{display:flex;gap:8px;border-bottom:1px solid #333;margin-bottom:14px}.tab{border:0;border-bottom:2px solid transparent;background:transparent;color:#aaa;padding:10px 20px;cursor:pointer;font:600 14px inherit}.tab.active{color:#fff;border-color:#1890ff}.page{display:none}.page.active{display:block}.section{border:1px solid #333;border-radius:7px;background:#1d1d1d;margin:12px 0;padding:14px}.section h2{font-size:15px;margin:0 0 12px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.card{min-width:0;background:#252525;border-radius:5px;padding:10px}.label{font-size:11px;color:#aaa;margin-bottom:6px}.value{color:#fff;font:600 15px "Courier New",monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.muted{color:#888}.ok{color:#78df47}.warn{color:#fadb14}.bad{color:#ff7875}.json{max-height:260px;overflow:auto;margin:0;background:#101010;border-radius:5px;padding:12px;color:#b7e4a8;font:12px/1.5 "Courier New",monospace}.notice{border-left:3px solid #1890ff;background:rgba(24,144,255,.08);padding:10px 12px;color:#b8c7d9;font-size:12px;line-height:1.6}.source-details{margin-top:12px;border-top:1px solid #333;padding-top:10px;color:#aaa;font-size:12px}.source-details summary{cursor:pointer;color:#69b1ff}.source-list{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.source-item{padding:4px 7px;border-radius:4px;background:#292929;color:#d9d9d9;font:11px "Courier New",monospace}.footer{color:#777;font-size:11px;margin:14px 0}.hidden{display:none}
    @media(max-width:760px){main{padding:14px}.head{flex-direction:column}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.tab{padding:10px 13px}}
  </style>
</head>
<body><main>
  <div class="head"><div><h1>机器人背屏 · 实时数据监控</h1><div class="sub">这是只读监控页，不控制机器人。每 5 秒自动请求一次后端；<a href="/docs" style="color:#69b1ff">/docs</a> 仅用于单次接口测试。</div></div><div id="connection" class="badge wait">正在连接</div></div>
  <div class="tabs"><button class="tab active" data-page="orin">Orin 数据</button><button class="tab" data-page="pico">Pico 数据</button></div>
  <div id="orin" class="page active"><div id="orinContent"></div></div>
  <div id="pico" class="page"><div id="picoContent"></div></div>
  <div class="footer" id="updated">尚未收到数据</div>
</main>
<script>
(function(){
  var frame=0, fetching=false;
  function escapeHtml(value){return String(value===undefined||value===null||value===''?'--':value).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function num(value,unit){var n=Number(value);return Number.isFinite(n)?n.toFixed(2)+(unit||''):'--';}
  function card(label,value,kind){return '<div class="card"><div class="label">'+escapeHtml(label)+'</div><div class="value '+(kind||'')+'" title="'+escapeHtml(value)+'">'+escapeHtml(value)+'</div></div>';}
  function section(title,body){return '<section class="section"><h2>'+escapeHtml(title)+'</h2>'+body+'</section>';}
  function grid(items){return '<div class="grid">'+items.join('')+'</div>';}
  function text(value){return value===undefined||value===null||value===''?'--':String(value);}
  function sourceDetails(sources,prefix){var items=(sources||[]).filter(function(item){return String(item).indexOf(prefix+':')===0;}).map(function(item){return String(item).slice(prefix.length+1);});if(!items.length)return '<div class="source-details">已收到数据源：未收到</div>';return '<details class="source-details"><summary>已收到 '+items.length+' 项数据源（点击展开）</summary><div class="source-list">'+items.map(function(item){return '<span class="source-item">'+escapeHtml(item)+'</span>';}).join('')+'</div></details>';}
  function objectText(value){return value&&Object.keys(value).length?JSON.stringify(value,null,2):'暂无数据';}
  function renderOrin(health,snapshot,alarms){
    var motion=snapshot.motion||{}, battery=snapshot.battery||{}, sensors=snapshot.sensors||{}, network=snapshot.network||{}, metrics=(snapshot.diagnosticMetrics||{}).systemResource||{}, errors=(snapshot.diagnosticMetrics||{}).systemResourceErrors||{};
    var alarmCount=(alarms.data||[]).length;
    var html=section('Orin 连接与诊断',grid([
      card('数据模式',text(health.telemetryMode)),card('数据状态',health.dataReady?'正在接收':'等待数据',health.dataReady?'ok':'warn'),card('最新消息年龄',num(health.lastMessageAgeSeconds,' s')),card('当前告警',alarmCount,alarmCount?'bad':'ok'),card('Orin IP',text(network.ip)),card('网络状态',text(((snapshot.diagnosticMetrics||{}).network||{}).linkState)),card('诊断结论',text((snapshot.health||{}).label))
    ])+sourceDetails(health.activeSources,'orin'));
    html+=section('Orin 资源（CPU 为各核心平均值）',grid([
      card('CPU 平均占用',num(metrics.cpuUsage,'%'),Number(metrics.cpuUsage)>=80?'bad':''),card('内存占用',num(metrics.memoryUsage,'%')),card('磁盘占用',num(metrics.diskUsage,'%')),card('GPU 占用',num(metrics.gpuUsage,'%')),card('最高温度',num(metrics.temperature,' °C'),Number(metrics.temperature)>=80?'bad':''),card('CPU 告警',errors.overCpu?'存在告警':'正常',errors.overCpu?'bad':'ok'),card('内存告警',errors.overMemory?'存在告警':'正常',errors.overMemory?'bad':'ok'),card('温度告警',errors.overTemperature?'存在告警':'正常',errors.overTemperature?'bad':'ok')
    ]));
    document.getElementById('orinContent').innerHTML=html;
  }
  function renderPico(health,snapshot){
    var metrics=(snapshot.diagnosticMetrics||{}).picoResource||{}, errors=(snapshot.diagnosticMetrics||{}).picoResourceErrors||{}, hands=snapshot.hands||{}, wrist=snapshot.wristForces||{}, network=snapshot.network||{};
    var hasResource=Object.keys(metrics).length>0, hasHands=(hands.left&&Object.keys(hands.left.jointPositions||{}).length)||(hands.right&&Object.keys(hands.right.jointPositions||{}).length);
    var html=section('Pico 连接状态',grid([
      card('Pico IP',text(network.picoIp)),card('数据来源',text((snapshot.dataSources||{}).pico)),card('资源数据',hasResource?'已接入':'暂未接入',hasResource?'ok':'warn'),card('手部关节数据',hasHands?'已接入':'暂未接入',hasHands?'ok':'warn'),card('腕部力数据',(wrist.left||wrist.right)?'已接入':'暂未接入',(wrist.left||wrist.right)?'ok':'warn')
    ])+sourceDetails(health.activeSources,'pico'));
    if(hasResource) html+=section('Pico 资源',grid([
      card('CPU 平均占用',num(metrics.cpuUsage,'%')),card('内存占用',num(metrics.memoryUsage,'%')),card('磁盘占用',num(metrics.diskUsage,'%')),card('GPU 占用',num(metrics.gpuUsage,'%')),card('最高温度',num(metrics.temperature,' °C')),card('CPU 告警',errors.overCpu?'存在告警':hasResource?'正常':'--',errors.overCpu?'bad':'ok'),card('内存告警',errors.overMemory?'存在告警':hasResource?'正常':'--',errors.overMemory?'bad':'ok'),card('温度告警',errors.overTemperature?'存在告警':hasResource?'正常':'--',errors.overTemperature?'bad':'ok')
    ]));
    if(hands.left&&Object.keys(hands.left.jointPositions||{}).length) html+=section('左手关节数据','<pre class="json">'+escapeHtml(objectText(hands.left))+'</pre>');
    if(hands.right&&Object.keys(hands.right.jointPositions||{}).length) html+=section('右手关节数据','<pre class="json">'+escapeHtml(objectText(hands.right))+'</pre>');
    if(wrist.left||wrist.right) html+=section('左 / 右腕部六维力','<pre class="json">'+escapeHtml(JSON.stringify({left:wrist.left||null,right:wrist.right||null},null,2))+'</pre>');
    if(!hasResource&&!hasHands&&!wrist.left&&!wrist.right) html+='<div class="notice">当前只收到 Pico 网络状态，尚未收到 Pico 资源、手部或腕部数据。对应 ROS2 节点开始发布后，本页会自动出现该数据分类。</div>';
    document.getElementById('picoContent').innerHTML=html;
  }
  async function refresh(){
    if(fetching)return;fetching=true;
    try{
      var responses=await Promise.all([fetch('/healthz?frame='+Date.now(),{cache:'no-store'}),fetch('/api/v1/robot/snapshot?frame='+Date.now(),{cache:'no-store'}),fetch('/api/v1/alarms?frame='+Date.now(),{cache:'no-store'})]);
      if(!responses[0].ok||!responses[1].ok||!responses[2].ok)throw Error('HTTP '+responses.map(function(r){return r.status;}).join('/'));
      var values=await Promise.all(responses.map(function(r){return r.json();}));
      frame++;var health=values[0],snapshot=values[1],alarms=values[2],badge=document.getElementById('connection');
      badge.className='badge '+(health.dataReady?'ok':'wait');badge.textContent=health.dataReady?'第 '+frame+' 帧 · 正在接收':'第 '+frame+' 帧 · 等待 ROS 数据';
      renderOrin(health,snapshot,alarms);renderPico(health,snapshot);
      document.getElementById('updated').textContent='最后成功刷新：'+new Date().toLocaleTimeString()+' · 每 5 秒一次 · 第 '+frame+' 帧';
    }catch(error){var badge=document.getElementById('connection');badge.className='badge error';badge.textContent='接口不可用';document.getElementById('updated').textContent='最后请求失败：'+new Date().toLocaleTimeString();}
    finally{fetching=false;}
  }
  Array.prototype.forEach.call(document.querySelectorAll('.tab'),function(button){button.addEventListener('click',function(){Array.prototype.forEach.call(document.querySelectorAll('.tab'),function(el){el.classList.toggle('active',el===button);});Array.prototype.forEach.call(document.querySelectorAll('.page'),function(el){el.classList.toggle('active',el.id===button.dataset.page);});});});
  refresh();setInterval(refresh,5000);
}());
</script></body></html>"""
