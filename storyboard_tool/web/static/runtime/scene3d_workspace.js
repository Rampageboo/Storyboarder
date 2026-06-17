//#region src/scene3d/workspace/workspacePrimitives.ts
var e = new Set([
	"cube",
	"sphere",
	"plane",
	"cylinder",
	"cone"
]);
function t() {
	let e = globalThis.crypto;
	return e && typeof e.randomUUID == "function" ? e.randomUUID().replace(/-/g, "").slice(0, 12) : `obj_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}
function n(e, t = [
	0,
	0,
	0
]) {
	return Array.isArray(e) && e.length >= 3 ? [
		Number(e[0]) || 0,
		Number(e[1]) || 0,
		Number(e[2]) || 0
	] : [...t];
}
function r(e) {
	return n(e);
}
function i(e, t, n = 8421504) {
	return typeof t == "string" && t.startsWith("#") ? new e.Color(t).getHex() : n;
}
function a() {
	return {
		source: "builtin",
		objects: [{
			id: "ground",
			name: "Ground",
			type: "plane",
			position: [
				0,
				0,
				0
			],
			rotation: [
				-Math.PI / 2,
				0,
				0
			],
			scale: [
				10,
				10,
				1
			],
			color: "#3a4048"
		}, {
			id: "cube1",
			name: "Cube",
			type: "cube",
			position: [
				0,
				.5,
				0
			],
			rotation: [
				0,
				0,
				0
			],
			scale: [
				1,
				1,
				1
			],
			color: "#3d8bfd"
		}]
	};
}
function o(e, n, r) {
	let i = `${{
		cube: "Cube",
		sphere: "Sphere",
		plane: "Plane",
		cylinder: "Cylinder",
		cone: "Cone"
	}[e] || "Object"} ${n + 1}`;
	return {
		id: t(),
		name: i,
		type: e,
		position: [
			0,
			e === "plane" ? 0 : .5,
			0
		],
		rotation: e === "plane" ? [
			-Math.PI / 2,
			0,
			0
		] : [
			0,
			0,
			0
		],
		scale: e === "plane" ? [
			4,
			4,
			1
		] : [
			1,
			1,
			1
		],
		color: r
	};
}
function s(e, t) {
	let a = new e.MeshStandardMaterial({
		color: i(e, t.color),
		roughness: .55,
		metalness: .05
	}), o;
	switch (t.type) {
		case "sphere":
			o = new e.SphereGeometry(.5, 32, 24);
			break;
		case "plane":
			o = new e.PlaneGeometry(1, 1);
			break;
		case "cylinder":
			o = new e.CylinderGeometry(.5, .5, 1, 32);
			break;
		case "cone":
			o = new e.ConeGeometry(.5, 1, 32);
			break;
		default:
			o = new e.BoxGeometry(1, 1, 1);
			break;
	}
	let s = new e.Mesh(o, a);
	s.castShadow = t.type !== "plane", s.receiveShadow = t.type === "plane", s.userData.objectId = t.id, s.userData.objectName = t.name || t.type, s.userData.objectType = t.type;
	let [c, l, u] = n(t.position, [
		0,
		.5,
		0
	]), [d, f, p] = r(t.rotation), [m, h, g] = n(t.scale, [
		1,
		1,
		1
	]);
	return s.position.set(c, l, u), s.rotation.set(d, f, p), s.scale.set(m, h, g), s;
}
//#endregion
//#region src/scene3d/workspace/workspaceCapture.ts
function c(e, t, n, r, i = {}) {
	let a = new e.Vector2();
	t.getSize(a);
	let o = t.getPixelRatio(), s = n.aspect, c = i.getProjectCanvasSize?.() ?? {
		width: 1920,
		height: 1080
	}, l = Math.max(1, Math.floor(i.width ?? c.width)), u = Math.max(1, Math.floor(i.height ?? c.height));
	i.prepareExport?.(), t.setPixelRatio(1), t.setSize(l, u, !1), n.aspect = l / u, n.updateProjectionMatrix(), i.prepareExport?.(), t.render(r, n);
	let d = t.domElement.toDataURL("image/png");
	return t.setPixelRatio(o), t.setSize(a.x, a.y, !1), n.aspect = s, n.updateProjectionMatrix(), i.finishDisplay?.(), d;
}
//#endregion
//#region src/scene3d/workspace/workspaceCamera.ts
function l(e, t = 36) {
	return t / (2 * Math.tan(e * Math.PI / 360));
}
function u() {
	let e = globalThis.getProjectCanvasSize;
	if (typeof e == "function") {
		let t = e();
		return {
			width: Math.max(1, Math.floor(Number(t.width) || 1920)),
			height: Math.max(1, Math.floor(Number(t.height) || 1080))
		};
	}
	return {
		width: 1920,
		height: 1080
	};
}
function d() {
	let e = u();
	return e.width / Math.max(1, e.height);
}
function f(e, t) {
	let n = t.target.clone();
	return {
		position: e.position.toArray(),
		target: n.toArray(),
		rotation: e.rotation.toArray().slice(0, 3),
		fov: e.fov,
		focal_length: Math.round(l(Number(e.fov) || 50))
	};
}
function p(e, t) {
	let n = f(t.camera, t.orbit), r = t.camera.getWorldDirection(new e.Vector3()), i = Math.max(.001, t.camera.position.distanceTo(t.orbit.target)) || 1, a = t.camera.position.clone().add(r.multiplyScalar(i)), o = !!(t.followCamera && t.activeCamera);
	return {
		mode: o ? "scene_camera" : "free_view",
		camera_name: o && t.activeCamera?.name || "",
		time: Number(t.animationTime) || 0,
		position: n.position,
		target: a.toArray(),
		rotation: n.rotation,
		fov: n.fov,
		source: "workspace"
	};
}
function m(e, t, n, r, i = [
	6,
	4,
	8
], a = [
	0,
	.5,
	0
]) {
	if (!r?.position) return !1;
	let o = g(r.position, i);
	if (t.position.set(o[0], o[1], o[2]), r.target) {
		let e = g(r.target, a);
		n.target.set(e[0], e[1], e[2]);
	} else if (r.rotation) {
		let [i, a, o] = g(r.rotation);
		t.rotation.set(i, a, o), n.target.copy(t.position.clone().add(t.getWorldDirection(new e.Vector3())));
	}
	return r.fov && (t.fov = Number(r.fov) || 50, t.updateProjectionMatrix()), n.update(), !0;
}
function h(e, t, n, r) {
	if (!n?.object3d) return !1;
	let i = n.viewNode || n.object3d;
	i.updateWorldMatrix(!0, !1), i.matrixWorld.decompose(r.position, r.quaternion, r.scale), e.position.copy(r.position), e.quaternion.copy(r.quaternion);
	let a = n.object3d.isCamera ? n.object3d : null;
	return a?.isPerspectiveCamera && (e.fov = a.fov, e.near = Math.max(.001, a.near), e.far = Math.max(e.near + 1, a.far), e.updateProjectionMatrix()), t.enabled = !1, !0;
}
function g(e, t = [
	0,
	0,
	0
]) {
	return Array.isArray(e) && e.length >= 3 ? [
		Number(e[0]) || 0,
		Number(e[1]) || 0,
		Number(e[2]) || 0
	] : [...t];
}
//#endregion
//#region src/scene3d/workspace/workspaceScene.ts
var _ = 1711393, v = [
	6,
	4,
	8
], y = [
	0,
	.5,
	0
];
function ee(e, t, n = {}) {
	let r = new e.WebGLRenderer({
		antialias: !0,
		alpha: !1,
		preserveDrawingBuffer: !0
	}), i = n.maxPixelRatio ?? 2;
	return r.setPixelRatio(Math.min(window.devicePixelRatio, i)), r.outputColorSpace = e.SRGBColorSpace, r.toneMapping = e.AgXToneMapping ?? e.ACESFilmicToneMapping, r.toneMappingExposure = 1, r.shadowMap.enabled = !0, r.shadowMap.type = e.PCFSoftShadowMap, t.appendChild(r.domElement), r;
}
function b(e) {
	let t = new e.Scene();
	t.background = new e.Color(_);
	let n = new e.PerspectiveCamera(50, 1, .01, 1e3);
	n.position.set(...v);
	let r = new e.AmbientLight(16777215, .45);
	t.add(r);
	let i = new e.DirectionalLight(16777215, 1.1);
	i.position.set(6, 10, 4), t.add(i);
	let a = new e.AmbientLight(16777215, .1);
	a.visible = !1, t.add(a);
	let o = new e.HemisphereLight(14214383, 4210760, .28);
	o.visible = !1, t.add(o);
	let s = new e.GridHelper(20, 20, 4870490, 3817544);
	t.add(s);
	let c = new e.AxesHelper(2);
	return t.add(c), {
		scene: t,
		camera: n,
		defaultAmbient: r,
		defaultSun: i,
		programAmbient: a,
		programHemisphere: o,
		grid: s,
		axes: c,
		builtinBackground: new e.Color(_),
		pmremGenerator: null
	};
}
function x(e, t) {
	let n = new e.PMREMGenerator(t);
	return n.compileEquirectangularShader(), n;
}
//#endregion
//#region src/scene3d/workspace/workspaceControls.ts
function te(e, t, n, r = {}) {
	let i = new e(t, n);
	i.enableDamping = !0;
	let [a, o, s] = r.target ?? y;
	return i.target.set(a, o, s), r.onChange && i.addEventListener("change", r.onChange), i;
}
function S(e, t, n, r, i = {}) {
	let a = new e(t, n);
	return a.setMode(i.mode ?? "translate"), a.addEventListener("dragging-changed", (e) => {
		i.onDraggingChanged?.(!!e.value);
	}), a.addEventListener("objectChange", () => {
		i.onObjectChange?.();
	}), r.add(a), a;
}
//#endregion
//#region src/scene3d/workspace/workspaceBridge.ts
function C(e, t, n, r) {
	let i = ee(e, r.mountEl), a = b(e), o = x(e, i), s = te(t, a.camera, i.domElement, { onChange: r.onOrbitChange }), c = S(n, a.camera, i.domElement, a.scene, {
		mode: r.transformMode ?? "translate",
		onDraggingChanged: r.onTransformDraggingChanged,
		onObjectChange: r.onTransformObjectChange
	});
	return {
		...a,
		renderer: i,
		pmremGenerator: o,
		orbit: s,
		transform: c
	};
}
//#endregion
//#region src/scene3d/workspace/workspaceState.ts
function w(e) {
	let t = Math.max(0, Number(e) || 0), n = Math.floor(t / 60), r = (t % 60).toFixed(1).padStart(n > 0 ? 4 : 1, "0");
	return n > 0 ? `${n}:${r}` : `${r}s`;
}
function T(e, t) {
	return {
		id: e,
		name: String(t.userData?.objectName || t.userData?.objectType || e),
		type: String(t.userData?.objectType || "cube"),
		position: t.position.toArray(),
		rotation: t.rotation.toArray().slice(0, 3),
		scale: t.scale.toArray(),
		color: `#${t.material.color.getHexString()}`
	};
}
function E(e) {
	let t = [];
	for (let [n, r] of e) t.push(T(n, r));
	return t;
}
function D(e, t, n) {
	return {
		source: "builtin",
		objects: E(e),
		wireframe_mode: t,
		object_color_preview: n
	};
}
function ne(e) {
	return {
		...e.sceneMeta,
		source: "blender",
		camera_name: e.activeCameraName,
		follow_camera: e.followCamera,
		animation_time: e.animationTime,
		program_lighting: e.programLightingMode,
		imported_light_count: e.importedLightCount,
		object_color_preview: e.objectColorPreview,
		wireframe_mode: e.wireframeMode
	};
}
function O(e) {
	return e && typeof e == "object" ? { ...e } : {};
}
//#endregion
//#region src/scene3d/dispose.ts
function k(e) {
	if (!e || typeof e != "object") return;
	let t = e;
	try {
		t.dispose?.();
	} catch {}
}
function A(e) {
	let t = Array.isArray(e) ? e : [e];
	for (let e of t) {
		if (!e || typeof e != "object") continue;
		let t = e;
		for (let e of Object.keys(t)) k(t[e]);
		try {
			t.dispose?.();
		} catch {}
	}
}
function j(e) {
	try {
		e?.dispose?.();
	} catch {}
}
function M(e) {
	try {
		j(e.geometry), A(e.material);
	} catch {}
}
//#endregion
//#region src/scene3d/workspace/workspaceDispose.ts
function N(e) {
	e?.traverse?.((e) => {
		let t = e.userData?.scene3dOriginalMaterial;
		if (t) {
			A(t);
			return;
		}
		M(e);
	});
}
function P(e) {
	e && (j(e.geometry), A(e.material));
}
//#endregion
//#region src/scene3d/workspace/workspaceGlb.ts
function F(e) {
	let t = 0;
	return e?.traverse?.((e) => {
		e.isLight && (t += 1);
	}), t;
}
function I(e) {
	e?.traverse?.((e) => {
		!e.isLight || typeof e.intensity != "number" || (e.isDirectionalLight ? e.intensity = Math.min(e.intensity * Math.PI * .35, 4) : (e.isPointLight || e.isSpotLight) && e.intensity > 0 && e.intensity < 800 && (e.intensity = Math.min(e.intensity * 1.5, 600)));
	});
}
function L(e, t) {
	let n = t;
	for (; n;) {
		if (n === e) return !0;
		n = n.parent ?? null;
	}
	return !1;
}
function R(e) {
	let t = [], n = /* @__PURE__ */ new Set(), r = e.scene, i = (e, r = {}) => {
		if (!e?.isCamera || n.has(e.uuid)) return;
		n.add(e.uuid);
		let i = String(e.name || e.userData?.name || "").trim() || `Camera ${t.length + 1}`;
		t.push({
			id: e.uuid,
			name: i,
			object3d: e,
			...r
		});
	}, a = e.scenes?.length ? e.scenes : [r];
	for (let e of a) e?.traverse?.((e) => i(e, { source: "scene" }));
	if (e.parser?.associations) for (let [t] of e.parser.associations.entries()) i(t, { source: "parser" });
	for (let t of e.cameras || []) i(t, { source: "gltf.cameras" });
	for (let e of t) L(r, e.object3d) || (r.add(e.object3d), e.orphan = !0);
	return t.sort((e, t) => e.name.localeCompare(t.name, void 0, { numeric: !0 }));
}
function z(e) {
	let t = ((e.parser?.json || {}).nodes || []).filter((e) => e.camera !== void 0).length, n = e.cameras?.length || 0;
	return n > 0 || t > 0 ? `GLB 元数据含 ${Math.max(n, t)} 个相机，但未能正确挂到场景。 请检查 Blender：相机不要隐藏（眼睛图标），Limit to 不要勾选 Visible/Active Collection，或把相机放进导出集合。` : "GLB 内完全没有相机数据（不是勾选 Cameras 就行）。 请确认场景里有 Camera 对象、导出时 Limit to 留空、相机可见，并重新导出。";
}
function B(e, t) {
	let n = 0, r = e.object3d;
	for (; r;) r.name && t.has(r.name) && (n += 10), r = r.parent ?? null;
	return n;
}
function V(e, t, n = "") {
	if (!e.length) return "";
	if (n) {
		let t = e.find((e) => e.name === n);
		if (t) return t.id;
	}
	let r = e[0], i = B(r, t);
	for (let n of e.slice(1)) {
		let e = B(n, t);
		e > i && (r = n, i = e);
	}
	return r.id;
}
function H(e, t, n, r) {
	let i = new e.Box3().setFromObject(t);
	if (i.isEmpty?.()) return;
	let a = i.getSize(new e.Vector3()), o = i.getCenter(new e.Vector3()), s = Math.max(a.x, a.y, a.z) * .6 || 4;
	r.target.copy(o), n.position.copy(o.clone().add(new e.Vector3(s, s * .7, s))), n.near = Math.max(.01, s / 100), n.far = Math.max(100, s * 40), n.updateProjectionMatrix(), r.update();
}
function U(e, t) {
	if (!e || t.animationDuration <= 0) return !1;
	let n = t.animationTime;
	t.setMixerTime(0), e.getWorldPosition(t.probeA);
	let r = Math.min(Math.max(t.animationDuration * .25, .1), t.animationDuration);
	return t.setMixerTime(r), e.getWorldPosition(t.probeB), t.setMixerTime(n), t.probeA.distanceToSquared(t.probeB) > 1e-10;
}
function W(e, t, n, r) {
	if (U(e.object3d, r)) return e.object3d;
	let i = e.object3d.parent ?? null;
	for (; i && i !== t;) {
		if (i.name && n.has(i.name) && U(i, r)) return e.object3d;
		i = i.parent ?? null;
	}
	return e.object3d;
}
function G(e, t) {
	e?.traverse?.((e) => {
		e.isLight && (e.visible = t);
	});
}
function K(e, t) {
	e?.traverse?.((e) => {
		if (!e.isMesh) return;
		let n = Array.isArray(e.material) ? e.material : [e.material];
		for (let e of n) e?.isMeshStandardMaterial && (e.envMapIntensity = t, e.needsUpdate = !0);
	});
}
//#endregion
//#region src/scene3d/workspace/workspaceLighting.ts
function q(e) {
	return e === "on" || e === "off" ? e : "auto";
}
function J(e) {
	return !(e.workspaceMode !== "blender" || e.mode === "off");
}
function Y(e) {
	return e.workspaceMode !== "blender" || e.mode === "off" ? !1 : (e.mode, e.importedLightCount === 0);
}
function X(e) {
	return e.workspaceMode !== "blender" || e.mode === "off" || e.objectColorPreview ? !1 : (e.mode, e.importedLightCount > 0);
}
function Z(e) {
	return J(e) ? e.importedLightCount > 0 ? .35 : 1 : 0;
}
function re(e) {
	return e.mode === "on" ? "手动：环境 + 柔光" : e.mode === "off" ? "手动：仅 GLB 灯光" : e.importedLightCount > 0 ? `自动：GLB ${e.importedLightCount} 盏灯 + 弱环境反射` : "自动：GLB 无灯，全程序补光";
}
function Q(e) {
	switch (e) {
		case "on": return "始终开启";
		case "off": return "关闭";
		default: return "自动";
	}
}
function ie(e) {
	let t = e.importedLightCount > 0 ? `GLB 已导出 ${e.importedLightCount} 盏灯` : "GLB 未导出灯光（导出时请勾选 Punctual Lights）", n = J(e) && !e.objectColorPreview ? "环境反射：开" : "环境反射：关", r = Y(e) ? "柔光补光：开" : X(e) ? "柔光补光：弱" : "柔光补光：关", i = e.objectColorPreview ? "对象色：开（不受灯光影响）" : "对象色：关";
	return `${t} · ${Q(e.mode)} · ${n} · ${r} · ${i}`;
}
function ae(e, t, n) {
	if (t.workspaceMode !== "blender") return;
	let r = J(t) && !t.objectColorPreview, i = Y(t), a = X(t);
	r ? (n.scene.environment = n.ensureBlenderEnvMap(), n.scene.background = new e.Color(3158064)) : t.objectColorPreview ? (n.scene.environment = null, n.scene.background = new e.Color(3815994)) : (n.scene.environment = null, n.scene.background = n.builtinBackground.clone()), n.programAmbient.intensity = i ? .1 : .22, n.programAmbient.visible = i || a, n.programHemisphere.visible = i, n.setImportedLightsVisible(!t.objectColorPreview);
}
function oe(e, t) {
	let n = new e(), r = t.fromScene(n, .04).texture;
	return n.dispose?.(), r;
}
//#endregion
//#region src/scene3d/workspace/workspaceAnimation.ts
function $(e) {
	let t = String(e || "").lastIndexOf(".");
	return t > 0 ? e.slice(0, t) : e;
}
function se(e) {
	let t = /* @__PURE__ */ new Set();
	for (let n of e || []) for (let e of n.tracks || []) {
		let n = $(e.name);
		n && t.add(n);
	}
	return t;
}
function ce(e) {
	let t = 0;
	for (let n of e || []) {
		t = Math.max(t, Number(n.duration) || 0);
		for (let e of n.tracks || []) {
			let n = e.times;
			n?.length && (t = Math.max(t, n[n.length - 1]));
		}
	}
	return t;
}
function le(e) {
	return e || [];
}
function ue(e, t) {
	return t > 0 ? Math.min(Math.max(0, e), t) : Math.max(0, e);
}
function de(e, t, n) {
	if (!t || !e.length) return Math.max(0, Number(n) || 0);
	let r = Math.max(0, Number(n) || 0);
	for (let t of e) t.enabled = !0, t.paused = !1, t.time = r;
	return t.update(0), r;
}
function fe(e, t, n) {
	let r = t || 0;
	return {
		max: r.toFixed(2),
		value: e.toFixed(2),
		disabled: r <= 0,
		displayText: `${n(e)} / ${n(r)}`
	};
}
function pe(e) {
	let t = e.animationDuration || 0;
	return t ? e.activeCameraName ? e.cameraMoves ? "拖动时间条或点 ▶ 播放 · 跟随相机视角 · 「印到当前分镜」保存当前画面" : `动画 ${e.formatTime(t)} · 当前相机「${e.activeCameraName}」未随时间变化。请换其他相机，或在 Blender 给该相机（或其父级）打关键帧后重新导出。` : `动画 ${e.formatTime(t)} · 请在左侧选择相机` : "未检测到 GLB 动画。Blender 导出请勾选 Animation，Animation mode 建议选 Scene，并勾选 Bake All Objects Animations。";
}
function me(e, t, n) {
	let r = n || 0, i = e + t;
	return r > 0 && i >= r ? {
		nextTime: r,
		reachedEnd: !0
	} : {
		nextTime: i,
		reachedEnd: !1
	};
}
//#endregion
export { e as PRIMITIVE_TYPES, me as advancePlaybackTime, h as applyFollowCameraToEditor, ae as applyWorkspaceProgramLighting, pe as buildAnimationHint, ie as buildLightStatusText, fe as buildTimelineUiState, I as calibrateImportedLights, U as cameraMovesOverTime, c as captureRendererPng, ue as clampAnimationTime, se as collectAnimatedNodeNames, R as collectImportedCameras, i as colorFrom, ce as computeClipDuration, F as countImportedLights, oe as createBlenderEnvMap, s as createMeshFromSpec, o as defaultAddObjectSpec, a as defaultSceneData, z as diagnoseMissingCameras, N as disposeObject3DRoot, P as disposePrimitiveMesh, r as eulerFrom, ne as exportBlenderSceneData, D as exportBuiltinSceneData, E as exportBuiltinSceneObjects, p as exportViewState, w as formatWorkspaceTime, l as fovToFocalLength, H as frameImportedScene, f as getCameraStateFromEditor, Z as getEnvMapIntensity, d as getProjectCanvasAspect, u as getProjectCanvasSize, C as initWorkspaceEditorThree, L as isNodeInSceneGraph, m as loadShotCameraIntoEditor, t as makeId, q as normalizeProgramLightingMode, O as normalizeWorkspaceSceneMeta, V as pickBestCameraId, K as prepareImportedMaterials, Q as programLightingModeLabel, re as programLightingReason, W as resolveViewNode, B as scoreCameraForAnimation, le as selectAnimationClips, G as setImportedLightsVisible, Y as shouldUseProgramFill, J as shouldUseProgramIbl, X as shouldUseProgramWeakFill, de as syncMixerActionsTime, $ as trackNodeName, n as vec3From };
