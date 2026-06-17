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
function o(e, t) {
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
function s(e, t, n, r, i = {}) {
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
function c(e, t = 36) {
	return t / (2 * Math.tan(e * Math.PI / 360));
}
function l() {
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
function u() {
	let e = l();
	return e.width / Math.max(1, e.height);
}
function d(e, t) {
	let n = t.target.clone();
	return {
		position: e.position.toArray(),
		target: n.toArray(),
		rotation: e.rotation.toArray().slice(0, 3),
		fov: e.fov,
		focal_length: Math.round(c(Number(e.fov) || 50))
	};
}
function f(e, t) {
	let n = d(t.camera, t.orbit), r = t.camera.getWorldDirection(new e.Vector3()), i = Math.max(.001, t.camera.position.distanceTo(t.orbit.target)) || 1, a = t.camera.position.clone().add(r.multiplyScalar(i)), o = !!(t.followCamera && t.activeCamera);
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
function p(e, t, n, r, i = [
	6,
	4,
	8
], a = [
	0,
	.5,
	0
]) {
	if (!r?.position) return !1;
	let o = h(r.position, i);
	if (t.position.set(o[0], o[1], o[2]), r.target) {
		let e = h(r.target, a);
		n.target.set(e[0], e[1], e[2]);
	} else if (r.rotation) {
		let [i, a, o] = h(r.rotation);
		t.rotation.set(i, a, o), n.target.copy(t.position.clone().add(t.getWorldDirection(new e.Vector3())));
	}
	return r.fov && (t.fov = Number(r.fov) || 50, t.updateProjectionMatrix()), n.update(), !0;
}
function m(e, t, n, r) {
	if (!n?.object3d) return !1;
	let i = n.viewNode || n.object3d;
	i.updateWorldMatrix(!0, !1), i.matrixWorld.decompose(r.position, r.quaternion, r.scale), e.position.copy(r.position), e.quaternion.copy(r.quaternion);
	let a = n.object3d.isCamera ? n.object3d : null;
	return a?.isPerspectiveCamera && (e.fov = a.fov, e.near = Math.max(.001, a.near), e.far = Math.max(e.near + 1, a.far), e.updateProjectionMatrix()), t.enabled = !1, !0;
}
function h(e, t = [
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
var g = 1711393, _ = [
	6,
	4,
	8
], v = [
	0,
	.5,
	0
];
function y(e, t, n = {}) {
	let r = new e.WebGLRenderer({
		antialias: !0,
		alpha: !1,
		preserveDrawingBuffer: !0
	}), i = n.maxPixelRatio ?? 2;
	return r.setPixelRatio(Math.min(window.devicePixelRatio, i)), r.outputColorSpace = e.SRGBColorSpace, r.toneMapping = e.AgXToneMapping ?? e.ACESFilmicToneMapping, r.toneMappingExposure = 1, r.shadowMap.enabled = !0, r.shadowMap.type = e.PCFSoftShadowMap, t.appendChild(r.domElement), r;
}
function b(e) {
	let t = new e.Scene();
	t.background = new e.Color(g);
	let n = new e.PerspectiveCamera(50, 1, .01, 1e3);
	n.position.set(..._);
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
		builtinBackground: new e.Color(g),
		pmremGenerator: null
	};
}
function x(e, t) {
	let n = new e.PMREMGenerator(t);
	return n.compileEquirectangularShader(), n;
}
//#endregion
//#region src/scene3d/workspace/workspaceControls.ts
function S(e, t, n, r = {}) {
	let i = new e(t, n);
	i.enableDamping = !0;
	let [a, o, s] = r.target ?? v;
	return i.target.set(a, o, s), r.onChange && i.addEventListener("change", r.onChange), i;
}
function C(e, t, n, r, i = {}) {
	let a = new e(t, n);
	return a.setMode(i.mode ?? "translate"), a.addEventListener("dragging-changed", (e) => {
		i.onDraggingChanged?.(!!e.value);
	}), a.addEventListener("objectChange", () => {
		i.onObjectChange?.();
	}), r.add(a), a;
}
//#endregion
//#region src/scene3d/workspace/workspaceBridge.ts
function w(e, t, n, r) {
	let i = y(e, r.mountEl), a = b(e), o = x(e, i), s = S(t, a.camera, i.domElement, { onChange: r.onOrbitChange }), c = C(n, a.camera, i.domElement, a.scene, {
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
function T(e) {
	let t = Math.max(0, Number(e) || 0), n = Math.floor(t / 60), r = (t % 60).toFixed(1).padStart(n > 0 ? 4 : 1, "0");
	return n > 0 ? `${n}:${r}` : `${r}s`;
}
function E(e, t) {
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
function D(e) {
	let t = [];
	for (let [n, r] of e) t.push(E(n, r));
	return t;
}
function O(e, t, n) {
	return {
		source: "builtin",
		objects: D(e),
		wireframe_mode: t,
		object_color_preview: n
	};
}
function k(e) {
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
function A(e) {
	return e && typeof e == "object" ? { ...e } : {};
}
//#endregion
//#region src/scene3d/workspace/workspaceDispose.ts
function j(e) {
	if (!e || typeof e != "object") return;
	let t = e;
	try {
		t.dispose?.();
	} catch {}
}
function M(e) {
	let t = Array.isArray(e) ? e : [e];
	for (let e of t) {
		if (!e || typeof e != "object") continue;
		let t = e;
		for (let e of Object.keys(t)) j(t[e]);
		try {
			t.dispose?.();
		} catch {}
	}
}
function N(e) {
	try {
		e?.dispose?.();
	} catch {}
}
function P(e) {
	try {
		N(e.geometry), M(e.material);
	} catch {}
}
function F(e) {
	e?.traverse?.((e) => {
		let t = e.userData?.scene3dOriginalMaterial;
		if (t) {
			M(t);
			return;
		}
		P(e);
	});
}
function I(e) {
	e && (N(e.geometry), M(e.material));
}
//#endregion
export { e as PRIMITIVE_TYPES, m as applyFollowCameraToEditor, s as captureRendererPng, i as colorFrom, o as createMeshFromSpec, a as defaultSceneData, F as disposeObject3DRoot, I as disposePrimitiveMesh, r as eulerFrom, k as exportBlenderSceneData, O as exportBuiltinSceneData, D as exportBuiltinSceneObjects, f as exportViewState, T as formatWorkspaceTime, c as fovToFocalLength, d as getCameraStateFromEditor, u as getProjectCanvasAspect, l as getProjectCanvasSize, w as initWorkspaceEditorThree, p as loadShotCameraIntoEditor, t as makeId, A as normalizeWorkspaceSceneMeta, n as vec3From };
