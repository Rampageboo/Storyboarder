import * as e from "/static/vendor/three/three.module.js";
import { OrbitControls as t } from "/static/vendor/three/OrbitControls.js";
import { TransformControls as n } from "/static/vendor/three/TransformControls.js";
import { GLTFLoader as r } from "/static/vendor/three/GLTFLoader.js";
import { RoomEnvironment as i } from "/static/vendor/three/RoomEnvironment.js";
//#region src/scene3d/workspace/workspacePrimitives.ts
var a = new Set([
	"cube",
	"sphere",
	"plane",
	"cylinder",
	"cone"
]);
function o() {
	let e = globalThis.crypto;
	return e && typeof e.randomUUID == "function" ? e.randomUUID().replace(/-/g, "").slice(0, 12) : `obj_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}
function s(e, t = [
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
function c(e) {
	return s(e);
}
function l(e, t, n = 8421504) {
	return typeof t == "string" && t.startsWith("#") ? new e.Color(t).getHex() : n;
}
function u() {
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
function d(e, t, n) {
	let r = `${{
		cube: "Cube",
		sphere: "Sphere",
		plane: "Plane",
		cylinder: "Cylinder",
		cone: "Cone"
	}[e] || "Object"} ${t + 1}`;
	return {
		id: o(),
		name: r,
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
		color: n
	};
}
function f(e, t) {
	let n = new e.MeshStandardMaterial({
		color: l(e, t.color),
		roughness: .55,
		metalness: .05
	}), r;
	switch (t.type) {
		case "sphere":
			r = new e.SphereGeometry(.5, 32, 24);
			break;
		case "plane":
			r = new e.PlaneGeometry(1, 1);
			break;
		case "cylinder":
			r = new e.CylinderGeometry(.5, .5, 1, 32);
			break;
		case "cone":
			r = new e.ConeGeometry(.5, 1, 32);
			break;
		default:
			r = new e.BoxGeometry(1, 1, 1);
			break;
	}
	let i = new e.Mesh(r, n);
	i.castShadow = t.type !== "plane", i.receiveShadow = t.type === "plane", i.userData.objectId = t.id, i.userData.objectName = t.name || t.type, i.userData.objectType = t.type;
	let [a, o, u] = s(t.position, [
		0,
		.5,
		0
	]), [d, f, p] = c(t.rotation), [m, h, g] = s(t.scale, [
		1,
		1,
		1
	]);
	return i.position.set(a, o, u), i.rotation.set(d, f, p), i.scale.set(m, h, g), i;
}
//#endregion
//#region src/scene3d/workspace/workspaceCapture.ts
function p(e, t, n, r, i = {}) {
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
function m(e, t = 36) {
	return t / (2 * Math.tan(e * Math.PI / 360));
}
function h() {
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
function g() {
	let e = h();
	return e.width / Math.max(1, e.height);
}
function _(e, t) {
	let n = t.target.clone();
	return {
		position: e.position.toArray(),
		target: n.toArray(),
		rotation: e.rotation.toArray().slice(0, 3),
		fov: e.fov,
		focal_length: Math.round(m(Number(e.fov) || 50))
	};
}
function v(e, t) {
	let n = _(t.camera, t.orbit), r = t.camera.getWorldDirection(new e.Vector3()), i = Math.max(.001, t.camera.position.distanceTo(t.orbit.target)) || 1, a = t.camera.position.clone().add(r.multiplyScalar(i)), o = !!(t.followCamera && t.activeCamera);
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
function ee(e, t, n, r, i = [
	6,
	4,
	8
], a = [
	0,
	.5,
	0
]) {
	if (!r?.position) return !1;
	let o = b(r.position, i);
	if (t.position.set(o[0], o[1], o[2]), r.target) {
		let e = b(r.target, a);
		n.target.set(e[0], e[1], e[2]);
	} else if (r.rotation) {
		let [i, a, o] = b(r.rotation);
		t.rotation.set(i, a, o), n.target.copy(t.position.clone().add(t.getWorldDirection(new e.Vector3())));
	}
	return r.fov && (t.fov = Number(r.fov) || 50, t.updateProjectionMatrix()), n.update(), !0;
}
function y(e, t, n, r) {
	if (!n?.object3d) return !1;
	let i = n.viewNode || n.object3d;
	i.updateWorldMatrix(!0, !1), i.matrixWorld.decompose(r.position, r.quaternion, r.scale), e.position.copy(r.position), e.quaternion.copy(r.quaternion);
	let a = n.object3d.isCamera ? n.object3d : null;
	return a?.isPerspectiveCamera && (e.fov = a.fov, e.near = Math.max(.001, a.near), e.far = Math.max(e.near + 1, a.far), e.updateProjectionMatrix()), t.enabled = !1, !0;
}
function b(e, t = [
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
var x = 1711393, S = [
	6,
	4,
	8
], C = [
	0,
	.5,
	0
];
function te(e, t, n = {}) {
	let r = new e.WebGLRenderer({
		antialias: !0,
		alpha: !1,
		preserveDrawingBuffer: !0
	}), i = n.maxPixelRatio ?? 2;
	return r.setPixelRatio(Math.min(window.devicePixelRatio, i)), r.outputColorSpace = e.SRGBColorSpace, r.toneMapping = e.AgXToneMapping ?? e.ACESFilmicToneMapping, r.toneMappingExposure = 1, r.shadowMap.enabled = !0, r.shadowMap.type = e.PCFSoftShadowMap, t.appendChild(r.domElement), r;
}
function ne(e) {
	let t = new e.Scene();
	t.background = new e.Color(x);
	let n = new e.PerspectiveCamera(50, 1, .01, 1e3);
	n.position.set(...S);
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
		builtinBackground: new e.Color(x),
		pmremGenerator: null
	};
}
function re(e, t) {
	let n = new e.PMREMGenerator(t);
	return n.compileEquirectangularShader(), n;
}
//#endregion
//#region src/scene3d/workspace/workspaceControls.ts
function ie(e, t, n, r = {}) {
	let i = new e(t, n);
	i.enableDamping = !0;
	let [a, o, s] = r.target ?? C;
	return i.target.set(a, o, s), r.onChange && i.addEventListener("change", r.onChange), i;
}
function ae(e, t, n, r, i = {}) {
	let a = new e(t, n);
	return a.setMode(i.mode ?? "translate"), a.addEventListener("dragging-changed", (e) => {
		i.onDraggingChanged?.(!!e.value);
	}), a.addEventListener("objectChange", () => {
		i.onObjectChange?.();
	}), r.add(a), a;
}
//#endregion
//#region src/scene3d/workspace/workspaceBridge.ts
function oe(e, t, n, r) {
	let i = te(e, r.mountEl), a = ne(e), o = re(e, i), s = ie(t, a.camera, i.domElement, { onChange: r.onOrbitChange }), c = ae(n, a.camera, i.domElement, a.scene, {
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
function se(e, t) {
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
function ce(e) {
	let t = [];
	for (let [n, r] of e) t.push(se(n, r));
	return t;
}
function le(e, t, n) {
	return {
		source: "builtin",
		objects: ce(e),
		wireframe_mode: t,
		object_color_preview: n
	};
}
function ue(e) {
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
function de(e) {
	return e && typeof e == "object" ? { ...e } : {};
}
//#endregion
//#region src/scene3d/previewStyle.ts
var fe = [
	13138542,
	7256186,
	7245512,
	13152366,
	11562696,
	7260344,
	13135498,
	9095278,
	7237320,
	13145198,
	7254216,
	10537070,
	13138040,
	7915640,
	7895240,
	13158520
];
function pe(e) {
	let t = 0;
	for (let n = 0; n < e.length; n += 1) t = t * 31 + e.charCodeAt(n) | 0;
	return Math.abs(t);
}
function T(e) {
	return e === "on" || e === "strong" ? e : "off";
}
function E(e, t) {
	let n = e;
	for (; n.parent && n.parent !== t;) {
		if (n.name) return n.name;
		n = n.parent;
	}
	return e.name || e.uuid;
}
function me(e) {
	return fe[pe(String(e)) % fe.length];
}
function D(e, t) {
	return new e.Color(me(t));
}
function he(e, t) {
	e instanceof Set ? e.add(t) : e.push(t);
}
function ge(e) {
	e?.traverse((e) => {
		!e.isMesh || e.userData.scene3dOriginalMaterial !== void 0 || (e.userData.scene3dOriginalMaterial = e.material);
	});
}
function _e(e) {
	e?.traverse((e) => {
		!e.isMesh || e.userData.scene3dOriginalMaterial === void 0 || (e.material = e.userData.scene3dOriginalMaterial, delete e.userData.scene3dOriginalMaterial);
	});
}
function O(e) {
	let t = e instanceof Set ? [...e] : e;
	for (let e of t) try {
		e.dispose?.();
	} catch {}
	e instanceof Set ? e.clear() : e.length = 0;
}
function ve(e, t, n, r, i) {
	if (!t) return;
	if (!i) {
		_e(t), O(r);
		return;
	}
	ge(t), O(r);
	let a = /* @__PURE__ */ new Map(), o = /* @__PURE__ */ new Set();
	t.traverse((e) => {
		e.isMesh && o.add(E(e, n ?? t));
	});
	for (let t of [...o].sort()) a.set(t, D(e, t));
	t.traverse((i) => {
		if (!i.isMesh) return;
		let o = E(i, n ?? t), s = new e.MeshBasicMaterial({ color: a.get(o) || D(e, o) });
		he(r, s), i.material = s, i.frustumCulled = !1;
	});
}
function k() {
	return {
		geometries: /* @__PURE__ */ new Set(),
		materials: /* @__PURE__ */ new Set()
	};
}
function ye(e) {
	e?.traverse((e) => {
		if (!e.isMesh || e.userData.scene3dWireframeFillOpacity == null) return;
		let t = Array.isArray(e.material) ? e.material : [e.material];
		for (let n of t) n && (n.opacity = e.userData.scene3dWireframeFillOpacity, n.transparent = e.userData.scene3dWireframeFillTransparent, n.needsUpdate = !0);
		delete e.userData.scene3dWireframeFillOpacity, delete e.userData.scene3dWireframeFillTransparent;
	});
}
function A(e, t) {
	let n = Array.isArray(e) ? e : [e];
	for (let e of n) e && (ye(e), e.traverse((e) => {
		let t = e.userData?.scene3dWireframeLine;
		t && (e.remove(t), delete e.userData.scene3dWireframeLine);
	}));
	for (let e of t.geometries) try {
		e.dispose?.();
	} catch {}
	for (let e of t.materials) try {
		e.dispose?.();
	} catch {}
	t.geometries.clear(), t.materials.clear();
}
function be(e, t, n, r) {
	let i = Array.isArray(t) ? t : [t], a = T(n);
	if (A(i, r), a === "off") return;
	let o = a === "strong", s = o ? 1 : 35, c = new e.LineBasicMaterial({
		color: o ? 16777215 : 1381653,
		transparent: !o,
		opacity: o ? 1 : .72,
		depthTest: !0,
		depthWrite: !1
	});
	r.materials.add(c);
	for (let t of i) t && t.traverse((t) => {
		if (!t.isMesh || !t.geometry || t.userData.scene3dWireframeLine) return;
		let n = new e.EdgesGeometry(t.geometry, s), i = new e.LineSegments(n, c);
		if (i.renderOrder = o ? 2 : 1, i.frustumCulled = !1, t.add(i), t.userData.scene3dWireframeLine = i, r.geometries.add(n), o && t.material) {
			let e = Array.isArray(t.material) ? t.material : [t.material];
			for (let n of e) !n || t.userData.scene3dWireframeFillOpacity != null || (t.userData.scene3dWireframeFillOpacity = n.opacity ?? 1, t.userData.scene3dWireframeFillTransparent = !!n.transparent, n.transparent = !0, n.opacity = Math.min(n.opacity ?? 1, .42), n.needsUpdate = !0);
		}
	});
}
//#endregion
//#region src/scene3d/dispose.ts
function xe(e) {
	if (!e || typeof e != "object") return;
	let t = e;
	try {
		t.dispose?.();
	} catch {}
}
function j(e) {
	let t = Array.isArray(e) ? e : [e];
	for (let e of t) {
		if (!e || typeof e != "object") continue;
		let t = e;
		for (let e of Object.keys(t)) xe(t[e]);
		try {
			t.dispose?.();
		} catch {}
	}
}
function M(e) {
	try {
		e?.dispose?.();
	} catch {}
}
function Se(e) {
	try {
		M(e.geometry), j(e.material);
	} catch {}
}
//#endregion
//#region src/scene3d/workspace/workspaceDispose.ts
function N(e) {
	e?.traverse?.((e) => {
		let t = e.userData?.scene3dOriginalMaterial;
		if (t) {
			j(t);
			return;
		}
		Se(e);
	});
}
function P(e) {
	e && (M(e.geometry), j(e.material));
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
function Ce(e, t) {
	e?.traverse?.((e) => {
		if (!e.isMesh) return;
		let n = Array.isArray(e.material) ? e.material : [e.material];
		for (let e of n) e?.isMeshStandardMaterial && (e.envMapIntensity = t, e.needsUpdate = !0);
	});
}
//#endregion
//#region src/scene3d/workspace/workspaceLighting.ts
function we(e) {
	return e === "on" || e === "off" ? e : "auto";
}
function K(e) {
	return !(e.workspaceMode !== "blender" || e.mode === "off");
}
function q(e) {
	return e.workspaceMode !== "blender" || e.mode === "off" ? !1 : (e.mode, e.importedLightCount === 0);
}
function J(e) {
	return e.workspaceMode !== "blender" || e.mode === "off" || e.objectColorPreview ? !1 : (e.mode, e.importedLightCount > 0);
}
function Te(e) {
	return K(e) ? e.importedLightCount > 0 ? .35 : 1 : 0;
}
function Ee(e) {
	return e.mode === "on" ? "手动：环境 + 柔光" : e.mode === "off" ? "手动：仅 GLB 灯光" : e.importedLightCount > 0 ? `自动：GLB ${e.importedLightCount} 盏灯 + 弱环境反射` : "自动：GLB 无灯，全程序补光";
}
function Y(e) {
	switch (e) {
		case "on": return "始终开启";
		case "off": return "关闭";
		default: return "自动";
	}
}
function De(e) {
	let t = e.importedLightCount > 0 ? `GLB 已导出 ${e.importedLightCount} 盏灯` : "GLB 未导出灯光（导出时请勾选 Punctual Lights）", n = K(e) && !e.objectColorPreview ? "环境反射：开" : "环境反射：关", r = q(e) ? "柔光补光：开" : J(e) ? "柔光补光：弱" : "柔光补光：关", i = e.objectColorPreview ? "对象色：开（不受灯光影响）" : "对象色：关";
	return `${t} · ${Y(e.mode)} · ${n} · ${r} · ${i}`;
}
function Oe(e, t, n) {
	if (t.workspaceMode !== "blender") return;
	let r = K(t) && !t.objectColorPreview, i = q(t), a = J(t);
	r ? (n.scene.environment = n.ensureBlenderEnvMap(), n.scene.background = new e.Color(3158064)) : t.objectColorPreview ? (n.scene.environment = null, n.scene.background = new e.Color(3815994)) : (n.scene.environment = null, n.scene.background = n.builtinBackground.clone()), n.programAmbient.intensity = i ? .1 : .22, n.programAmbient.visible = i || a, n.programHemisphere.visible = i, n.setImportedLightsVisible(!t.objectColorPreview);
}
function ke(e, t) {
	let n = new e(), r = t.fromScene(n, .04).texture;
	return n.dispose?.(), r;
}
//#endregion
//#region src/scene3d/workspace/workspaceAnimation.ts
function X(e) {
	let t = String(e || "").lastIndexOf(".");
	return t > 0 ? e.slice(0, t) : e;
}
function Ae(e) {
	let t = /* @__PURE__ */ new Set();
	for (let n of e || []) for (let e of n.tracks || []) {
		let n = X(e.name);
		n && t.add(n);
	}
	return t;
}
function Z(e) {
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
function Q(e) {
	return e || [];
}
function je(e, t) {
	return t > 0 ? Math.min(Math.max(0, e), t) : Math.max(0, e);
}
function Me(e, t, n) {
	if (!t || !e.length) return Math.max(0, Number(n) || 0);
	let r = Math.max(0, Number(n) || 0);
	for (let t of e) t.enabled = !0, t.paused = !1, t.time = r;
	return t.update(0), r;
}
function Ne(e, t, n) {
	let r = t || 0;
	return {
		max: r.toFixed(2),
		value: e.toFixed(2),
		disabled: r <= 0,
		displayText: `${n(e)} / ${n(r)}`
	};
}
function Pe(e) {
	let t = e.animationDuration || 0;
	return t ? e.activeCameraName ? e.cameraMoves ? "拖动时间条或点 ▶ 播放 · 跟随相机视角 · 「印到当前分镜」保存当前画面" : `动画 ${e.formatTime(t)} · 当前相机「${e.activeCameraName}」未随时间变化。请换其他相机，或在 Blender 给该相机（或其父级）打关键帧后重新导出。` : `动画 ${e.formatTime(t)} · 请在左侧选择相机` : "未检测到 GLB 动画。Blender 导出请勾选 Animation，Animation mode 建议选 Scene，并勾选 Bake All Objects Animations。";
}
function Fe(e, t, n) {
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
//#region src/scene3d/workspace/workspaceMaterials.ts
function Ie(e) {
	e?.traverse?.((e) => {
		!e.isMesh || e.userData.scene3dOriginalMaterial !== void 0 || (e.userData.scene3dOriginalMaterial = e.material);
	});
}
function Le(e) {
	e?.traverse?.((e) => {
		!e.isMesh || e.userData.scene3dOriginalMaterial === void 0 || (e.material = e.userData.scene3dOriginalMaterial);
	});
}
function Re(e, t) {
	let n = /* @__PURE__ */ new Set();
	return e?.traverse?.((e) => {
		e.isMesh && n.add(t(e));
	}), [...n].sort();
}
//#endregion
//#region src/scene3d/workspace/workspaceGlbLoad.ts
function ze(e, t, n) {
	let r = Q(n || []), i = e.AnimationMixer, a = new i(t), o = [], s = e.LoopOnce;
	for (let e of r) {
		let t = a.clipAction(e);
		t.setLoop(s, 1), t.play(), o.push(t);
	}
	return {
		mixer: a,
		mixerActions: o,
		animationDuration: Z(r.length ? r : n)
	};
}
function Be(e) {
	let { gltf: t, importedCameras: n, animationDuration: r, importedLightCount: i, programLightingMode: a } = e, o = [];
	return n.length === 0 ? (o.push(z(t)), o) : (n.some((e) => e.orphan) ? o.push(`已找到 ${n.length} 个相机（部分未挂到场景树，已自动修复）。`) : (t.animations || []).length ? r <= 0 ? o.push("已找到动画轨道，但时长为 0。请检查 Blender 时间轴范围与关键帧。") : a === "auto" && (i > 0 ? o.push(`检测到 GLB 含 ${i} 盏灯，已校准强度并启用弱环境反射（模拟 Blender World）。`) : o.push("GLB 无导出灯光，已自动开启全程序补光。")) : o.push("场景已加载，但未找到动画。请在 Blender 导出时勾选 Animation。"), o);
}
function Ve(e, t) {
	if (t != null && !Number.isNaN(Number(t))) return Number(t);
	let n = Number(e.animation_time);
	return !Number.isNaN(n) && n >= 0 ? n : null;
}
function He(e, t) {
	return e <= 0 ? 0 : Math.min(e, t || e);
}
function Ue(e, t) {
	let n = t.blend_file_path || "scene3d/scene.blend", r = t.file_name || t.file_path || "";
	return e === "blender" && r ? `GLB: ${String(r).split("/").pop()}` : n.split("/").pop() || "scene.blend";
}
function We(e, t) {
	let n = [];
	e && n.push(e);
	for (let e of t) n.push(e);
	return n;
}
function Ge(e, t, n) {
	let r = e?.objects?.length ? e : t(), i = (r.objects || []).filter((e) => n.has(String(e.type || "")));
	return {
		...r,
		objects: i
	};
}
//#endregion
//#region src/scene3d/workspace/workspaceTransform.ts
function Ke(e, t, n, r, i) {
	let a = (e, t) => Number(n[e]?.value) || t, o = e.MathUtils;
	t.position.set(a("px", t.position.x), a("py", t.position.y), a("pz", t.position.z)), t.rotation.set(o.degToRad(a("rx", o.radToDeg(t.rotation.x))), o.degToRad(a("ry", o.radToDeg(t.rotation.y))), o.degToRad(a("rz", o.radToDeg(t.rotation.z)))), t.scale.set(Math.max(.01, a("sx", t.scale.x)), Math.max(.01, a("sy", t.scale.y)), Math.max(.01, a("sz", t.scale.z))), r && i?.updateMatrixWorld();
}
function qe(e, t, n) {
	let r = !t;
	for (let e of Object.values(n)) e.disabled = r;
	if (!t) return;
	let i = e.MathUtils;
	n.px.value = t.position.x.toFixed(2), n.py.value = t.position.y.toFixed(2), n.pz.value = t.position.z.toFixed(2), n.rx.value = i.radToDeg(t.rotation.x).toFixed(1), n.ry.value = i.radToDeg(t.rotation.y).toFixed(1), n.rz.value = i.radToDeg(t.rotation.z).toFixed(1), n.sx.value = t.scale.x.toFixed(2), n.sy.value = t.scale.y.toFixed(2), n.sz.value = t.scale.z.toFixed(2);
}
var Je = {
	off: "关闭",
	on: "标准",
	strong: "强化"
};
//#endregion
//#region src/scene3d/workspace/workspaceOutliner.ts
function Ye(e, t, n, r, i) {
	if (e === "blender") return n.length ? n.map((e) => ({
		kind: "camera",
		id: e.id,
		label: e.name,
		active: e.id === r
	})) : [{
		kind: "empty",
		label: "无相机"
	}];
	let a = [], o = t instanceof Map ? t.entries() : t;
	for (let [e, t] of o) a.push({
		kind: "object",
		id: e,
		label: String(t.userData?.objectName || e),
		active: e === i
	});
	return a;
}
function Xe(e, t) {
	e.innerHTML = "";
	for (let n of t) {
		let t = document.createElement("li");
		n.kind === "empty" ? (t.className = "scene3d-empty", t.textContent = n.label) : n.kind === "camera" ? (t.dataset.cameraId = n.id, t.className = n.active ? "active" : "", t.textContent = `📷 ${n.label}`) : (t.dataset.objectId = n.id, t.className = n.active ? "active" : "", t.textContent = n.label), e.appendChild(t);
	}
}
function Ze(e) {
	return e.length ? e.map((e) => ({
		value: e.id,
		label: e.name
	})) : [{
		value: "",
		label: "（无相机）"
	}];
}
function Qe(e, t, n = "") {
	e.innerHTML = "";
	for (let n of t) {
		let t = document.createElement("option");
		t.value = n.value, t.textContent = n.label, e.appendChild(t);
	}
	e.disabled = t.length === 1 && t[0].value === "", n && !e.disabled && (e.value = n);
}
//#endregion
//#region src/scene3d/workspace/workspaceMode.ts
function $e(e, t) {
	e.classList.toggle("scene3d-mode-blender", t === "blender"), e.classList.toggle("scene3d-mode-builtin", t === "builtin"), e.querySelectorAll(".scene3d-blender-only").forEach((e) => {
		e.hidden = t !== "blender";
	}), e.querySelectorAll(".scene3d-builtin-only").forEach((e) => {
		e.hidden = t === "blender";
	});
}
function et(e, t) {
	let n = e === "builtin";
	t.grid.visible = n, t.axes.visible = n, t.defaultAmbient.visible = n, t.defaultSun.visible = n, n && (t.scene.environment = null, t.scene.background = t.builtinBackground.clone(), t.programAmbient.visible = !1, t.programHemisphere.visible = !1);
}
function tt(e, t) {
	return !(t && e === "blender");
}
//#endregion
//#region src/scene3d/workspace/workspaceSelection.ts
function $(e) {
	return !!(e && e !== "ground");
}
function nt(e, t) {
	return !!(t && e === "builtin");
}
function rt(e, t) {
	return e ? e.position.clone() : t.target.clone();
}
function it(e, t) {
	let [n, r, i] = S, [a, o, s] = C;
	e.position.set(n, r, i), t.target.set(a, o, s), t.update();
}
//#endregion
//#region src/scene3d/workspace/workspaceInput.ts
function at(e) {
	return !!(e && e instanceof Element && e.matches("input, textarea, select"));
}
function ot(e) {
	return e.code === "Space" ? { type: "togglePlayback" } : e.code === "F5" ? { type: "reloadGlb" } : e.key === "Home" ? { type: "goToStart" } : e.key === "ArrowLeft" ? {
		type: "stepAnimation",
		delta: e.shiftKey ? -.5 : -.1
	} : e.key === "ArrowRight" ? {
		type: "stepAnimation",
		delta: e.shiftKey ? .5 : .1
	} : null;
}
function st(e) {
	let t = e.key.toLowerCase();
	return t === "g" ? {
		type: "setTransformMode",
		mode: "translate"
	} : t === "r" ? {
		type: "setTransformMode",
		mode: "rotate"
	} : t === "s" ? {
		type: "setTransformMode",
		mode: "scale"
	} : t === "delete" ? { type: "deleteSelected" } : t === "f" ? { type: "focusSelected" } : null;
}
function ct(e, t) {
	switch (e.type) {
		case "togglePlayback":
			t.togglePlayback();
			break;
		case "reloadGlb":
			t.reloadGlb();
			break;
		case "goToStart":
			t.goToStart();
			break;
		case "stepAnimation":
			t.stepAnimation(e.delta);
			break;
		case "setTransformMode":
			t.setTransformMode(e.mode);
			break;
		case "deleteSelected":
			t.deleteSelected();
			break;
		case "focusSelected":
			t.focusSelected();
			break;
	}
}
//#endregion
//#region src/scene3d/workspace/workspaceClear.ts
function lt() {
	return {
		mixer: null,
		mixerActions: [],
		importedCameras: [],
		activeCameraId: "",
		importedLightCount: 0,
		animationDuration: 0,
		animationTime: 0,
		isPlaying: !1
	};
}
function ut(e) {
	e?.stopAllAction?.();
}
//#endregion
//#region src/scene3d/workspace/workspaceEditor.ts
var dt = class {
	rootEl;
	callbacks;
	sceneData;
	sceneMeta;
	mode;
	objects;
	selectedId;
	transformMode;
	shotCameraHelper;
	animationId;
	clock;
	blenderRoot;
	mixer;
	mixerActions;
	importedCameras;
	activeCameraId;
	followCamera;
	isPlaying;
	programLightingMode;
	importedLightCount;
	objectColorPreview;
	previewMaterials;
	wireframeMode;
	wireframeResources;
	animationTime;
	animationDuration;
	animatedNodeNames;
	_followPos;
	_followQuat;
	_followScale;
	_probePosA;
	_probePosB;
	_sceneSettingsSaveTimer;
	_suppressViewChange;
	_disposed;
	renderer;
	scene;
	camera;
	defaultAmbient;
	defaultSun;
	programAmbient;
	programHemisphere;
	grid;
	axes;
	builtinBackground;
	pmremGenerator;
	blenderEnvMap;
	orbit;
	transform;
	raycaster;
	pointer;
	outlinerEl;
	viewportEl;
	formatFrameEl;
	fileNameEl;
	cameraSelectEl;
	followCameraEl;
	objectColorsEl;
	wireframeModeEl;
	programLightingEl;
	lightStatusEl;
	timeSliderEl;
	timeDisplayEl;
	boardPreviewImg;
	boardPreviewEmpty;
	boardLabelEl;
	playPauseBtn;
	hintEl;
	transformInputs;
	_resizeObserver;
	_keydownHandler;
	_pointerdownHandler;
	constructor(t, n = {}) {
		this.rootEl = t, this.callbacks = n, this.sceneData = u(), this.sceneMeta = {}, this.mode = "builtin", this.objects = /* @__PURE__ */ new Map(), this.selectedId = null, this.transformMode = "translate", this.shotCameraHelper = null, this.animationId = null, this.clock = new e.Clock(), this.blenderRoot = null, this.mixer = null, this.mixerActions = [], this.importedCameras = [], this.activeCameraId = "", this.followCamera = !0, this.isPlaying = !1, this.programLightingMode = "auto", this.importedLightCount = 0, this.objectColorPreview = !0, this.previewMaterials = /* @__PURE__ */ new Set(), this.wireframeMode = "off", this.wireframeResources = k(), this.animationTime = 0, this.animationDuration = 0, this.animatedNodeNames = /* @__PURE__ */ new Set(), this._followPos = new e.Vector3(), this._followQuat = new e.Quaternion(), this._followScale = new e.Vector3(), this._probePosA = new e.Vector3(), this._probePosB = new e.Vector3(), this._sceneSettingsSaveTimer = null, this._suppressViewChange = !1, this._disposed = !1, this.renderer = null, this.scene = null, this.camera = null, this.defaultAmbient = null, this.defaultSun = null, this.programAmbient = null, this.programHemisphere = null, this.grid = null, this.axes = null, this.builtinBackground = null, this.pmremGenerator = null, this.blenderEnvMap = null, this.orbit = null, this.transform = null, this.raycaster = null, this.pointer = null, this.transformInputs = {}, this._buildDom(), this._initThree(), this._bindUi();
	}
	_buildDom() {
		this.rootEl.innerHTML = "\n      <div class=\"scene3d-layout\">\n        <aside class=\"scene3d-sidebar\">\n          <div class=\"scene3d-panel-title\">当前分镜预览</div>\n          <div class=\"scene3d-board-preview\" data-board-preview>\n            <img data-board-preview-img alt=\"\" hidden />\n            <span class=\"scene3d-board-preview-empty\" data-board-preview-empty>无预览 · Capture 后显示</span>\n          </div>\n          <div class=\"scene3d-board-label\" data-board-label>—</div>\n          <div class=\"scene3d-panel-title\">Blender 场景</div>\n          <div class=\"scene3d-blender-panel\">\n            <div class=\"scene3d-file-name\" data-blend-name>scene3d/scene.blend</div>\n            <button type=\"button\" data-action=\"open-blender\" class=\"scene3d-import-btn\">在 Blender 中打开</button>\n            <button type=\"button\" data-action=\"import-blender\" class=\"scene3d-import-btn\">导入 GLB / GLTF</button>\n            <button type=\"button\" data-action=\"reload-glb\" class=\"scene3d-import-btn\">刷新 GLB</button>\n            <label class=\"scene3d-check\">\n              <input type=\"checkbox\" data-follow-camera checked />\n              跟随相机视角\n            </label>\n            <label class=\"scene3d-check\">\n              <input type=\"checkbox\" data-object-colors checked />\n              对象随机色（低饱和，便于区分）\n            </label>\n            <label class=\"scene3d-field\">\n              <span>线框</span>\n              <select data-wireframe-mode>\n                <option value=\"off\">关闭</option>\n                <option value=\"on\">标准（叠加边线）</option>\n                <option value=\"strong\">强化（全边线 + 高亮）</option>\n              </select>\n            </label>\n            <label class=\"scene3d-field\">\n              <span>程序补光</span>\n              <select data-program-lighting>\n                <option value=\"auto\">自动（有灯：环境反射；无灯：全补光）</option>\n                <option value=\"on\">始终开启（环境 + 柔光）</option>\n                <option value=\"off\">关闭（仅 GLB 灯光）</option>\n              </select>\n            </label>\n            <div class=\"scene3d-light-status\" data-light-status>—</div>\n            <label class=\"scene3d-field\">\n              <span>相机</span>\n              <select data-camera-select disabled>\n                <option value=\"\">（无相机）</option>\n              </select>\n            </label>\n          </div>\n          <div class=\"scene3d-panel-title\">Outliner</div>\n          <ul class=\"scene3d-outliner\" data-outliner></ul>\n          <div class=\"scene3d-panel-title scene3d-builtin-only\">Transform</div>\n          <div class=\"scene3d-transform-fields scene3d-builtin-only\">\n            <label>位置 X <input type=\"number\" step=\"0.1\" data-tf=\"px\" /></label>\n            <label>位置 Y <input type=\"number\" step=\"0.1\" data-tf=\"py\" /></label>\n            <label>位置 Z <input type=\"number\" step=\"0.1\" data-tf=\"pz\" /></label>\n            <label>旋转 X <input type=\"number\" step=\"1\" data-tf=\"rx\" /></label>\n            <label>旋转 Y <input type=\"number\" step=\"1\" data-tf=\"ry\" /></label>\n            <label>旋转 Z <input type=\"number\" step=\"1\" data-tf=\"rz\" /></label>\n            <label>缩放 X <input type=\"number\" step=\"0.1\" min=\"0.01\" data-tf=\"sx\" /></label>\n            <label>缩放 Y <input type=\"number\" step=\"0.1\" min=\"0.01\" data-tf=\"sy\" /></label>\n            <label>缩放 Z <input type=\"number\" step=\"0.1\" min=\"0.01\" data-tf=\"sz\" /></label>\n          </div>\n        </aside>\n        <div class=\"scene3d-main\">\n          <div class=\"scene3d-toolbar\">\n            <div class=\"scene3d-tool-group scene3d-builtin-only\">\n              <button type=\"button\" data-mode=\"translate\" class=\"active\" title=\"移动 (G)\">移动</button>\n              <button type=\"button\" data-mode=\"rotate\" title=\"旋转 (R)\">旋转</button>\n              <button type=\"button\" data-mode=\"scale\" title=\"缩放 (S)\">缩放</button>\n            </div>\n            <div class=\"scene3d-tool-group scene3d-builtin-only\">\n              <button type=\"button\" data-add=\"cube\">立方体</button>\n              <button type=\"button\" data-add=\"sphere\">球体</button>\n              <button type=\"button\" data-add=\"plane\">平面</button>\n              <button type=\"button\" data-add=\"cylinder\">圆柱</button>\n              <button type=\"button\" data-add=\"cone\">圆锥</button>\n            </div>\n            <div class=\"scene3d-tool-group scene3d-blender-only\" hidden>\n              <button type=\"button\" data-action=\"play-pause\">▶ 播放</button>\n              <button type=\"button\" data-action=\"go-to-start\" title=\"回到开头\">⏮ 开头</button>\n              <button type=\"button\" data-action=\"step-back\" title=\"后退 0.1s\">◀</button>\n              <button type=\"button\" data-action=\"step-forward\" title=\"前进 0.1s\">▶</button>\n              <button type=\"button\" data-action=\"capture-board\">印到当前分镜</button>\n              <button type=\"button\" data-action=\"free-view\">自由视角</button>\n            </div>\n            <div class=\"scene3d-tool-group scene3d-builtin-only\">\n              <button type=\"button\" data-action=\"delete\" title=\"删除 (Del)\">删除</button>\n              <button type=\"button\" data-action=\"focus\" title=\"聚焦 (F)\">聚焦</button>\n              <button type=\"button\" data-action=\"reset-view\">重置视图</button>\n            </div>\n            <div class=\"scene3d-tool-group scene3d-tool-group-right scene3d-builtin-only\">\n              <button type=\"button\" data-action=\"load-shot-camera\">加载镜头相机</button>\n              <button type=\"button\" data-action=\"apply-shot-camera\">保存镜头相机</button>\n            </div>\n          </div>\n          <div class=\"scene3d-viewport\" data-viewport>\n            <div class=\"scene3d-format-frame\" data-format-frame></div>\n          </div>\n          <div class=\"scene3d-timeline scene3d-blender-only\" hidden>\n            <input type=\"range\" min=\"0\" max=\"0\" step=\"0.01\" value=\"0\" data-time-slider />\n            <span data-time-display>0.0s / 0.0s</span>\n          </div>\n          <div class=\"scene3d-hint\" data-hint>\n            空格播放/暂停 · ←→ 步进 0.1s（Shift 0.5s）· Home 回开头 · F5 刷新 GLB · 播完停在最后一帧\n          </div>\n        </div>\n      </div>\n    ", this.outlinerEl = this.rootEl.querySelector("[data-outliner]"), this.viewportEl = this.rootEl.querySelector("[data-viewport]"), this.formatFrameEl = this.rootEl.querySelector("[data-format-frame]"), this.fileNameEl = this.rootEl.querySelector("[data-blend-name]"), this.cameraSelectEl = this.rootEl.querySelector("[data-camera-select]"), this.followCameraEl = this.rootEl.querySelector("[data-follow-camera]"), this.objectColorsEl = this.rootEl.querySelector("[data-object-colors]"), this.wireframeModeEl = this.rootEl.querySelector("[data-wireframe-mode]"), this.programLightingEl = this.rootEl.querySelector("[data-program-lighting]"), this.lightStatusEl = this.rootEl.querySelector("[data-light-status]"), this.timeSliderEl = this.rootEl.querySelector("[data-time-slider]"), this.timeDisplayEl = this.rootEl.querySelector("[data-time-display]"), this.boardPreviewImg = this.rootEl.querySelector("[data-board-preview-img]"), this.boardPreviewEmpty = this.rootEl.querySelector("[data-board-preview-empty]"), this.boardLabelEl = this.rootEl.querySelector("[data-board-label]"), this.playPauseBtn = this.rootEl.querySelector("[data-action='play-pause']"), this.hintEl = this.rootEl.querySelector("[data-hint]"), this.transformInputs = {}, this.rootEl.querySelectorAll("[data-tf]").forEach((e) => {
			let t = e;
			this.transformInputs[t.dataset.tf] = t;
		});
	}
	_initThree() {
		let r = oe(e, t, n, {
			mountEl: this.formatFrameEl,
			transformMode: this.transformMode,
			onOrbitChange: () => {
				this.mode === "blender" && !this.followCamera && this._notifyViewChange();
			},
			onTransformDraggingChanged: (e) => {
				this.orbit.enabled = !e && !this.followCamera;
			},
			onTransformObjectChange: () => {
				this._syncSelectedFromMesh(), this._renderOutliner();
			}
		});
		this.renderer = r.renderer, this.scene = r.scene, this.camera = r.camera, this.defaultAmbient = r.defaultAmbient, this.defaultSun = r.defaultSun, this.programAmbient = r.programAmbient, this.programHemisphere = r.programHemisphere, this.grid = r.grid, this.axes = r.axes, this.builtinBackground = r.builtinBackground, this.pmremGenerator = r.pmremGenerator, this.blenderEnvMap = null, this.orbit = r.orbit, this.transform = r.transform, this.raycaster = new e.Raycaster(), this.pointer = new e.Vector2(), this._pointerdownHandler = (e) => this._onPointerDown(e), this.renderer.domElement.addEventListener("pointerdown", this._pointerdownHandler), this._keydownHandler = (e) => this._onKeyDown(e), window.addEventListener("keydown", this._keydownHandler), this._resizeObserver = new ResizeObserver(() => this._resize()), this._resizeObserver.observe(this.viewportEl), this._resize(), this._animate();
	}
	_bindUi() {
		this.rootEl.querySelectorAll("[data-mode]").forEach((e) => {
			let t = e;
			t.addEventListener("click", () => this.setTransformMode(t.dataset.mode));
		}), this.rootEl.querySelectorAll("[data-add]").forEach((e) => {
			let t = e;
			t.addEventListener("click", () => this.addObject(t.dataset.add));
		}), this.rootEl.querySelectorAll("[data-action]").forEach((e) => {
			let t = e;
			t.addEventListener("click", () => this._runAction(t.dataset.action));
		}), Object.entries(this.transformInputs).forEach(([e, t]) => {
			t.addEventListener("change", () => this._applyTransformInputs(e)), t.addEventListener("input", () => this._applyTransformInputs(e));
		}), this.outlinerEl.addEventListener("click", (e) => {
			let t = e.target.closest("[data-camera-id]");
			if (t) {
				this.setFollowCamera(!0, { persist: !1 }), this.setActiveCamera(t.dataset.cameraId);
				return;
			}
			let n = e.target.closest("[data-object-id]");
			n && this.selectObject(n.dataset.objectId);
		}), this.followCameraEl.addEventListener("change", () => {
			this.setFollowCamera(this.followCameraEl.checked);
		}), this.objectColorsEl?.addEventListener("change", () => {
			this.setObjectColorPreview(this.objectColorsEl.checked);
		}), this.wireframeModeEl?.addEventListener("change", () => {
			this.setWireframeMode(this.wireframeModeEl.value);
		}), this.programLightingEl?.addEventListener("change", () => {
			this.setProgramLightingMode(this.programLightingEl.value);
		}), this.cameraSelectEl.addEventListener("change", () => {
			this.setActiveCamera(this.cameraSelectEl.value);
		}), this.timeSliderEl.addEventListener("input", () => {
			this.isPlaying && (this.isPlaying = !1, this._updatePlayButton()), this.setAnimationTime(Number(this.timeSliderEl.value || 0));
		});
	}
	_runAction(e) {
		switch (e) {
			case "delete":
				this.deleteSelected();
				break;
			case "focus":
				this.focusSelected();
				break;
			case "reset-view":
				this.resetView();
				break;
			case "load-shot-camera":
				this.loadShotCamera(this.callbacks.getShotCamera?.());
				break;
			case "apply-shot-camera":
				this.callbacks.onApplyShotCamera?.(this.getCameraState());
				break;
			case "import-blender":
				this.callbacks.onImportBlender?.();
				break;
			case "open-blender":
				this.callbacks.onOpenBlender?.();
				break;
			case "play-pause":
				this.toggleAnimationPlayback();
				break;
			case "go-to-start":
				this.goToAnimationStart();
				break;
			case "step-back":
				this.stepAnimation(-.1);
				break;
			case "step-forward":
				this.stepAnimation(.1);
				break;
			case "reload-glb":
				this.reloadBlenderScene();
				break;
			case "free-view":
				this.setFollowCamera(!1);
				break;
			case "capture-board":
				this.callbacks.onCaptureToBoard?.();
				break;
			default: break;
		}
	}
	_onKeyDown(e) {
		if (at(e.target)) return;
		let t = this.mode === "blender" ? ot(e) : st(e);
		t && (this.mode === "blender" && e.preventDefault(), ct(t, {
			togglePlayback: () => this.toggleAnimationPlayback(),
			reloadGlb: () => this.reloadBlenderScene(),
			goToStart: () => this.goToAnimationStart(),
			stepAnimation: (e) => this.stepAnimation(e),
			setTransformMode: (e) => this.setTransformMode(e),
			deleteSelected: () => this.deleteSelected(),
			focusSelected: () => this.focusSelected()
		}));
	}
	_onPointerDown(e) {
		if (this.mode !== "builtin" || this.transform.dragging) return;
		let t = this.renderer.domElement.getBoundingClientRect();
		this.pointer.x = (e.clientX - t.left) / t.width * 2 - 1, this.pointer.y = -((e.clientY - t.top) / t.height) * 2 + 1, this.raycaster.setFromCamera(this.pointer, this.camera);
		let n = this.raycaster.intersectObjects([...this.objects.values()], !1);
		n.length ? this.selectObject(n[0].object.userData.objectId) : this.selectObject(null);
	}
	setTransformMode(e) {
		this.transformMode = e, this.transform.setMode(e), this.rootEl.querySelectorAll("[data-mode]").forEach((t) => {
			let n = t;
			n.classList.toggle("active", n.dataset.mode === e);
		});
	}
	_scheduleSceneSettingsSave() {
		this.callbacks.onSceneSettingsChange && (window.clearTimeout(this._sceneSettingsSaveTimer ?? void 0), this._sceneSettingsSaveTimer = window.setTimeout(() => {
			this.callbacks.onSceneSettingsChange(this.exportSceneData());
		}, 350));
	}
	applyDisplaySettings(e = {}) {
		!e || typeof e != "object" || (this.setFollowCamera(e.follow_camera !== !1, { persist: !1 }), this.setProgramLightingMode(String(e.program_lighting || "auto"), {
			persist: !1,
			notify: !1
		}), this.setObjectColorPreview(e.object_color_preview !== !1, {
			persist: !1,
			notify: !1
		}), this.setWireframeMode(String(e.wireframe_mode || "off"), {
			persist: !1,
			notify: !1
		}));
	}
	async loadSceneData(e) {
		if (this.sceneMeta = e && typeof e == "object" ? { ...e } : {}, this.setWireframeMode(String(this.sceneMeta.wireframe_mode || "off"), {
			persist: !1,
			notify: !1
		}), this.sceneMeta.source === "blender" && this.sceneMeta.file_path) {
			await this.loadBlenderFromProject(this.sceneMeta);
			return;
		}
		this.setMode("builtin"), this.sceneData = Ge(this.sceneMeta, u, a), this.clearBlenderScene(), this.clearObjects();
		for (let e of this.sceneData.objects || []) this._addMeshFromSpec(e);
		this.selectObject(this.sceneData.objects?.[0]?.id || null), this._renderOutliner(), this._updateFileName(), this._applyWireframeMode();
	}
	_normalizeWireframeMode(e) {
		return T(e);
	}
	setWireframeMode(e, { persist: t = !0, notify: n = !1 } = {}) {
		this.wireframeMode = this._normalizeWireframeMode(e), this.wireframeModeEl && (this.wireframeModeEl.value = this.wireframeMode), t && (this.sceneMeta = {
			...this.sceneMeta || {},
			wireframe_mode: this.wireframeMode
		}), this._applyWireframeMode(), t && this._scheduleSceneSettingsSave(), n && this.callbacks.onMessage?.(`线框：${Je[this.wireframeMode] || this.wireframeMode}`);
	}
	_getWireframeRoots() {
		return We(this.blenderRoot, this.objects.values());
	}
	_clearWireframeOverlays() {
		this.wireframeResources ||= k(), A(this._getWireframeRoots(), this.wireframeResources);
	}
	_applyWireframeMode() {
		this.wireframeResources ||= k(), be(e, this._getWireframeRoots(), this.wireframeMode, this.wireframeResources);
	}
	async loadBlenderFromProject(e) {
		this.setMode("blender"), this._suppressViewChange = !0;
		try {
			this.sceneMeta = { ...e }, this.followCamera = e.follow_camera !== !1, this.followCameraEl.checked = this.followCamera, this.programLightingMode = e.program_lighting === "on" || e.program_lighting === "off" ? e.program_lighting : "auto", this.programLightingEl && (this.programLightingEl.value = this.programLightingMode), this.objectColorPreview = e.object_color_preview !== !1, this.objectColorsEl && (this.objectColorsEl.checked = this.objectColorPreview), this.setWireframeMode(String(e.wireframe_mode || "off"), {
				persist: !1,
				notify: !1
			});
			let t = `/api/project/scene3d/file?t=${Date.now()}`;
			await this._loadBlenderUrl(t, String(e.file_name || e.file_path || "")), e.camera_name ? this.setActiveCamera(this._pickBestCameraId(String(e.camera_name)), !1) : this.importedCameras.length && this.setActiveCamera(this._pickBestCameraId(""), !1);
			let n = this.callbacks.getShotScene3dTime?.(), r = Ve(e, n);
			r != null && this.setAnimationTime(r), this._updateFileName(), this._updateAnimationHint();
		} finally {
			this._suppressViewChange = !1;
		}
	}
	async reloadBlenderScene() {
		if (!this.sceneMeta?.file_path) {
			this.callbacks.onMessage?.("当前项目没有 GLB，请先 Import GLB");
			return;
		}
		let e = this.animationTime, t = this.importedCameras.find((e) => e.id === this.activeCameraId)?.name || this.sceneMeta.camera_name || "";
		this.isPlaying = !1, this._updatePlayButton(), this._suppressViewChange = !0;
		try {
			let n = `/api/project/scene3d/file?t=${Date.now()}`;
			await this._loadBlenderUrl(n, String(this.sceneMeta.file_name || this.sceneMeta.file_path)), t && this.setActiveCamera(this._pickBestCameraId(String(t)), !1), e > 0 && this.setAnimationTime(He(e, this.animationDuration)), this.callbacks.onMessage?.("已刷新 GLB（保留时间与显示设置）");
		} catch (e) {
			this.callbacks.onMessage?.(`刷新 GLB 失败：${e instanceof Error ? e.message : String(e)}`);
		} finally {
			this._suppressViewChange = !1;
		}
	}
	_programLightingContext() {
		return {
			mode: this.programLightingMode,
			workspaceMode: this.mode,
			importedLightCount: this.importedLightCount,
			objectColorPreview: this.objectColorPreview
		};
	}
	_cameraMotionProbe() {
		return {
			animationDuration: this.animationDuration,
			animationTime: this.animationTime,
			probeA: this._probePosA,
			probeB: this._probePosB,
			setMixerTime: (e) => this._syncMixerTime(e)
		};
	}
	_trackNodeName(e) {
		return X(e);
	}
	_collectAnimatedNodeNames(e) {
		return Ae(e);
	}
	_isNodeInSceneGraph(e, t) {
		return L(e, t);
	}
	_collectImportedCameras(e) {
		return R(e);
	}
	_diagnoseMissingCameras(e) {
		return z(e);
	}
	_scoreCameraForAnimation(e) {
		return B(e, this.animatedNodeNames);
	}
	_pickBestCameraId(e) {
		return V(this.importedCameras, this.animatedNodeNames, e);
	}
	_computeClipDuration(e) {
		return Z(e);
	}
	_selectAnimationClips(e) {
		return Q(e);
	}
	_cameraMovesOverTime(e) {
		return !this.mixer || !e || this.animationDuration <= 0 ? !1 : U(e, this._cameraMotionProbe());
	}
	_resolveViewNode(e) {
		return W(e, this.blenderRoot, this.animatedNodeNames, this._cameraMotionProbe());
	}
	_updateAnimationHint() {
		if (!this.hintEl) return;
		let e = this.importedCameras.find((e) => e.id === this.activeCameraId), t = e?.object3d ? this._cameraMovesOverTime(e.object3d) : !1;
		this.hintEl.textContent = Pe({
			animationDuration: this.animationDuration,
			activeCameraName: e?.name || "",
			cameraMoves: t,
			formatTime: w
		});
	}
	_countImportedLights(e) {
		return F(e);
	}
	_shouldUseProgramIbl() {
		return K(this._programLightingContext());
	}
	_shouldUseProgramFill() {
		return q(this._programLightingContext());
	}
	_shouldUseProgramWeakFill() {
		return J(this._programLightingContext());
	}
	_getEnvMapIntensity() {
		return Te(this._programLightingContext());
	}
	_calibrateImportedLights(e) {
		I(e);
	}
	_setImportedLightsVisible(e) {
		G(this.blenderRoot, e);
	}
	_programLightingReason() {
		return Ee(this._programLightingContext());
	}
	setProgramLightingMode(e, { persist: t = !0, notify: n = !0 } = {}) {
		let r = we(e);
		this.programLightingMode = r, this.programLightingEl && (this.programLightingEl.value = r), t && (this.sceneMeta = {
			...this.sceneMeta || {},
			program_lighting: r
		}), this._applyProgramLighting(), this.blenderRoot && this._prepareImportedMaterials(this.blenderRoot), this.objectColorPreview && this._applyObjectColorPreview(!0), t && this._scheduleSceneSettingsSave(), n && this.callbacks.onMessage?.(`灯光设置：${this._programLightingReason()}`);
	}
	_updateLightStatusUi() {
		if (this.lightStatusEl) {
			if (this.mode !== "blender") {
				this.lightStatusEl.textContent = "—";
				return;
			}
			this.lightStatusEl.textContent = De(this._programLightingContext());
		}
	}
	_ensureBlenderEnvMap() {
		return this.blenderEnvMap ||= ke(i, this.pmremGenerator), this.blenderEnvMap;
	}
	_applyProgramLighting() {
		Oe(e, this._programLightingContext(), {
			scene: this.scene,
			programAmbient: this.programAmbient,
			programHemisphere: this.programHemisphere,
			builtinBackground: this.builtinBackground,
			blenderEnvMap: this.blenderEnvMap,
			ensureBlenderEnvMap: () => this._ensureBlenderEnvMap(),
			setImportedLightsVisible: (e) => this._setImportedLightsVisible(e)
		}), this._updateLightStatusUi();
	}
	_generateBlenderObjectColor(t) {
		return D(e, t);
	}
	_collectObjectColorKeys(e) {
		return Re(e, (e) => this._objectColorKey(e));
	}
	_objectColorKey(e) {
		return E(e, this.blenderRoot);
	}
	_cacheImportedMaterials(e) {
		Ie(e);
	}
	_restoreImportedMaterials(e) {
		Le(e);
	}
	_disposePreviewMaterials() {
		O(this.previewMaterials);
	}
	setObjectColorPreview(e, { persist: t = !0, notify: n = !1 } = {}) {
		this.objectColorPreview = !!e, this.objectColorsEl && (this.objectColorsEl.checked = this.objectColorPreview), t && (this.sceneMeta = {
			...this.sceneMeta || {},
			object_color_preview: this.objectColorPreview
		}), this._applyProgramLighting(), this._applyObjectColorPreview(this.objectColorPreview), !this.objectColorPreview && this.blenderRoot && this._prepareImportedMaterials(this.blenderRoot), this._applyWireframeMode(), t && this._scheduleSceneSettingsSave(), n && this.callbacks.onMessage?.(this.objectColorPreview ? "已启用对象随机色（不受灯光影响，便于区分）" : "已恢复 GLB 原始材质");
	}
	_applyObjectColorPreview(t) {
		this.blenderRoot && (ve(e, this.blenderRoot, this.blenderRoot, this.previewMaterials, t), !t && this.blenderRoot && this._prepareImportedMaterials(this.blenderRoot));
	}
	_prepareImportedMaterials(e) {
		this.objectColorPreview || Ce(e, this._getEnvMapIntensity());
	}
	async _loadBlenderUrl(t, n) {
		this.clearBlenderScene(), this.clearObjects();
		let i = await new r().loadAsync(t);
		this.blenderRoot = i.scene, this.scene.add(this.blenderRoot), this.importedLightCount = this._countImportedLights(i.scene), this._calibrateImportedLights(this.blenderRoot), this._applyProgramLighting(), this._prepareImportedMaterials(this.blenderRoot), this._cacheImportedMaterials(this.blenderRoot), this._applyObjectColorPreview(this.objectColorPreview), this.objectColorPreview && this._applyProgramLighting(), this._applyWireframeMode(), this.importedCameras = this._collectImportedCameras(i), this.animatedNodeNames = this._collectAnimatedNodeNames(i.animations);
		let a = ze(e, i.scene, i.animations || []);
		if (this.mixer = a.mixer, this.mixerActions = a.mixerActions, this.animationDuration = a.animationDuration, this.animationTime = 0, this.isPlaying = !1, this._syncMixerTime(0), this._populateCameraSelect(), this._renderOutliner(), this._updateTimelineUi(), (!this.followCamera || !this.importedCameras.length) && this._frameImportedScene(), this.sceneMeta.file_name = n || this.sceneMeta.file_name, this.importedCameras.length) {
			let e = this._pickBestCameraId(""), t = this.importedCameras.find((t) => t.id === e);
			t && (t.viewNode = this._resolveViewNode(t)), this.setActiveCamera(e, !1);
		}
		this.setFollowCamera(this.followCamera), this._updateAnimationHint();
		for (let e of Be({
			gltf: i,
			importedCameras: this.importedCameras,
			animationDuration: this.animationDuration,
			importedLightCount: this.importedLightCount,
			programLightingMode: this.programLightingMode
		})) this.callbacks.onMessage?.(e);
	}
	_programLightingModeLabel() {
		return Y(this.programLightingMode);
	}
	_frameImportedScene() {
		this.blenderRoot && H(e, this.blenderRoot, this.camera, this.orbit);
	}
	_populateCameraSelect() {
		Qe(this.cameraSelectEl, Ze(this.importedCameras), this.activeCameraId);
	}
	setActiveCamera(e, t = !0) {
		let n = this.importedCameras.find((t) => t.id === e);
		n && (this.activeCameraId = e, this.cameraSelectEl.value = e, n.viewNode = this._resolveViewNode(n), this._renderOutliner(), t && this.callbacks.onMessage?.(`已切换相机：${n.name}`), this.followCamera && this._applyFollowCamera(), this._updateAnimationHint(), t && this._notifyViewChange());
	}
	setFollowCamera(e, { persist: t = !0 } = {}) {
		this.followCamera = !!e, this.followCameraEl.checked = this.followCamera, this.orbit.enabled = !this.followCamera, this.followCamera && this._applyFollowCamera(), t && (this.sceneMeta = {
			...this.sceneMeta || {},
			follow_camera: this.followCamera
		}, this._scheduleSceneSettingsSave(), this._notifyViewChange());
	}
	_notifyViewChange() {
		this._suppressViewChange || this.callbacks.onViewChange?.();
	}
	setMode(e) {
		this.mode = e, $e(this.rootEl, e), et(e, {
			grid: this.grid,
			axes: this.axes,
			defaultAmbient: this.defaultAmbient,
			defaultSun: this.defaultSun,
			programAmbient: this.programAmbient,
			programHemisphere: this.programHemisphere,
			scene: this.scene,
			builtinBackground: this.builtinBackground
		}), e === "blender" ? (this._applyProgramLighting(), this.transform.detach(), this.selectObject(null)) : this._updateLightStatusUi();
	}
	exportSceneData() {
		if (this.mode === "blender") {
			let e = this.importedCameras.find((e) => e.id === this.activeCameraId);
			return ue({
				sceneMeta: this.sceneMeta,
				activeCameraName: e?.name || String(this.sceneMeta.camera_name || ""),
				followCamera: this.followCamera,
				animationTime: this.animationTime,
				programLightingMode: this.programLightingMode,
				importedLightCount: this.importedLightCount,
				objectColorPreview: this.objectColorPreview,
				wireframeMode: this.wireframeMode
			});
		}
		return le(this.objects.entries(), this.wireframeMode, this.objectColorPreview);
	}
	clearBlenderScene() {
		ut(this.mixer), Object.assign(this, lt()), this._clearWireframeOverlays(), this.blenderRoot &&= (this._restoreImportedMaterials(this.blenderRoot), this._disposePreviewMaterials(), this.scene.remove(this.blenderRoot), N(this.blenderRoot), null), this._populateCameraSelect(), this._updateTimelineUi();
	}
	clearObjects() {
		for (let e of this.objects.values()) this.scene.remove(e), P(e);
		this.objects.clear(), this.transform.detach(), this.selectedId = null;
	}
	_addMeshFromSpec(t) {
		let n = f(e, t);
		return this.objects.set(t.id, n), this.scene.add(n), n;
	}
	addObject(e) {
		let t = d(e, this.objects.size, "");
		t.color = `#${this._generateBlenderObjectColor(t.name).getHexString()}`, this._addMeshFromSpec(t), this.selectObject(t.id), this._renderOutliner(), this._applyWireframeMode();
	}
	selectObject(e) {
		this.selectedId = e;
		let t = e ? this.objects.get(e) : null;
		nt(this.mode, t) ? this.transform.attach(t) : this.transform.detach(), this._renderOutliner(), this._updateTransformInputs();
	}
	deleteSelected() {
		if (!$(this.selectedId)) return;
		let e = this.objects.get(this.selectedId);
		e && (this.transform.detach(), this.scene.remove(e), P(e), this.objects.delete(this.selectedId), this.selectedId = null, this._renderOutliner(), this._updateTransformInputs());
	}
	focusSelected() {
		let e = rt(this.selectedId ? this.objects.get(this.selectedId) : null, this.orbit);
		this.orbit.target.copy(e), this.orbit.update();
	}
	resetView() {
		if (this.mode === "blender") {
			this._frameImportedScene();
			return;
		}
		it(this.camera, this.orbit);
	}
	getCameraState() {
		return _(this.camera, this.orbit);
	}
	getViewState() {
		let t = this.importedCameras.find((e) => e.id === this.activeCameraId) || null;
		return v(e, {
			camera: this.camera,
			orbit: this.orbit,
			followCamera: this.followCamera,
			activeCamera: t ? {
				id: t.id,
				name: t.name
			} : null,
			animationTime: this.animationTime
		});
	}
	loadShotCamera(t) {
		if (!t?.position) {
			this.callbacks.onMessage?.("当前镜头没有保存的 3D 相机数据");
			return;
		}
		this.setFollowCamera(!1), ee(e, this.camera, this.orbit, t);
	}
	_fovToFocalLength(e) {
		return m(e);
	}
	_syncSelectedFromMesh() {
		this._updateTransformInputs();
	}
	_applyTransformInputs(t) {
		let n = this.selectedId ? this.objects.get(this.selectedId) : null;
		n && Ke(e, n, this.transformInputs, t, this.transform);
	}
	_updateTransformInputs() {
		qe(e, this.selectedId ? this.objects.get(this.selectedId) : null, this.transformInputs);
	}
	_renderOutliner() {
		Xe(this.outlinerEl, Ye(this.mode, this.objects, this.importedCameras, this.activeCameraId, this.selectedId));
	}
	refreshBoardPreview() {
		let e = this.callbacks.getBoardPreviewUrl?.() || "", t = this.callbacks.getBoardLabel?.() || "—";
		this.boardLabelEl && (this.boardLabelEl.textContent = t), !(!this.boardPreviewImg || !this.boardPreviewEmpty) && (e ? (this.boardPreviewImg.src = e, this.boardPreviewImg.hidden = !1, this.boardPreviewEmpty.hidden = !0) : (this.boardPreviewImg.hidden = !0, this.boardPreviewEmpty.hidden = !1));
	}
	_updateFileName() {
		this.fileNameEl.textContent = Ue(this.mode, this.sceneMeta);
	}
	setBlendFilePath(e) {
		this.sceneMeta = {
			...this.sceneMeta || {},
			blend_file_path: e || "scene3d/scene.blend"
		}, this._updateFileName();
	}
	_syncMixerTime(e) {
		!this.mixer || !this.mixerActions.length || (this.animationTime = Me(this.mixerActions, this.mixer, e), this.blenderRoot?.updateMatrixWorld(!0));
	}
	setAnimationTime(e) {
		let t = je(e, this.animationDuration || 0);
		this._syncMixerTime(t), this._updateTimelineUi(), this.followCamera && this._applyFollowCamera(), this._notifyViewChange();
	}
	toggleAnimationPlayback() {
		if (this.mode !== "blender" || !this.mixer) {
			this.callbacks.onMessage?.("请先导入带相机动画的 GLB");
			return;
		}
		!this.isPlaying && this.animationDuration > 0 && this.animationTime >= this.animationDuration - .001 && this.setAnimationTime(0), this.isPlaying = !this.isPlaying, this._updatePlayButton();
	}
	pauseAnimation() {
		this.isPlaying = !1, this._updatePlayButton();
	}
	goToAnimationStart() {
		this.isPlaying = !1, this.setAnimationTime(0), this._updatePlayButton();
	}
	stepAnimation(e) {
		this.mode !== "blender" || !this.mixer || (this.isPlaying && (this.isPlaying = !1, this._updatePlayButton()), this.setAnimationTime(this.animationTime + Number(e || 0)));
	}
	captureFrameDataUrl() {
		let t = () => {
			this.followCamera && this.mode === "blender" && this._applyFollowCamera();
		};
		return p(e, this.renderer, this.camera, this.scene, {
			getProjectCanvasSize: h,
			prepareExport: t,
			finishDisplay: () => {
				t(), this.renderer.render(this.scene, this.camera);
			}
		});
	}
	getAnimationState() {
		return {
			time: this.animationTime,
			duration: this.animationDuration,
			camera_name: this.importedCameras.find((e) => e.id === this.activeCameraId)?.name || ""
		};
	}
	_updatePlayButton() {
		this.playPauseBtn && (this.playPauseBtn.textContent = this.isPlaying ? "⏸ 暂停" : "▶ 播放");
	}
	_updateTimelineUi() {
		let e = Ne(this.animationTime, this.animationDuration, w);
		this.timeSliderEl.max = String(e.max), this.timeSliderEl.value = String(e.value), this.timeSliderEl.disabled = e.disabled, this.timeDisplayEl.textContent = e.displayText;
	}
	_applyFollowCamera() {
		let e = this.importedCameras.find((e) => e.id === this.activeCameraId);
		y(this.camera, this.orbit, e, {
			position: this._followPos,
			quaternion: this._followQuat,
			scale: this._followScale
		});
	}
	_projectAspect() {
		return g();
	}
	_resize() {
		let e = this.formatFrameEl || this.viewportEl, t = Math.max(1, Math.floor(e.clientWidth)), n = Math.max(1, Math.floor(e.clientHeight));
		!t || !n || (this.camera.aspect = this._projectAspect(), this.camera.updateProjectionMatrix(), this.renderer.setSize(t, n, !1));
	}
	_animate() {
		this.animationId = requestAnimationFrame(() => this._animate());
		let e = this.clock.getDelta();
		if (this.mode === "blender" && this.mixer && this.isPlaying) {
			let t = this.animationDuration || 0, { nextTime: n, reachedEnd: r } = Fe(this.animationTime, e, t);
			r && (this.isPlaying = !1, this._updatePlayButton()), this._syncMixerTime(n), this._updateTimelineUi();
		}
		tt(this.mode, this.followCamera) ? this.orbit.update() : this._applyFollowCamera(), this.renderer.render(this.scene, this.camera);
	}
	dispose() {
		this._disposed || (this._disposed = !0, this.animationId && cancelAnimationFrame(this.animationId), this.animationId = null, this._sceneSettingsSaveTimer != null && (window.clearTimeout(this._sceneSettingsSaveTimer), this._sceneSettingsSaveTimer = null), this._resizeObserver?.disconnect(), this._keydownHandler && window.removeEventListener("keydown", this._keydownHandler), this._pointerdownHandler && this.renderer?.domElement && this.renderer.domElement.removeEventListener("pointerdown", this._pointerdownHandler), this.clearBlenderScene(), this.clearObjects(), this.transform?.dispose(), this.orbit?.dispose(), this.blenderEnvMap?.dispose(), this.blenderEnvMap = null, this.pmremGenerator?.dispose(), this.pmremGenerator = null, this._clearWireframeOverlays(), this.renderer && (this.renderer.dispose(), this.renderer.domElement.parentNode && this.renderer.domElement.parentNode.removeChild(this.renderer.domElement)));
	}
};
//#endregion
export { a as PRIMITIVE_TYPES, dt as Scene3DEditor, Je as WIREFRAME_MODE_LABELS, Fe as advancePlaybackTime, y as applyFollowCameraToEditor, Ke as applyTransformFromInputs, ct as applyWorkspaceKeyboardAction, $e as applyWorkspaceModeUi, Oe as applyWorkspaceProgramLighting, et as applyWorkspaceSceneModeFlags, Pe as buildAnimationHint, Ze as buildCameraSelectOptions, Be as buildGlbLoadNotifications, De as buildLightStatusText, Ye as buildOutlinerEntries, Ne as buildTimelineUiState, Ie as cacheImportedMaterialsOnRoot, I as calibrateImportedLights, U as cameraMovesOverTime, $ as canDeleteWorkspaceObject, p as captureRendererPng, je as clampAnimationTime, Ae as collectAnimatedNodeNames, R as collectImportedCameras, Re as collectMeshObjectColorKeys, l as colorFrom, Z as computeClipDuration, F as countImportedLights, ke as createBlenderEnvMap, lt as createEmptyBlenderPlaybackState, f as createMeshFromSpec, ze as createWorkspaceAnimationMixer, d as defaultAddObjectSpec, u as defaultSceneData, z as diagnoseMissingCameras, N as disposeObject3DRoot, P as disposePrimitiveMesh, c as eulerFrom, ue as exportBlenderSceneData, le as exportBuiltinSceneData, ce as exportBuiltinSceneObjects, v as exportViewState, Ge as filterBuiltinObjectSpecs, Ue as formatWorkspaceFileName, w as formatWorkspaceTime, m as fovToFocalLength, H as frameImportedScene, _ as getCameraStateFromEditor, Te as getEnvMapIntensity, g as getProjectCanvasAspect, h as getProjectCanvasSize, We as getWireframeRoots, rt as getWorkspaceFocusTarget, oe as initWorkspaceEditorThree, L as isNodeInSceneGraph, ee as loadShotCameraIntoEditor, o as makeId, we as normalizeProgramLightingMode, de as normalizeWorkspaceSceneMeta, V as pickBestCameraId, Qe as populateCameraSelectDom, Ce as prepareImportedMaterials, Y as programLightingModeLabel, Ee as programLightingReason, Xe as renderOutlinerDom, it as resetBuiltinCameraView, ot as resolveBlenderKeyboardAction, st as resolveBuiltinKeyboardAction, Ve as resolveInitialAnimationTime, He as resolveReloadAnimationTime, W as resolveViewNode, Le as restoreImportedMaterialsOnRoot, B as scoreCameraForAnimation, Q as selectAnimationClips, G as setImportedLightsVisible, nt as shouldAttachTransformToSelection, at as shouldIgnoreWorkspaceKeyboard, tt as shouldUseOrbitControls, q as shouldUseProgramFill, K as shouldUseProgramIbl, J as shouldUseProgramWeakFill, ut as stopWorkspaceMixer, Me as syncMixerActionsTime, qe as syncTransformInputsFromMesh, X as trackNodeName, s as vec3From };
