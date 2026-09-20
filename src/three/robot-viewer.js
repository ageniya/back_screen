import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from 'urdf-loader';

const PACKAGE_URL = '/models/wa-t-package/opt/ros/humble/share/wa_t_description/';

const PART_JOINTS = {
  left_arm: ['Shoulder_Y_L', 'Shoulder_X_L', 'Shoulder_Z_L', 'Elbow_L', 'Wrist_Z_L', 'Wrist_Y_L', 'Wrist_X_L'],
  right_arm: ['Shoulder_Y_R', 'Shoulder_X_R', 'Shoulder_Z_R', 'Elbow_R', 'Wrist_Z_R', 'Wrist_Y_R', 'Wrist_X_R'],
  neck: ['Neck_Z', 'Neck_Y'],
  lifting: ['Lifting_Z'],
};

const PART_LABELS = { left_arm: '左臂', right_arm: '右臂', neck: '颈部', lifting: '升降机构' };
const JOINT_LABELS = {
  Lifting_Z: '升降轴', Neck_Z: '颈部旋转轴', Neck_Y: '颈部俯仰轴',
  Shoulder_Y_L: '左肩 Y 轴', Shoulder_X_L: '左肩 X 轴', Shoulder_Z_L: '左肩 Z 轴', Elbow_L: '左肘关节', Wrist_Z_L: '左腕 Z 轴', Wrist_Y_L: '左腕 Y 轴', Wrist_X_L: '左腕 X 轴',
  Shoulder_Y_R: '右肩 Y 轴', Shoulder_X_R: '右肩 X 轴', Shoulder_Z_R: '右肩 Z 轴', Elbow_R: '右肘关节', Wrist_Z_R: '右腕 Z 轴', Wrist_Y_R: '右腕 Y 轴', Wrist_X_R: '右腕 X 轴',
};

// 离线展示用的安全姿态。真实 ROS 关节数据一到，就会覆盖这些值。
const DEMO_OPEN_ARM_POSE = {
  Lifting_Z: 0.12,
  Shoulder_X_L: 1.35,
  Shoulder_X_R: -1.35,
  Shoulder_Y_L: 0.08,
  Shoulder_Y_R: -0.08,
  Shoulder_Z_L: 0.1,
  Shoulder_Z_R: -0.1,
  Elbow_L: -0.25,
  Elbow_R: 0.25,
  Neck_Z: 0,
  Neck_Y: 0,
};

function severityClass(level) {
  return level === 'warning' || level === 'info' ? 'warning' : '';
}

function relatedJoints(part) {
  if (!part) return [];
  if (PART_JOINTS[part]) return PART_JOINTS[part];
  if (part.includes('left') || part.includes('_L')) return PART_JOINTS.left_arm;
  if (part.includes('right') || part.includes('_R')) return PART_JOINTS.right_arm;
  if (part.includes('neck')) return PART_JOINTS.neck;
  if (part.includes('lift')) return PART_JOINTS.lifting;
  return [part];
}

function inferPartFromAlarm(alarm) {
  const text = `${alarm.title || ''} ${alarm.desc || ''}`.toLowerCase();
  if (text.includes('左臂') || text.includes('左肩') || text.includes('左肘') || text.includes('左腕')) return 'left_arm';
  if (text.includes('右臂') || text.includes('右肩') || text.includes('右肘') || text.includes('右腕')) return 'right_arm';
  if (text.includes('颈') || text.includes('头')) return 'neck';
  if (text.includes('升降')) return 'lifting';
  return '';
}

