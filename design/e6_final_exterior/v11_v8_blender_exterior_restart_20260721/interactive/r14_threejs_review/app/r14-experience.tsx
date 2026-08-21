"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

type ProductState = "follow" | "ride" | "cafe" | "focus";
type ReviewMode = "object" | "internal" | "exploded";
type InternalFilter = "all" | "power" | "drive" | "control" | "perception";
type CameraView = "hero" | "front" | "side" | "top";
type PartId =
  | "backrest"
  | "mast"
  | "footrest"
  | "table"
  | "left-lid"
  | "right-lid"
  | "left-bay"
  | "right-bay"
  | "rear-door"
  | "front-sensor"
  | "joystick";

type PartInfo = {
  id: PartId;
  code: string;
  title: string;
  short: string;
  copy: string;
  status: string;
  verified: boolean;
  action?: string;
};

type ViewerApi = {
  setProductState: (state: ProductState) => void;
  setMode: (mode: ReviewMode) => void;
  setInternalFilter: (filter: InternalFilter) => void;
  setSection: (value: number) => void;
  setCamera: (view: CameraView) => void;
  togglePart: (id: PartId) => void;
  reset: () => void;
};

const STATES: Array<{
  id: ProductState;
  index: string;
  label: string;
  caption: string;
}> = [
  { id: "follow", index: "01", label: "Follow", caption: "FOLDED / CLOSED-SURFACE INTENT" },
  { id: "ride", index: "02", label: "Ride", caption: "FOOTREST DEPLOYED" },
  { id: "cafe", index: "03", label: "Café", caption: "SINGLE SURFACE" },
  { id: "focus", index: "04", label: "Focus", caption: "DUAL SURFACE / MAST HIGH" },
];

const PARTS: Record<PartId, PartInfo> = {
  backrest: {
    id: "backrest",
    code: "A06",
    title: "标志性梯形靠背",
    short: "靠背折叠",
    copy: "页面按 R14 定义铰点在两个外观端点间插值预览。Follow 态由同一块梯形件形成完整上表面，不增加遮盖壳；连续扫掠、锁止、密封与承载尚未验证。",
    status: "R14 外观端点 + 铰点定义 · 非机构验证",
    verified: true,
    action: "切换折叠 / 直立",
  },
  mast: {
    id: "mast",
    code: "A07",
    title: "工作桅杆与光学冠梁",
    short: "桅杆升降",
    copy: "原始无壳梯形桅杆保持外露；仅 Focus 按定义升高 420 mm。Follow 安全感知依赖基座多模态系统，冠梁不是唯一或主安全链。",
    status: "外观端点已定义 · 导向/线束/器件装包未验证",
    verified: true,
    action: "升高 / 降低",
  },
  footrest: {
    id: "footrest",
    code: "A08",
    title: "单片伸缩脚踏",
    short: "脚踏伸缩",
    copy: "正常 Ride 态展开；Café 与 Focus 默认收纳，也允许按需打开。两端点沿车体 X 轴相差 220 mm。",
    status: "R14 收纳/展开外观端点 · 行程/锁止/载荷未验证",
    verified: true,
    action: "展开 / 收纳",
  },
  table: {
    id: "table",
    code: "A09",
    title: "扶手内藏桌板",
    short: "桌板取放",
    copy: "交互预览按向外翻盖、切换桌板端点、关闭扶手盖的顺序表达。桌板位于两扶手之间，摇杆始终固定在右扶手顶端；当前并非连续取放轨迹。",
    status: "展开外观端点 · 取放轨迹/支架/锁止待 STEP 验证",
    verified: false,
    action: "预览展开端点 / 隐藏",
  },
  "left-lid": {
    id: "left-lid",
    code: "A05-L",
    title: "左扶手桌板取放盖",
    short: "左扶手盖",
    copy: "盖板向外翻开后回到齐平状态。Qi 充电区随左盖运动，小屏幕留在固定母表面上，并保持前高后低的可视角。",
    status: "R14 仅有闭态几何 · 运动为评审预览",
    verified: false,
    action: "播放 105° 铰链假设",
  },
  "right-lid": {
    id: "right-lid",
    code: "A05-R",
    title: "右扶手桌板取放盖",
    short: "右扶手盖",
    copy: "盖板只负责桌板取放通道；授权键和摇杆不随盖板运动，也不会被展开桌板遮挡。",
    status: "R14 仅有闭态几何 · 运动为评审预览",
    verified: false,
    action: "播放 105° 铰链假设",
  },
  "left-bay": {
    id: "left-bay",
    code: "A04-L",
    title: "左设备仓抽屉",
    short: "左设备仓",
    copy: "点击后进入历史包装视图，并按 R14 的 300 mm 目标行程刚体分离左托盘；DFR3 历史基准为 305 mm，仅用于包络对照，不代表滑轨级联、门片或锁扣运动。",
    status: "R14 TARGET 300 · DFR3 BASELINE 305",
    verified: false,
    action: "显示 / 收起名义拉出位置",
  },
  "right-bay": {
    id: "right-bay",
    code: "A04-R",
    title: "右设备仓抽屉",
    short: "右设备仓",
    copy: "右侧托盘用于较大 COTS 设备与 16 英寸级设备包络。点击后按 R14 的 300 mm 目标行程刚体分离；DFR3 历史基准为 305 mm，不代表供应件、滑轨级联或锁止机构已经冻结。",
    status: "R14 TARGET 300 · DFR3 BASELINE 305",
    verified: false,
    action: "显示 / 收起名义拉出位置",
  },
  "rear-door": {
    id: "rear-door",
    code: "A10",
    title: "后部设备与电池服务门",
    short: "后服务门",
    copy: "R14 外观只定义了一道齐平门缝。点击后将 DFR3 历史门代理沿 X 轴分离 260 mm，仅用于查看门后接口，不代表开门方向、铰链或量产行程。",
    status: "R14 仅有门缝 · 260 mm 为查看分离量",
    verified: false,
    action: "分离查看 / 复位",
  },
  "front-sensor": {
    id: "front-sensor",
    code: "A01",
    title: "固定前部感知地平线",
    short: "前部感知带",
    copy: "R14 只定义车体前部连续烟熏暗窗及其折叠前后不变的位置；传感器种类、数量、视场、窗口材料与内部装包尚待冻结。",
    status: "R14 外观暗窗位置 · 非感知系统验证",
    verified: false,
  },
  joystick: {
    id: "joystick",
    code: "A05-J",
    title: "固定外露摇杆",
    short: "摇杆",
    copy: "摇杆始终位于右扶手顶端的浅落位中，不随桌板或扶手盖消失，不放在桌板后方。",
    status: "R14 四态位置与可见性检查 · 操纵包络/强度未验证",
    verified: true,
  },
};

const STRUCTURE_ORDER: PartId[] = [
  "backrest",
  "mast",
  "footrest",
  "table",
  "left-lid",
  "right-lid",
  "left-bay",
  "right-bay",
  "rear-door",
  "front-sensor",
  "joystick",
];

const INTERNAL_FILTERS: Array<{ id: InternalFilter; label: string }> = [
  { id: "all", label: "All" },
  { id: "power", label: "Power" },
  { id: "drive", label: "Drive" },
  { id: "control", label: "Control" },
  { id: "perception", label: "Sense" },
];

const CAMERA_VIEWS: Array<{ id: CameraView; label: string }> = [
  { id: "hero", label: "¾" },
  { id: "front", label: "Front" },
  { id: "side", label: "Side" },
  { id: "top", label: "Top" },
];

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

function resolvePart(name: string): PartId | null {
  const value = name.toLowerCase();
  if (value.includes("joystick")) return "joystick";
  if (
    value.includes("pivot_a05_left_lid") ||
    value.includes("left_qi_flush") ||
    value.includes("left_qi_target_ring")
  ) return "left-lid";
  if (value.includes("perception_horizon")) return "front-sensor";
  if (value.includes("equipment_door_seam") && value.includes("left")) return "left-bay";
  if (value.includes("equipment_door_seam") && value.includes("right")) return "right-bay";
  if (value.includes("rear") && value.includes("service") && value.includes("door")) return "rear-door";
  if (value.includes("outward_flip_table_access_lid") && value.includes("left")) return "left-lid";
  if (value.includes("outward_flip_table_access_lid") && value.includes("right")) return "right-lid";
  if (value.includes("a09_") || value.includes("table_top") || value.includes("walnut_surface")) return "table";
  if (value.includes("a08_") || value.includes("footrest")) return "footrest";
  if (value.includes("a07_") || value.includes("mast_") || value.includes("optical_crown")) return "mast";
  if (value.includes("a06_") || value.includes("backrest")) return "backrest";
  if (value.includes("drawer_tray_left") || value.includes("device_bay") && value.includes("left")) return "left-bay";
  if (value.includes("drawer_tray_right") || value.includes("device_bay") && value.includes("right")) return "right-bay";
  return null;
}

function classifyInternal(name: string): InternalFilter {
  const value = name.toLowerCase();
  if (/battery|power_distribution|pressure_vent|temperature_sensor|charge_port|backup_battery/.test(value)) return "power";
  if (/chassis|tyre|hub_|axle|suspension|rocker|drive_imu|brake/.test(value)) return "drive";
  if (/follow_|tof|scanner|ultrasonic|uwb|cliff|tactile|antenna/.test(value)) return "perception";
  return "control";
}

function copyMeshMaterial(mesh: THREE.Mesh) {
  const source = mesh.material;
  mesh.material = Array.isArray(source)
    ? source.map((material) => material.clone())
    : source.clone();
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
  materials.forEach((material) => {
    material.userData.baseOpacity = material.opacity;
    material.userData.baseTransparent = material.transparent;
    material.userData.baseDepthWrite = material.depthWrite;
  });
}

function eachMaterial(object: THREE.Object3D, callback: (material: THREE.Material) => void) {
  if (!(object instanceof THREE.Mesh)) return;
  const materials = Array.isArray(object.material) ? object.material : [object.material];
  materials.forEach(callback);
}

function setObjectOpacity(object: THREE.Object3D, opacity: number, depthWrite = opacity > 0.96) {
  object.visible = opacity > 0.006;
  object.traverse((child) => {
    eachMaterial(child, (material) => {
      const base = Number(material.userData.baseOpacity ?? 1);
      material.opacity = base * clamp01(opacity);
      material.transparent = material.opacity < 0.995 || Boolean(material.userData.baseTransparent);
      material.depthWrite = depthWrite && Boolean(material.userData.baseDepthWrite ?? true);
      material.needsUpdate = true;
    });
  });
}

function makeFeatureGroup(source: THREE.Object3D, matcher: (name: string) => boolean, name: string) {
  const group = new THREE.Group();
  group.name = name;
  source.updateMatrixWorld(true);
  source.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || !matcher(object.name)) return;
    const clone = object.clone(false) as THREE.Mesh;
    clone.geometry = object.geometry;
    clone.matrix.copy(object.matrixWorld);
    clone.matrix.decompose(clone.position, clone.quaternion, clone.scale);
    copyMeshMaterial(clone);
    if (clone.name.includes("WALNUT_SURFACE")) {
      // Blender's procedural walnut nodes are not represented in the exported GLB.
      // Restore the R14 smoked-walnut base response without inventing a glossy finish.
      eachMaterial(clone, (material) => {
        const finish = material as THREE.MeshStandardMaterial;
        finish.color?.set("#6a4330");
        if ("roughness" in finish) finish.roughness = 0.46;
        if ("metalness" in finish) finish.metalness = 0;
        if ("envMapIntensity" in finish) finish.envMapIntensity = 0.52;
        finish.needsUpdate = true;
      });
    }
    group.add(clone);
  });
  return group;
}

function vectorLerp(base: THREE.Vector3, offset: THREE.Vector3, progress: number) {
  return base.clone().addScaledVector(offset, progress);
}