export function createRobotViewer({ canvasHost, loadingEl, statusEl, faultsEl, tooltipEl }) {
  let renderer;
  let scene;
  let camera;
  let controls;
  let robot;
  let grid;
  let animationFrame;
  let loaded = false;
  let hoveredMeshUuid = '';
  const highlightedMaterials = [];
  const hoverMaterials = [];
  const faultByJoint = new Map();
  const jointTransitions = new Map();
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const displayOptions = { grid: true };

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function renderFaults(faults = []) {
    if (!faultsEl) return;
    if (!faults.length) {
      faultsEl.innerHTML = '<div class="robot-3d-empty">暂无异常点。接入实机后，诊断告警会自动定位到模型部位。</div>';
      return;
    }
    faultsEl.innerHTML = faults.map((fault) => {
      const level = severityClass(fault.level);
      const name = fault.partLabel || fault.part || '未映射部位';
      return `<div class="robot-3d-fault ${level}"><strong>${name}</strong><br>${fault.message || '检测到异常'}</div>`;
    }).join('');
  }

  function clearHighlights() {
    highlightedMaterials.splice(0).forEach(({ material, color, emissive, emissiveIntensity }) => {
      material.color.copy(color);
      if (material.emissive) {
        material.emissive.copy(emissive);
        material.emissiveIntensity = emissiveIntensity;
      }
    });
  }

  function clearHoverHighlight() {
    hoverMaterials.splice(0).forEach(({ material, color, emissive, emissiveIntensity }) => {
      material.color.copy(color);
      if (material.emissive) {
        material.emissive.copy(emissive);
        material.emissiveIntensity = emissiveIntensity;
      }
    });
    hoveredMeshUuid = '';
  }

  function applyHoverHighlight(mesh) {
    // URDF 的一个关节节点会包含整条子链；悬停时只处理射线实际命中的网格，
    // 避免指向肘部却把整条手臂同时点亮。
    if (!mesh || !mesh.isMesh || !mesh.material || mesh.uuid === hoveredMeshUuid) return;
    clearHoverHighlight();
    hoveredMeshUuid = mesh.uuid;
    const hoverColor = new THREE.Color('#91D5FF');
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    materials.forEach((material) => {
      if (!material || hoverMaterials.some((entry) => entry.material === material)) return;
      hoverMaterials.push({
        material,
        color: material.color.clone(),
        emissive: material.emissive ? material.emissive.clone() : new THREE.Color(),
        emissiveIntensity: material.emissiveIntensity || 0,
      });
      material.color.lerp(hoverColor, 0.32);
      if (material.emissive) {
        material.emissive.copy(hoverColor);
        material.emissiveIntensity = 0.18;
      }
    });
  }

  function highlightJoints(faults) {
    if (!robot) return;
    clearHoverHighlight();
    clearHighlights();
    faults.forEach((fault) => {
      const color = severityClass(fault.level) ? new THREE.Color('#FADB14') : new THREE.Color('#FF4D4F');
      relatedJoints(fault.part || '').forEach((jointName) => {
        const joint = robot.joints[jointName];
        if (!joint) return;
        joint.traverse((object) => {
          if (!object.isMesh || !object.material) return;
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => {
            if (!material || highlightedMaterials.some((entry) => entry.material === material)) return;
            highlightedMaterials.push({
              material,
              color: material.color.clone(),
              emissive: material.emissive ? material.emissive.clone() : new THREE.Color(),
              emissiveIntensity: material.emissiveIntensity || 0,
            });
            material.color.lerp(color, 0.55);
            if (material.emissive) {
              material.emissive.copy(color);
              material.emissiveIntensity = 0.3;
            }
          });
        });
      });
    });
  }

  function setFaults(rawFaults = []) {
    const faults = rawFaults.map((fault) => ({
      ...fault,
      part: fault.part || inferPartFromAlarm(fault),
      partLabel: fault.partLabel || PART_LABELS[fault.part] || (fault.part ? fault.part : '未定位部位'),
    }));
    faultByJoint.clear();
    faults.forEach((fault) => relatedJoints(fault.part || '').forEach((jointName) => faultByJoint.set(jointName, fault)));
    renderFaults(faults);
    highlightJoints(faults);
  }

  function hideTooltip() {
    if (tooltipEl) tooltipEl.style.display = 'none';
    clearHoverHighlight();
    if (renderer) renderer.domElement.style.cursor = 'grab';
  }

  function findParentJoint(object) {
    let node = object;
    while (node && node !== robot) {
      if (node.isURDFJoint) return node;
      node = node.parent;
    }
    return null;
  }

  function showTooltip(event) {
    if (!robot || !renderer || !tooltipEl) return;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObject(robot, true)[0];
    const joint = hit ? findParentJoint(hit.object) : null;
    if (!joint) {
      hideTooltip();
      return;
    }

    applyHoverHighlight(hit.object);

    const jointName = joint.urdfName || joint.name;
    const title = JOINT_LABELS[jointName] || jointName;
    const fault = faultByJoint.get(jointName);
    const isLinear = joint.jointType === 'prismatic';
    const value = typeof joint.angle === 'number'
      ? (isLinear ? `${joint.angle.toFixed(3)} m` : `${THREE.MathUtils.radToDeg(joint.angle).toFixed(1)}°`)
      : '固定连接';
    const stateClass = fault ? severityClass(fault.level) ? 'tooltip-warning' : 'tooltip-critical' : 'tooltip-normal';
    const stateText = fault ? `${fault.level === 'warning' || fault.level === 'info' ? '警告' : '异常'}：${fault.message || fault.title || '请检查'}` : '状态正常';
    tooltipEl.innerHTML = `<strong>${title}</strong><span>关节名：${jointName}</span><br><span>实时位置：${value}</span><br><span class="${stateClass}">${stateText}</span>`;
    tooltipEl.style.display = 'block';
    tooltipEl.style.left = `${Math.min(event.clientX - rect.left + 14, rect.width - 235)}px`;
    tooltipEl.style.top = `${Math.min(event.clientY - rect.top + 14, rect.height - 96)}px`;
    renderer.domElement.style.cursor = 'pointer';
  }

  function updateJointPositions(snapshot) {
    if (!robot) return;
    const motion = snapshot.motion || {};
    // 实机适配约定：jointPositions 的键为 URDF 关节名，值为 ROS 弧度值。
    const jointPositions = motion.jointPositions || snapshot.jointPositions || {};
    Object.entries(jointPositions).forEach(([name, value]) => {
      if (robot.joints[name] && typeof value === 'number' && Number.isFinite(value)) {
        jointTransitions.set(name, {
          from: robot.joints[name].angle,
          to: value,
          startedAt: performance.now(),
        });
      }
    });
  }

  function smoothJointMotion() {
    if (!robot || !jointTransitions.size) return;
    const now = performance.now();
    jointTransitions.forEach((transition, name) => {
      const joint = robot.joints[name];
      if (!joint || typeof joint.angle !== 'number') return;
      // 后端每秒更新一次，前端在相邻数据点间以恒定速度插值。
      const progress = Math.min((now - transition.startedAt) / 1000, 1);
      joint.setJointValue(THREE.MathUtils.lerp(transition.from, transition.to, progress));
      if (progress >= 1) jointTransitions.delete(name);
    });
  }

  function resetView() {
    if (!camera || !controls) return;
    // 默认让机器人填满主要画面，仍可用滚轮和右键继续调整。
    camera.position.set(2.35, 1.75, 3.35);
    controls.target.set(0, 1.05, 0);
    controls.update();
  }

  function toggleOption(option) {
    if (!(option in displayOptions)) return false;
    displayOptions[option] = !displayOptions[option];
    if (option === 'grid' && grid) grid.visible = displayOptions.grid;
    return displayOptions[option];
  }

  function resize() {
    if (!renderer || !camera || !canvasHost) return;
    const width = canvasHost.clientWidth;
    const height = canvasHost.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function animate() {
    animationFrame = requestAnimationFrame(animate);
    smoothJointMotion();
    controls?.update();
    renderer?.render(scene, camera);
  }

  function initialize() {
    if (renderer || !canvasHost) return;
    scene = new THREE.Scene();
    scene.fog = new THREE.Fog('#1c2025', 6, 13);
    camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    canvasHost.appendChild(renderer.domElement);
    renderer.domElement.addEventListener('pointermove', showTooltip);
    renderer.domElement.addEventListener('pointerleave', hideTooltip);
    renderer.domElement.addEventListener('contextmenu', (event) => event.preventDefault());

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = true;
    controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
    controls.minDistance = 1.5;
    controls.maxDistance = 9;
    controls.maxPolarAngle = Math.PI * 0.78;
    resetView();

    scene.add(new THREE.HemisphereLight('#dfe9ff', '#20242a', 2.6));
    const keyLight = new THREE.DirectionalLight('#ffffff', 2.8);
    keyLight.position.set(3, 5, 4);
    scene.add(keyLight);
    const edgeLight = new THREE.DirectionalLight('#6ca9ff', 1.6);
    edgeLight.position.set(-4, 2, -3);
    scene.add(edgeLight);
    grid = new THREE.GridHelper(7, 14, '#6b7179', '#42474e');
    grid.position.y = 0;
    scene.add(grid);

    const loader = new URDFLoader();
    loader.packages = { wa_t_description: PACKAGE_URL };
    loader.load(`${PACKAGE_URL}urdf/WA-T_V1_1.urdf`, (loadedRobot) => {
      robot = loadedRobot;
      // ROS/URDF uses Z-up; Three.js uses Y-up.
      robot.rotation.x = -Math.PI / 2;
      robot.traverse((object) => {
        if (object.isMesh) {
          // STL 可能复用同一个材质实例。每块网格单独复制后，悬停改色才不会
          // 连带所有使用相同材质的远处部件。
          object.material = Array.isArray(object.material)
            ? object.material.map((material) => material.clone())
            : object.material.clone();
          object.castShadow = false;
          object.receiveShadow = false;
        }
      });
      scene.add(robot);
      Object.entries(DEMO_OPEN_ARM_POSE).forEach(([name, value]) => robot.setJointValue(name, value));
      loaded = true;
      if (loadingEl) loadingEl.style.display = 'none';
      setStatus('演示姿态：双臂张开 · 实机数据会自动覆盖');
      renderFaults([]);
    }, undefined, () => {
      setStatus('模型加载失败，请检查本机资源');
      if (loadingEl) loadingEl.textContent = '模型加载失败';
    });

    window.addEventListener('resize', resize);
    resize();
    animate();
  }

  function open() {
    initialize();
    requestAnimationFrame(resize);
  }

  function destroy() {
    if (animationFrame) cancelAnimationFrame(animationFrame);
    window.removeEventListener('resize', resize);
    renderer?.domElement.removeEventListener('pointermove', showTooltip);
    renderer?.domElement.removeEventListener('pointerleave', hideTooltip);
    renderer?.dispose();
  }

  return { open, resetView, toggleOption, setFaults, updateJointPositions, destroy, get loaded() { return loaded; } };
}