export function R14Experience() {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const apiRef = useRef<ViewerApi | null>(null);
  const [productState, setProductState] = useState<ProductState>("follow");
  const [mode, setMode] = useState<ReviewMode>("object");
  const [cameraView, setCameraViewState] = useState<CameraView>("hero");
  const [internalFilter, setInternalFilter] = useState<InternalFilter>("all");
  const [section, setSection] = useState(100);
  const [selectedPart, setSelectedPart] = useState<PartId | null>(null);
  const [structureOpen, setStructureOpen] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const [loading, setLoading] = useState(0);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const stateInfo = useMemo(
    () => STATES.find((state) => state.id === productState) ?? STATES[0],
    [productState],
  );

  useEffect(() => {
    const host = mountRef.current;
    if (!host) return;

    let disposed = false;
    let animationFrame = 0;
    let hoveredMesh: THREE.Mesh | null = null;
    let activeState: ProductState = "follow";
    let activeMode: ReviewMode = "object";
    let activeFilter: InternalFilter = "all";
    let sectionValue = 100;
    let tableVariant: "none" | "cafe" | "focus" = "none";
    let leftBayOpen = false;
    let rightBayOpen = false;
    let rearDoorOpen = false;
    let userCameraControl = false;

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(host.clientWidth, host.clientHeight, false);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.16;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.localClippingEnabled = true;
    renderer.domElement.setAttribute("role", "img");
    renderer.domElement.setAttribute(
      "aria-label",
      "WorkCore E6 R14 三维交互模型，可拖动旋转、滚轮缩放并点击结构。",
    );
    renderer.domElement.tabIndex = 0;
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x090807, 0.043);

    const camera = new THREE.PerspectiveCamera(
      34,
      Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight),
      0.02,
      40,
    );
    camera.position.set(-2.35, 1.42, 2.05);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.68, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.065;
    controls.enablePan = false;
    controls.minDistance = 1.25;
    controls.maxDistance = 5.2;
    controls.minPolarAngle = 0.12;
    controls.maxPolarAngle = Math.PI * 0.485;
    controls.rotateSpeed = 0.56;
    controls.zoomSpeed = 0.75;
    controls.addEventListener("start", () => {
      userCameraControl = true;
      setInteracted(true);
    });

    const hemi = new THREE.HemisphereLight(0xdedbd5, 0x211a16, 1.42);
    scene.add(hemi);
    const key = new THREE.SpotLight(0xfff0dc, 61, 8, Math.PI * 0.2, 0.68, 1.2);
    key.position.set(-2.8, 4.2, 2.8);
    key.target.position.set(0, 0.68, 0);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.00025;
    scene.add(key, key.target);
    const rim = new THREE.SpotLight(0xd9dedb, 18, 7, Math.PI * 0.18, 0.76, 1.4);
    rim.position.set(2.4, 2.7, -2.8);
    rim.target.position.set(0.1, 0.72, 0);
    scene.add(rim, rim.target);
    const fill = new THREE.PointLight(0xc99572, 6.2, 3.6, 2);
    fill.position.set(-0.4, 0.5, 1.6);
    scene.add(fill);

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(4.2, 96),
      new THREE.MeshStandardMaterial({
        color: 0x0a0908,
        roughness: 0.8,
        metalness: 0.05,
        transparent: true,
        opacity: 0.88,
      }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.004;
    floor.receiveShadow = true;
    floor.name = "REVIEW_FLOOR";
    scene.add(floor);

    const clippingPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0.5);
    const manager = new THREE.LoadingManager();
    manager.onProgress = (_url, loaded, total) => {
      if (!disposed) setLoading(Math.round((loaded / Math.max(1, total)) * 100));
    };
    const loader = new GLTFLoader(manager);

    const motion = {
      fold: 1,
      mast: 0,
      footrest: 0,
      cafeTable: 0,
      focusTable: 0,
      shell: 1,
      internal: 0,
      explode: 0,
      leftBay: 0,
      rightBay: 0,
      rearDoor: 0,
    };
    const target = { ...motion };

    const cameraGoal = {
      active: false,
      position: camera.position.clone(),
      target: controls.target.clone(),
    };

    let rideRoot: THREE.Object3D;
    let internalRoot: THREE.Object3D;
    let foldPivot: THREE.Group;
    let mastLift: THREE.Group;
    let footrestSlide: THREE.Group;
    let closedBody: THREE.Group;
    let rideOpenBody: THREE.Object3D | undefined;
    let cafeTable: THREE.Group;
    let focusTable: THREE.Group;
    let leftLidPivot: THREE.Group | null = null;
    let rightLidPivot: THREE.Group | null = null;
    let leftDrawerGroup: THREE.Group | null = null;
    let rightDrawerGroup: THREE.Group | null = null;
    let rearServiceGroup: THREE.Group | null = null;
    let openFootrestMeshes: THREE.Object3D[] = [];
    const internalSystems = new Map<InternalFilter, THREE.Object3D[]>();
    const explodeEntries: Array<{
      object: THREE.Object3D;
      base: THREE.Vector3;
      offset: THREE.Vector3;
    }> = [];
    let lidPulse: null | {
      start: number;
      side: "left" | "right" | "both";
      applyAtPeak?: () => void;
      applied: boolean;
    } = null;
    const stateTimers = new Set<number>();
    let stateRevision = 0;

    const setHover = (mesh: THREE.Mesh | null) => {
      if (hoveredMesh === mesh) return;
      if (hoveredMesh) {
        eachMaterial(hoveredMesh, (material) => {
          if ("emissive" in material) {
            (material as THREE.MeshStandardMaterial).emissive.setHex(
              Number(material.userData.baseEmissive ?? 0),
            );
            (material as THREE.MeshStandardMaterial).emissiveIntensity = Number(
              material.userData.baseEmissiveIntensity ?? 1,
            );
          }
        });
      }
      hoveredMesh = mesh;
      if (hoveredMesh) {
        eachMaterial(hoveredMesh, (material) => {
          if ("emissive" in material) {
            const typed = material as THREE.MeshStandardMaterial;
            if (material.userData.baseEmissive === undefined) {
              material.userData.baseEmissive = typed.emissive.getHex();
              material.userData.baseEmissiveIntensity = typed.emissiveIntensity;
            }
            typed.emissive.setHex(0x4a2514);
            typed.emissiveIntensity = 0.34;
          }
        });
      }
    };

    const addExplode = (object: THREE.Object3D | null | undefined, offset: THREE.Vector3) => {
      if (!object) return;
      explodeEntries.push({ object, base: object.position.clone(), offset });
    };

    const makeLidPivot = (
      objects: Array<THREE.Object3D | undefined>,
      side: "left" | "right",
    ) => {
      const moving = objects.filter((object): object is THREE.Object3D => Boolean(object));
      if (!moving.length) return null;
      const pivot = new THREE.Group();
      pivot.name = `PIVOT_A05_${side.toUpperCase()}_LID`;
      pivot.position.set(side === "left" ? 0 : 0.02, 0.655, side === "left" ? 0.368 : -0.368);
      rideRoot.add(pivot);
      rideRoot.updateMatrixWorld(true);
      moving.forEach((object) => pivot.attach(object));
      return pivot;
    };

    const buildMoveGroup = (
      root: THREE.Object3D,
      name: string,
      matcher: (objectName: string) => boolean,
    ) => {
      const group = new THREE.Group();
      group.name = name;
      root.add(group);
      root.updateMatrixWorld(true);
      const matches: THREE.Object3D[] = [];
      root.traverse((object) => {
        if (object !== group && object instanceof THREE.Mesh && matcher(object.name)) matches.push(object);
      });
      matches.forEach((object) => group.attach(object));
      return group;
    };

    const applyFilter = () => {
      if (!internalRoot) return;
      internalSystems.forEach((objects, keyName) => {
        const alpha = activeFilter === "all" || activeFilter === keyName ? 0.96 : 0.12;
        objects.forEach((object) => {
          object.userData.filterOpacity = alpha;
        });
      });
    };

    const setCameraView = (view: CameraView) => {
      const focusScale = activeState === "focus" ? 1.13 : 1;
      const views: Record<CameraView, { position: THREE.Vector3; target: THREE.Vector3 }> = {
        hero: {
          position: new THREE.Vector3(-2.35 * focusScale, 1.42 * focusScale, 2.05 * focusScale),
          target: new THREE.Vector3(0, activeState === "focus" ? 0.84 : 0.68, 0),
        },
        front: {
          position: new THREE.Vector3(-3.05 * focusScale, 0.88 * focusScale, 0),
          target: new THREE.Vector3(0, activeState === "focus" ? 0.82 : 0.67, 0),
        },
        side: {
          position: new THREE.Vector3(0, 1.04 * focusScale, 3.05 * focusScale),
          target: new THREE.Vector3(0, activeState === "focus" ? 0.83 : 0.64, 0),
        },
        top: {
          position: new THREE.Vector3(-0.01, 3.65 * focusScale, 0.01),
          target: new THREE.Vector3(0, 0.48, 0),
        },
      };
      cameraGoal.position.copy(views[view].position);
      cameraGoal.target.copy(views[view].target);
      cameraGoal.active = true;
      userCameraControl = false;
      setCameraViewState(view);
      setInteracted(true);
    };

    const pulseLid = (
      side: "left" | "right" | "both",
      applyAtPeak?: () => void,
    ) => {
      lidPulse = { start: performance.now(), side, applyAtPeak, applied: false };
    };

    const cancelStateSequence = () => {
      stateRevision += 1;
      stateTimers.forEach((timer) => window.clearTimeout(timer));
      stateTimers.clear();
      lidPulse = null;
      if (leftLidPivot) leftLidPivot.rotation.x = 0;
      if (rightLidPivot) rightLidPivot.rotation.x = 0;
    };

    const scheduleState = (delay: number, revision: number, task: () => void) => {
      const timer = window.setTimeout(() => {
        stateTimers.delete(timer);
        if (!disposed && revision === stateRevision) task();
      }, delay);
      stateTimers.add(timer);
    };

    const setTableEndpoint = (variant: "none" | "cafe" | "focus") => {
      tableVariant = variant;
      target.cafeTable = variant === "cafe" ? 1 : 0;
      target.focusTable = variant === "focus" ? 1 : 0;
    };

    const retractServicePreviews = () => {
      leftBayOpen = false;
      rightBayOpen = false;
      rearDoorOpen = false;
      target.leftBay = 0;
      target.rightBay = 0;
      target.rearDoor = 0;
    };

    const applyProductState = (state: ProductState, immediate = false) => {
      cancelStateSequence();
      const revision = stateRevision;
      activeState = state;
      setProductState(state);
      retractServicePreviews();
      const desiredTable = state === "cafe" ? "cafe" : state === "focus" ? "focus" : "none";

      if (immediate) {
        target.fold = state === "follow" ? 1 : 0;
        target.mast = state === "focus" ? 1 : 0;
        target.footrest = state === "ride" ? 1 : 0;
        setTableEndpoint(desiredTable);
      } else {
        const hadTable =
          tableVariant !== "none" ||
          target.cafeTable > 0.04 ||
          target.focusTable > 0.04 ||
          motion.cafeTable > 0.04 ||
          motion.focusTable > 0.04;

        // Every state transition first removes work surfaces, retracts the footrest,
        // and lowers A07. Folding or redeploying happens only after that safe stage.
        target.footrest = 0;
        target.mast = 0;

        const enterPosture = () => {
          if (state === "follow") {
            scheduleState(460, revision, () => {
              target.fold = 1;
            });
            return;
          }

          target.fold = 0;
          const postureDelay = motion.fold > 0.04 ? 620 : 160;
          scheduleState(postureDelay, revision, () => {
            if (state === "ride") {
              target.footrest = 1;
              return;
            }
            if (state === "focus") target.mast = 1;
            const tableDelay = state === "focus" ? 620 : 0;
            scheduleState(tableDelay, revision, () => {
              pulseLid(state === "focus" ? "both" : "right", () => {
                setTableEndpoint(desiredTable);
              });
            });
          });
        };

        if (hadTable) {
          const stowSide = tableVariant === "focus" ? "both" : "right";
          pulseLid(stowSide, () => setTableEndpoint("none"));
          scheduleState(1420, revision, enterPosture);
        } else {
          setTableEndpoint("none");
          enterPosture();
        }
      }

      if (!userCameraControl && state === "focus") setCameraView("hero");
      setInteracted(true);
    };

    const applyMode = (nextMode: ReviewMode) => {
      activeMode = nextMode;
      setMode(nextMode);
      target.shell = nextMode === "internal" ? 0.16 : nextMode === "exploded" ? 0.2 : 1;
      target.internal = nextMode === "object" ? 0 : 1;
      target.explode = nextMode === "exploded" ? 1 : 0;
      if (nextMode === "exploded") {
        activeFilter = "all";
        setInternalFilter("all");
        applyFilter();
      }
      if (nextMode === "internal") setCameraView("hero");
      setInteracted(true);
    };

    const togglePart = (id: PartId) => {
      setSelectedPart(id);
      setInteracted(true);
      switch (id) {
        case "backrest":
          applyProductState(activeState === "follow" ? "ride" : "follow");
          break;
        case "mast":
          applyProductState(activeState === "focus" ? "cafe" : "focus");
          break;
        case "footrest":
          if (activeState === "follow") {
            applyProductState("ride");
            break;
          }
          target.footrest = target.footrest > 0.5 ? 0 : 1;
          break;
        case "table": {
          if (activeState === "follow" || activeState === "ride") {
            applyProductState("cafe");
            break;
          }
          const next: "none" | "cafe" | "focus" =
            tableVariant === "none" ? (activeState === "focus" ? "focus" : "cafe") : "none";
          pulseLid(next === "focus" ? "both" : "right", () => {
            tableVariant = next;
            target.cafeTable = next === "cafe" ? 1 : 0;
            target.focusTable = next === "focus" ? 1 : 0;
          });
          break;
        }
        case "left-lid":
          pulseLid("left");
          break;
        case "right-lid":
          pulseLid("right");
          break;
        case "left-bay":
          leftBayOpen = !leftBayOpen;
          target.leftBay = leftBayOpen ? 1 : 0;
          applyMode("internal");
          activeFilter = "control";
          setInternalFilter("control");
          applyFilter();
          break;
        case "right-bay":
          rightBayOpen = !rightBayOpen;
          target.rightBay = rightBayOpen ? 1 : 0;
          applyMode("internal");
          activeFilter = "control";
          setInternalFilter("control");
          applyFilter();
          break;
        case "rear-door":
          rearDoorOpen = !rearDoorOpen;
          target.rearDoor = rearDoorOpen ? 1 : 0;
          applyMode("internal");
          activeFilter = "power";
          setInternalFilter("power");
          applyFilter();
          break;
        case "front-sensor":
          activeFilter = "perception";
          setInternalFilter("perception");
          if (activeMode !== "object") applyFilter();
          break;
        case "joystick":
          break;
      }
    };

    const reset = () => {
      leftBayOpen = false;
      rightBayOpen = false;
      rearDoorOpen = false;
      target.leftBay = 0;
      target.rightBay = 0;
      target.rearDoor = 0;
      activeFilter = "all";
      setInternalFilter("all");
      setSelectedPart(null);
      applyMode("object");
      applyProductState("follow");
      setCameraView("hero");
    };

    apiRef.current = {
      setProductState: applyProductState,
      setMode: applyMode,
      setInternalFilter: (filter) => {
        activeFilter = filter;
        setInternalFilter(filter);
        applyFilter();
      },
      setSection: (value) => {
        sectionValue = value;
        setSection(value);
      },
      setCamera: setCameraView,
      togglePart,
      reset,
    };

    const prepare = async () => {
      const [ride, follow, cafe, focus, internal] = await Promise.all([
        loader.loadAsync("/workcore_r14_ride.glb"),
        loader.loadAsync("/workcore_r14_follow.glb"),
        loader.loadAsync("/workcore_r14_cafe.glb"),
        loader.loadAsync("/workcore_r14_focus.glb"),
        loader.loadAsync("/workcore_internal_layout.glb"),
      ]);
      if (disposed) return;

      rideRoot = ride.scene;
      rideRoot.name = "WORKCORE_R14_CANONICAL";
      rideRoot.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        copyMeshMaterial(object);
        object.castShadow = true;
        object.receiveShadow = true;
      });
      scene.add(rideRoot);

      closedBody = makeFeatureGroup(
        follow.scene,
        (name) => name.includes("MONOCOQUE"),
        "BODY_CLOSED",
      );
      rideOpenBody = rideRoot.getObjectByName("V11_R14_SHARED_SINGLE_ASYMMETRIC_MONOCOQUE");
      if (rideOpenBody) rideOpenBody.name = "BODY_RIDE_OPEN";
      cafeTable = makeFeatureGroup(
        cafe.scene,
        (name) => name.includes("A09_"),
        "FEATURE_A09_CAFE",
      );
      focusTable = makeFeatureGroup(
        focus.scene,
        (name) => name.includes("A09_"),
        "FEATURE_A09_FOCUS",
      );
      rideRoot.add(closedBody, cafeTable, focusTable);
      setObjectOpacity(closedBody, 0);
      setObjectOpacity(cafeTable, 0);
      setObjectOpacity(focusTable, 0);

      openFootrestMeshes = [];
      rideRoot.traverse((object) => {
        if (
          object instanceof THREE.Mesh &&
          object.name.includes("A08_") &&
          !object.name.includes("STOWED") &&
          !object.name.includes("CASSETTE_SEAM")
        ) {
          openFootrestMeshes.push(object);
        }
      });
      footrestSlide = new THREE.Group();
      footrestSlide.name = "SLIDE_A08_FOOTREST";
      rideRoot.add(footrestSlide);
      rideRoot.updateMatrixWorld(true);
      openFootrestMeshes.forEach((object) => footrestSlide.attach(object));

      foldPivot = new THREE.Group();
      foldPivot.name = "PIVOT_A06_A07_FOLD";
      foldPivot.position.set(0.158, 0.535, 0);
      mastLift = new THREE.Group();
      mastLift.name = "LIFT_A07";
      foldPivot.add(mastLift);
      rideRoot.add(foldPivot);
      rideRoot.updateMatrixWorld(true);
      const foldables: THREE.Object3D[] = [];
      const mastParts: THREE.Object3D[] = [];
      rideRoot.traverse((object) => {
        if (object.name.includes("_RIDE_A06_")) foldables.push(object);
        if (object.name.includes("_RIDE_A07_")) mastParts.push(object);
      });
      foldables.forEach((object) => foldPivot.attach(object));
      mastParts.forEach((object) => mastLift.attach(object));

      leftLidPivot = makeLidPivot(
        [
          rideRoot.getObjectByName("V11_R14_A05_LEFT_OUTWARD_FLIP_TABLE_ACCESS_LID"),
          rideRoot.getObjectByName("V11_R14_A05_LEFT_QI_FLUSH_USABLE_FIELD_176X86"),
          rideRoot.getObjectByName("V11_R14_A05_LEFT_QI_TARGET_RING"),
        ],
        "left",
      );
      rightLidPivot = makeLidPivot(
        [rideRoot.getObjectByName("V11_R14_A05_RIGHT_OUTWARD_FLIP_TABLE_ACCESS_LID")],
        "right",
      );

      internalRoot = internal.scene;
      internalRoot.name = "WORKCORE_INTERNAL_LAYOUT";
      internalRoot.scale.setScalar(0.001);
      // The DFR3 reference GLB stores engineering coordinates as X/Y/Z-up.
      // Rotate once into the Blender-exported R14 world convention (Y-up in Three.js).
      internalRoot.rotation.x = -Math.PI / 2;
      internalRoot.visible = false;
      internalRoot.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        if (/^hmi_|follow_hidden_backrest_antenna/i.test(object.name)) {
          object.userData.excludeFromReview = true;
          object.visible = false;
          return;
        }
        copyMeshMaterial(object);
        object.castShadow = true;
        object.receiveShadow = true;
        const category = classifyInternal(object.name);
        const list = internalSystems.get(category) ?? [];
        list.push(object);
        internalSystems.set(category, list);
        object.userData.filterOpacity = 0.96;
      });
      scene.add(internalRoot);

      leftDrawerGroup = buildMoveGroup(
        internalRoot,
        "SLIDE_A04_LEFT_DEVICE_BAY",
        (name) => /^(drawer_tray_left_upper|device_bay_shock_liner_left|universal_flat_device_keepout_left|cots_latch_left_upper|cots_slide_left_upper_b)$/.test(name.toLowerCase()),
      );
      rightDrawerGroup = buildMoveGroup(
        internalRoot,
        "SLIDE_A04_RIGHT_DEVICE_BAY",
        (name) => /^(drawer_tray_right_upper|device_bay_shock_liner_right|laptop_16in_keepout_right|cots_latch_right_upper|cots_slide_right_upper_b)$/.test(name.toLowerCase()),
      );
      rearServiceGroup = buildMoveGroup(
        internalRoot,
        "OPEN_A10_REAR_SERVICE",
        (name) => name.toLowerCase() === "service_rear_flush_door",
      );

      addExplode(foldPivot, new THREE.Vector3(0.12, 0.3, 0));
      addExplode(rideRoot.getObjectByName("V11_R14_SHARED_FIXED_LOW_ARM_LEFT"), new THREE.Vector3(0, 0.05, 0.28));
      addExplode(rideRoot.getObjectByName("V11_R14_SHARED_FIXED_LOW_ARM_RIGHT"), new THREE.Vector3(0, 0.05, -0.28));
      addExplode(rideRoot.getObjectByName("V11_R14_SHARED_TAPERED_NATURAL_LEATHER_SEAT"), new THREE.Vector3(0, 0.24, 0));
      addExplode(footrestSlide, new THREE.Vector3(-0.24, 0, 0));
      addExplode(cafeTable, new THREE.Vector3(0, 0.14, -0.2));
      addExplode(focusTable, new THREE.Vector3(0, 0.16, 0));
      rideRoot.traverse((object) => {
        if (!object.name.toLowerCase().includes("source_tyre")) return;
        const left = object.name.toLowerCase().includes("left");
        addExplode(object, new THREE.Vector3(0, 0, left ? 0.22 : -0.22));
      });

      addExplode(leftDrawerGroup, new THREE.Vector3(0, 0.08, 0.2));
      addExplode(rightDrawerGroup, new THREE.Vector3(0, 0.08, -0.2));
      addExplode(rearServiceGroup, new THREE.Vector3(0.22, 0.05, 0));

      applyFilter();
      applyProductState("follow", true);
      applyMode("object");
      setCameraView("hero");
      setLoading(100);
      window.setTimeout(() => {
        if (!disposed) setReady(true);
      }, 120);
    };

    prepare().catch((reason: unknown) => {
      console.error(reason);
      if (!disposed) setError("R14 模型载入失败。请通过本地页面服务打开，而不是直接双击 HTML 文件。");
    });

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let pointerDown: { x: number; y: number } | null = null;

    const pick = (event: PointerEvent) => {
      if (!rideRoot) return null;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const roots = [rideRoot];
      if (internalRoot?.visible) roots.push(internalRoot);
      const hits = raycaster.intersectObjects(roots, true);
      for (const hit of hits) {
        let object: THREE.Object3D | null = hit.object;
        while (object && !resolvePart(object.name)) object = object.parent;
        const part = object ? resolvePart(object.name) : null;
        if (part) return { part, mesh: hit.object as THREE.Mesh };
      }
      return null;
    };

    const onPointerDown = (event: PointerEvent) => {
      pointerDown = { x: event.clientX, y: event.clientY };
    };
    const onPointerMove = (event: PointerEvent) => {
      const result = pick(event);
      setHover(result?.mesh ?? null);
      renderer.domElement.style.cursor = result ? "pointer" : "grab";
    };
    const onPointerUp = (event: PointerEvent) => {
      if (!pointerDown) return;
      const distance = Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y);
      pointerDown = null;
      if (distance > 6) return;
      const result = pick(event);
      if (result) togglePart(result.part);
      else setSelectedPart(null);
    };
    const onPointerLeave = () => setHover(null);
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerup", onPointerUp);
    renderer.domElement.addEventListener("pointerleave", onPointerLeave);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement) return;
      const stateByKey: Record<string, ProductState> = {
        "1": "follow",
        "2": "ride",
        "3": "cafe",
        "4": "focus",
      };
      if (stateByKey[event.key]) applyProductState(stateByKey[event.key]);
      if (event.key.toLowerCase() === "e") applyMode("object");
      if (event.key.toLowerCase() === "i") applyMode("internal");
      if (event.key.toLowerCase() === "x") applyMode("exploded");
      if (event.key === "Escape") {
        setSelectedPart(null);
        setStructureOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);

    const resizeObserver = new ResizeObserver(() => {
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    });
    resizeObserver.observe(host);

    const clock = new THREE.Clock();
    const damp = (current: number, next: number, lambda: number, delta: number) =>
      THREE.MathUtils.lerp(current, next, 1 - Math.exp(-lambda * delta));

    const animate = () => {
      if (disposed) return;
      animationFrame = requestAnimationFrame(animate);
      const delta = Math.min(clock.getDelta(), 0.05);
      const now = performance.now();

      (Object.keys(motion) as Array<keyof typeof motion>).forEach((keyName) => {
        motion[keyName] = damp(motion[keyName], target[keyName], keyName === "explode" ? 4.8 : 7.2, delta);
      });

      if (foldPivot) foldPivot.rotation.z = motion.fold * Math.PI * 0.5;
      if (mastLift) mastLift.position.y = motion.mast * 0.42;

      if (rideRoot) {
        setObjectOpacity(rideRoot, motion.shell, motion.shell > 0.94);
        const usesRideOpening = motion.footrest > 0.025;
        if (rideOpenBody) setObjectOpacity(rideOpenBody, usesRideOpening ? motion.shell : 0);
        setObjectOpacity(closedBody, usesRideOpening ? 0 : motion.shell);
        if (footrestSlide) footrestSlide.position.x = (1 - motion.footrest) * 0.22;
        setObjectOpacity(cafeTable, motion.shell * motion.cafeTable);
        setObjectOpacity(focusTable, motion.shell * motion.focusTable);

        rideRoot.traverse((object) => {
          if (!(object instanceof THREE.Mesh)) return;
          const isShell =
            /BODY_|MONOCOQUE|FIXED_LOW_ARM|ICONIC_FRONT_TRAPEZOID|LEATHER_SEAT/.test(object.name);
          eachMaterial(object, (material) => {
            material.clippingPlanes =
              activeMode === "internal" && sectionValue < 98 && isShell ? [clippingPlane] : [];
          });
        });
        clippingPlane.constant = THREE.MathUtils.lerp(-0.44, 0.5, sectionValue / 100);
      }

      if (internalRoot) {
        internalRoot.visible = motion.internal > 0.01;
        internalRoot.traverse((object) => {
          if (!(object instanceof THREE.Mesh)) return;
          if (object.userData.excludeFromReview) {
            object.visible = false;
            return;
          }
          const filterOpacity = Number(object.userData.filterOpacity ?? 0.96);
          setObjectOpacity(object, motion.internal * filterOpacity, motion.internal > 0.96);
        });
      }

      if (leftDrawerGroup) leftDrawerGroup.position.y = motion.leftBay * -300;
      if (rightDrawerGroup) rightDrawerGroup.position.y = motion.rightBay * 300;
      if (rearServiceGroup) rearServiceGroup.position.x = motion.rearDoor * 260;

      if (lidPulse) {
        const progress = clamp01((now - lidPulse.start) / 1300);
        const angle = Math.sin(progress * Math.PI) * THREE.MathUtils.degToRad(105);
        if (leftLidPivot) leftLidPivot.rotation.x = lidPulse.side !== "right" ? angle : 0;
        if (rightLidPivot) rightLidPivot.rotation.x = lidPulse.side !== "left" ? -angle : 0;
        if (progress >= 0.48 && !lidPulse.applied) {
          lidPulse.applied = true;
          lidPulse.applyAtPeak?.();
        }
        if (progress >= 1) {
          if (leftLidPivot) leftLidPivot.rotation.x = 0;
          if (rightLidPivot) rightLidPivot.rotation.x = 0;
          lidPulse = null;
        }
      }

      explodeEntries.forEach(({ object, base, offset }) => {
        if (object === foldPivot) {
          object.position.copy(vectorLerp(base, offset, motion.explode));
          return;
        }
        if (object === footrestSlide) {
          object.position
            .set((1 - motion.footrest) * 0.22, 0, 0)
            .addScaledVector(offset, motion.explode);
          return;
        }
        if (object === leftDrawerGroup || object === rightDrawerGroup || object === rearServiceGroup) return;
        object.position.copy(vectorLerp(base, offset, motion.explode));
      });

      if (cameraGoal.active) {
        camera.position.lerp(cameraGoal.position, 1 - Math.exp(-4.8 * delta));
        controls.target.lerp(cameraGoal.target, 1 - Math.exp(-5.4 * delta));
        if (
          camera.position.distanceTo(cameraGoal.position) < 0.008 &&
          controls.target.distanceTo(cameraGoal.target) < 0.005
        ) {
          cameraGoal.active = false;
        }
      }

      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      apiRef.current = null;
      cancelAnimationFrame(animationFrame);
      stateTimers.forEach((timer) => window.clearTimeout(timer));
      stateTimers.clear();
      resizeObserver.disconnect();
      window.removeEventListener("keydown", onKeyDown);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  const chooseState = (state: ProductState) => apiRef.current?.setProductState(state);
  const chooseMode = (nextMode: ReviewMode) => apiRef.current?.setMode(nextMode);
  const chooseFilter = (filter: InternalFilter) => apiRef.current?.setInternalFilter(filter);
  const choosePart = (part: PartId) => {
    setSelectedPart(part);
    setStructureOpen(false);
    apiRef.current?.togglePart(part);
  };

  return (
    <main className="review-shell">
      <div ref={mountRef} className="stage" />

      <header className="top-plate" aria-label="产品版本">
        <p className="eyebrow">WORKCORE E6</p>
        <p className="plate-sub">R14 · INTERACTIVE DESIGN REVIEW</p>
        <p className="scope-line">BLENDER VISUAL COMPOSITE · NO STEP / MOTION / PRODUCTION CLAIM</p>
      </header>

      <nav className="view-axis" aria-label="检视模式">
        {(
          [
            ["object", "Object"],
            ["internal", "Internal"],
            ["exploded", "Exploded"],
          ] as Array<[ReviewMode, string]>
        ).map(([id, label]) => (
          <button
            key={id}
            className={`axis-button ${mode === id ? "is-active" : ""}`}
            type="button"
            aria-pressed={mode === id}
            onClick={() => chooseMode(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {mode === "internal" && (
        <>
          <div className="context-axis" aria-label="内部系统筛选">
            {INTERNAL_FILTERS.map((filter) => (
              <button
                key={filter.id}
                className={`context-button ${internalFilter === filter.id ? "is-active" : ""}`}
                type="button"
                aria-pressed={internalFilter === filter.id}
                onClick={() => chooseFilter(filter.id)}
              >
                {filter.label}
              </button>
            ))}
            <span
              className="baseline-note"
            >
              DFR3 historical · not production
            </span>
            <label className="section-control">
              <span className="micro-label">Section</span>
              <input
                className="section-range"
                type="range"
                min="0"
                max="100"
                value={section}
                aria-label="外壳剖切位置"
                onChange={(event) => apiRef.current?.setSection(Number(event.target.value))}
              />
            </label>
          </div>
        </>
      )}

      {mode !== "object" && (
        <div className="provenance-note" role="note">
          <span>INTERNAL · E6-DFR3 HISTORICAL PACKAGING SUBSET · NOT CURRENT R14</span>
          <span>OMITTED / NOT MODELLED · SAFETY CASSETTE · FIREWALL · STO · BRAKES · MOTOR CONTROLLERS</span>
        </div>
      )}

      <div className={`current-state-caption ${selectedPart ? "has-selection" : ""}`} aria-live="polite">
        <p className="current-state-name">{stateInfo.label}</p>
        <p className="state-sub">{stateInfo.caption}</p>
      </div>

      <button
        className={`structure-launch ${structureOpen ? "is-active" : ""}`}
        type="button"
        aria-expanded={structureOpen}
        aria-controls="structure-panel"
        onClick={() => setStructureOpen((open) => !open)}
      >
        Review items
      </button>

      <aside
        id="structure-panel"
        className={`structure-panel ${structureOpen ? "is-open" : ""}`}
        aria-label="可交互结构"
      >
        <div className="structure-panel-head">
          <span>Inspectable items</span>
          <span>R14</span>
        </div>
        {STRUCTURE_ORDER.map((partId) => {
          const part = PARTS[partId];
          return (
            <button
              key={part.id}
              className={`structure-row ${selectedPart === part.id ? "is-active" : ""}`}
              type="button"
              onClick={() => choosePart(part.id)}
            >
              <span className="structure-code">{part.code}</span>
              <span className="structure-name">{part.short}</span>
              <span className="structure-meta">
                {part.action ? (part.verified ? "ENDPOINT" : "PREVIEW") : "INSPECT"}
              </span>
            </button>
          );
        })}
      </aside>

      {selectedPart && (
        <aside className="specimen-card" aria-live="polite">
          <button
            className="card-dismiss"
            type="button"
            aria-label="关闭部件说明"
            onClick={() => setSelectedPart(null)}
          >
            ×
          </button>
          <p className="specimen-kicker">{PARTS[selectedPart].code} · COMPONENT</p>
          <h2 className="specimen-title">{PARTS[selectedPart].title}</h2>
          <p className="specimen-copy">{PARTS[selectedPart].copy}</p>
          <span
            className={`specimen-status ${PARTS[selectedPart].verified ? "is-verified" : ""}`}
          >
            {PARTS[selectedPart].status}
          </span>
          {PARTS[selectedPart].action && (
            <div className="card-actions">
              <button
                className="card-action"
                type="button"
                onClick={() => apiRef.current?.togglePart(selectedPart)}
              >
                {PARTS[selectedPart].action}
              </button>
            </div>
          )}
        </aside>
      )}

      <div className="camera-axis" aria-label="相机视角">
        <span className="micro-label">View</span>
        {CAMERA_VIEWS.map((view) => (
          <button
            key={view.id}
            className={`camera-button ${cameraView === view.id ? "is-active" : ""}`}
            type="button"
            aria-pressed={cameraView === view.id}
            onClick={() => apiRef.current?.setCamera(view.id)}
          >
            {view.label}
          </button>
        ))}
        <button className="camera-button" type="button" onClick={() => apiRef.current?.reset()}>
          Reset
        </button>
      </div>

      <p className={`gesture-note ${interacted ? "is-hidden" : ""}`}>
        DRAG / ORBIT
        <br />
        SCROLL / DOLLY
        <br />
        CLICK / PREVIEW
      </p>

      <nav className="state-axis" aria-label="产品状态">
        {STATES.map((state) => (
          <button
            key={state.id}
            className={`state-button ${productState === state.id ? "is-active" : ""}`}
            type="button"
            aria-pressed={productState === state.id}
            onClick={() => chooseState(state.id)}
          >
            <span className="state-name">
              <span className="state-index">{state.index}</span>
              {state.label}
            </span>
          </button>
        ))}
      </nav>

      <div className={`loading-plate ${ready ? "is-complete" : ""}`} aria-hidden={ready}>
        <span className="loading-aperture" />
        <span className="loading-copy">Loading review assets</span>
        <span className="loading-percent">{String(loading).padStart(2, "0")}%</span>
      </div>

      {error && <div className="error-plate">{error}</div>}
    </main>
  );
}
