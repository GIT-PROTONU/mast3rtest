import { app } from "/scripts/app.js";

const THREE_VER = "0.160.0";
let threeBundle = null;

async function loadThree() {
    if (threeBundle) return threeBundle;
    const base = `https://esm.sh/three@${THREE_VER}`;
    const deps = `?deps=three@${THREE_VER}`;
    const [THREE, GLTFLoaderMod, OrbitMod, PLockMod] = await Promise.all([
        import(`${base}`),
        import(`${base}/examples/jsm/loaders/GLTFLoader.js${deps}`),
        import(`${base}/examples/jsm/controls/OrbitControls.js${deps}`),
        import(`${base}/examples/jsm/controls/PointerLockControls.js${deps}`),
    ]);
    threeBundle = {
        THREE,
        GLTFLoader: GLTFLoaderMod.GLTFLoader,
        OrbitControls: OrbitMod.OrbitControls,
        PointerLockControls: PLockMod.PointerLockControls,
    };
    return threeBundle;
}

function mkBtn(label, title) {
    const b = document.createElement("button");
    b.textContent = label;
    b.title = title || label;
    b.style.fontSize = "11px";
    b.style.padding = "3px 7px";
    b.style.border = "1px solid #555";
    b.style.background = "#222";
    b.style.color = "#eee";
    b.style.cursor = "pointer";
    b.style.borderRadius = "3px";
    b.onmouseenter = () => (b.style.background = b._active ? "#3a5" : "#333");
    b.onmouseleave = () => (b.style.background = b._active ? "#3a5" : "#222");
    return b;
}

function activate(b, on) {
    b._active = on;
    b.style.background = on ? "#3a5" : "#222";
    b.style.borderColor = on ? "#7d7" : "#555";
}

function mkSlider(label, min, max, step, value, title) {
    const wrap = document.createElement("label");
    wrap.style.display = "inline-flex";
    wrap.style.alignItems = "center";
    wrap.style.gap = "4px";
    wrap.style.fontSize = "10px";
    wrap.style.color = "#ccc";
    wrap.style.padding = "0 4px";
    wrap.title = title || label;
    const txt = document.createElement("span");
    txt.textContent = label;
    txt.style.minWidth = "4ch";
    const s = document.createElement("input");
    s.type = "range";
    s.min = min; s.max = max; s.step = step; s.value = value;
    s.style.width = "90px";
    s.style.height = "12px";
    const val = document.createElement("span");
    val.textContent = (+value).toFixed(2);
    val.style.minWidth = "3ch";
    val.style.color = "#9fd";
    val.style.fontVariantNumeric = "tabular-nums";
    s.addEventListener("input", () => { val.textContent = (+s.value).toFixed(2); });
    wrap.append(txt, s, val);
    return { wrap, slider: s, value: val };
}

function makeUI() {
    const wrap = document.createElement("div");
    wrap.style.width = "100%";
    wrap.style.height = "100%";
    wrap.style.minHeight = "380px";
    wrap.style.background = "#111";
    wrap.style.position = "relative";
    wrap.style.border = "1px solid #333";
    wrap.style.borderRadius = "4px";
    wrap.style.overflow = "hidden";
    wrap.style.fontFamily = "monospace";

    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    canvas.style.outline = "none";
    canvas.tabIndex = 0;
    wrap.appendChild(canvas);

    const toolbar = document.createElement("div");
    toolbar.style.position = "absolute";
    toolbar.style.left = "6px";
    toolbar.style.top = "6px";
    toolbar.style.right = "6px";
    toolbar.style.display = "flex";
    toolbar.style.flexWrap = "wrap";
    toolbar.style.gap = "4px";
    toolbar.style.alignItems = "center";
    toolbar.style.zIndex = "2";
    toolbar.style.background = "rgba(0,0,0,0.45)";
    toolbar.style.padding = "4px 6px";
    toolbar.style.borderRadius = "4px";
    toolbar.style.pointerEvents = "auto";
    wrap.appendChild(toolbar);

    const status = document.createElement("div");
    status.style.position = "absolute";
    status.style.right = "8px";
    status.style.bottom = "26px";
    status.style.fontSize = "10px";
    status.style.color = "#9fd";
    status.style.background = "rgba(0,0,0,0.5)";
    status.style.padding = "2px 6px";
    status.style.borderRadius = "3px";
    status.style.pointerEvents = "none";
    status.textContent = "no model";
    wrap.appendChild(status);

    const hint = document.createElement("div");
    hint.style.position = "absolute";
    hint.style.left = "8px";
    hint.style.bottom = "6px";
    hint.style.fontSize = "10px";
    hint.style.color = "#bbb";
    hint.style.background = "rgba(0,0,0,0.5)";
    hint.style.padding = "2px 6px";
    hint.style.borderRadius = "3px";
    hint.style.pointerEvents = "none";
    hint.textContent = "Orbit: drag = rotate, wheel = zoom, right-drag = pan";
    wrap.appendChild(hint);

    function sep() {
        const s = document.createElement("span");
        s.style.borderLeft = "1px solid #444";
        s.style.height = "18px";
        s.style.margin = "0 4px";
        return s;
    }

    const btnOrbit = mkBtn("Orbit");
    const btnWASD = mkBtn("WASD");
    const btnSolid = mkBtn("Solid");
    const btnWire = mkBtn("Wireframe");
    const btnPoints = mkBtn("Points");
    const btnUnlit = mkBtn("Unlit", "Show baked colors directly (recommended for photogrammetry)");
    const btnLit = mkBtn("Lit", "Use PBR shading with scene lights");
    const sBright = mkSlider("Bright", 0.1, 3.0, 0.05, 1.2, "Brightness (tone mapping exposure)");
    const sPoint = mkSlider("Pt sz", 0.001, 0.02, 0.001, 0.004, "Point size in Points mode");
    const sFog = mkSlider("Far", 0.5, 5.0, 0.1, 5.0, "Far clip multiplier (lower = closer plane)");
    const btnBgDark = mkBtn("BG·D", "Dark background");
    const btnBgMid = mkBtn("BG·M", "Mid grey background");
    const btnBgLight = mkBtn("BG·L", "Light background");
    const btnGrid = mkBtn("Grid", "Toggle the ground grid");
    const btnFs = mkBtn("Fullscreen", "Fill the screen (press ESC to exit)");
    btnFs.style.background = "#246";
    btnFs.style.borderColor = "#58a";
    const btnReset = mkBtn("Reset", "Frame the model in view");
    const btnDownload = mkBtn("Download GLB", "Save scene to your computer");
    btnDownload.style.background = "#264";
    btnDownload.style.borderColor = "#5a8";

    toolbar.append(
        btnOrbit, btnWASD, sep(),
        btnSolid, btnWire, btnPoints, sep(),
        btnUnlit, btnLit, sep(),
        sBright.wrap, sPoint.wrap, sFog.wrap, sep(),
        btnBgDark, btnBgMid, btnBgLight, btnGrid, sep(),
        btnReset, btnFs, btnDownload
    );

    return {
        wrap, canvas, status, hint, toolbar,
        btnOrbit, btnWASD,
        btnSolid, btnWire, btnPoints,
        btnUnlit, btnLit,
        sBright, sPoint, sFog,
        btnBgDark, btnBgMid, btnBgLight, btnGrid,
        btnReset, btnFs, btnDownload,
    };
}

function setupScene(THREE, canvas) {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x111111);

    const camera = new THREE.PerspectiveCamera(60, 1, 0.001, 1000);
    camera.position.set(0, 0, 2);

    const grid = new THREE.GridHelper(10, 20, 0x444444, 0x222222);
    grid.position.y = -0.001;
    scene.add(grid);

    const hemi = new THREE.HemisphereLight(0xffffff, 0x444466, 1.2);
    scene.add(hemi);
    const dir1 = new THREE.DirectionalLight(0xffffff, 1.0);
    dir1.position.set(2, 3, 2);
    scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0xffffff, 0.4);
    dir2.position.set(-2, 1, -1.5);
    scene.add(dir2);

    return { renderer, scene, camera, grid };
}

function frameModel(THREE, model, camera, orbit, farMultiplier = 5.0) {
    const box = new THREE.Box3().setFromObject(model);
    if (box.isEmpty()) return null;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) * 0.5;
    const fov = (camera.fov * Math.PI) / 180;
    const dist = (radius / Math.sin(fov / 2)) * 1.4;
    const dir = new THREE.Vector3(1, 0.6, 1).normalize();
    camera.position.copy(center.clone().add(dir.multiplyScalar(dist)));
    camera.near = Math.max(0.001, radius / 200);
    camera.far = dist * farMultiplier;
    camera.updateProjectionMatrix();
    camera.lookAt(center);
    if (orbit) {
        orbit.target.copy(center);
        orbit.update();
    }
    return { center, radius, dist };
}

function asBasicMaterial(THREE, srcMat, geometry) {
    const hasVertexColor = !!(geometry && geometry.attributes && geometry.attributes.color);
    const opts = {
        color: srcMat.color ? srcMat.color.clone() : new THREE.Color(0xffffff),
        map: srcMat.map || null,
        vertexColors: srcMat.vertexColors || hasVertexColor,
        side: THREE.DoubleSide,
        transparent: false,
        opacity: 1,
        toneMapped: true,
    };
    return new THREE.MeshBasicMaterial(opts);
}

function applyMaterialMode(THREE, root, mode) {
    root.traverse((o) => {
        if (!o.isMesh) return;
        if (!o.userData._origMat) {
            o.userData._origMat = o.material;
        }
        const orig = o.userData._origMat;
        if (mode === "unlit") {
            const origArr = Array.isArray(orig) ? orig : [orig];
            if (!o.userData._basicMat) {
                o.userData._basicMat = origArr.map((m) =>
                    m ? asBasicMaterial(THREE, m, o.geometry) : new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide })
                );
            }
            o.material = o.userData._basicMat.length === 1 ? o.userData._basicMat[0] : o.userData._basicMat;
        } else {
            o.material = orig;
            const arr = Array.isArray(o.material) ? o.material : [o.material];
            for (const m of arr) {
                if (!m) continue;
                if (m.isMeshStandardMaterial || m.isMeshPhysicalMaterial) {
                    m.metalness = 0;
                    m.roughness = 1;
                }
                m.side = THREE.DoubleSide;
                m.needsUpdate = true;
            }
        }
    });
}

function applyRenderMode(THREE, root, mode) {
    root.traverse((o) => {
        if (!o.isMesh) return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        for (const m of mats) {
            if (!m) continue;
            m.wireframe = mode === "wireframe";
            m.needsUpdate = true;
        }
        o.visible = mode !== "points";
    });
    if (root._mastPoints) root._mastPoints.visible = mode === "points";
}

function buildPointsClone(THREE, root) {
    if (root._mastPoints) return root._mastPoints;
    const positions = [];
    const colors = [];
    const tmp = new THREE.Vector3();
    const tmpColor = new THREE.Color();
    root.traverse((o) => {
        if (!o.isMesh || !o.geometry) return;
        const g = o.geometry;
        const pos = g.attributes.position;
        const col = g.attributes.color;
        if (!pos) return;
        const matArr = Array.isArray(o.material) ? o.material : [o.material];
        const baseColor = (matArr.find((m) => m && m.color) || {}).color;
        o.updateWorldMatrix(true, false);
        for (let i = 0; i < pos.count; i++) {
            tmp.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
            positions.push(tmp.x, tmp.y, tmp.z);
            if (col) {
                colors.push(col.getX(i), col.getY(i), col.getZ(i));
            } else if (baseColor) {
                colors.push(baseColor.r, baseColor.g, baseColor.b);
            } else {
                colors.push(1, 1, 1);
            }
        }
    });
    if (positions.length === 0) return null;
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geom.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    const pMat = new THREE.PointsMaterial({
        size: 0.004,
        vertexColors: true,
        sizeAttenuation: true,
        toneMapped: true,
    });
    const pts = new THREE.Points(geom, pMat);
    pts.visible = false;
    root.parent.add(pts);
    root._mastPoints = pts;
    return pts;
}

app.registerExtension({
    name: "mast3r.viewer3d",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "Mast3rViewer3D") return;

        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const ret = onCreated?.apply(this, arguments);
            if (this._mast3rViewer3d) return ret;

            const ui = makeUI();
            this._mast3rViewer3d = ui;

            this.addDOMWidget("viewer3d", "div", ui.wrap, {
                serialize: false,
                hideOnZoom: false,
            });
            if (this.size[0] < 1180) this.size[0] = 1180;
            if (this.size[1] < 680) this.size[1] = 680;

            const state = {
                THREE: null,
                renderer: null,
                scene: null,
                camera: null,
                orbit: null,
                plock: null,
                mode: "orbit",
                renderMode: "solid",
                materialMode: "unlit",
                bgMode: "dark",
                model: null,
                bounds: null,
                rafId: 0,
                keys: new Set(),
                speed: 1,
                farMul: 5.0,
            };
            this._mast3rViewerState = state;

            const BG_COLORS = { dark: 0x111111, mid: 0x666666, light: 0xdddddd };

            loadThree()
                .then(({ THREE, OrbitControls, PointerLockControls }) => {
                    state.THREE = THREE;
                    const { renderer, scene, camera, grid } = setupScene(THREE, ui.canvas);
                    state.renderer = renderer;
                    state.scene = scene;
                    state.camera = camera;
                    state.grid = grid;
                    state.orbit = new OrbitControls(camera, ui.canvas);
                    state.orbit.enableDamping = true;
                    state.orbit.dampingFactor = 0.08;
                    state.orbit.minDistance = 0.0005;
                    state.orbit.maxDistance = 5000;
                    state.plock = new PointerLockControls(camera, ui.canvas);
                    scene.add(state.plock.getObject());

                    const resize = () => {
                        const r = ui.canvas.getBoundingClientRect();
                        const w = Math.max(2, Math.floor(r.width));
                        const h = Math.max(2, Math.floor(r.height));
                        renderer.setSize(w, h, false);
                        camera.aspect = w / h;
                        camera.updateProjectionMatrix();
                    };
                    new ResizeObserver(resize).observe(ui.wrap);
                    resize();

                    const tmpVel = new THREE.Vector3();
                    const tmpFwd = new THREE.Vector3();
                    const tmpRight = new THREE.Vector3();
                    let prev = performance.now();
                    const tick = () => {
                        const now = performance.now();
                        const dt = Math.min(0.1, (now - prev) / 1000);
                        prev = now;

                        if (state.mode === "wasd" && state.plock.isLocked) {
                            const k = state.keys;
                            tmpVel.set(0, 0, 0);
                            camera.getWorldDirection(tmpFwd);
                            tmpFwd.y = 0;
                            tmpFwd.normalize();
                            tmpRight.crossVectors(tmpFwd, camera.up).normalize();
                            if (k.has("w")) tmpVel.add(tmpFwd);
                            if (k.has("s")) tmpVel.sub(tmpFwd);
                            if (k.has("d")) tmpVel.add(tmpRight);
                            if (k.has("a")) tmpVel.sub(tmpRight);
                            if (k.has(" ")) tmpVel.y += 1;
                            if (k.has("shift")) tmpVel.y -= 1;
                            const boost = k.has("control") ? 3 : 1;
                            if (tmpVel.lengthSq() > 0) {
                                tmpVel.normalize().multiplyScalar(state.speed * boost * dt);
                                camera.position.add(tmpVel);
                            }
                        } else if (state.orbit.enabled) {
                            state.orbit.update();
                        }
                        renderer.render(scene, camera);
                        state.rafId = requestAnimationFrame(tick);
                    };
                    state.rafId = requestAnimationFrame(tick);

                    const onKeyDown = (e) => {
                        const key = e.key.toLowerCase() === "shift" ? "shift" : e.key.toLowerCase();
                        state.keys.add(key);
                    };
                    const onKeyUp = (e) => {
                        const key = e.key.toLowerCase() === "shift" ? "shift" : e.key.toLowerCase();
                        state.keys.delete(key);
                    };
                    window.addEventListener("keydown", onKeyDown);
                    window.addEventListener("keyup", onKeyUp);
                    state._dispose = () => {
                        window.removeEventListener("keydown", onKeyDown);
                        window.removeEventListener("keyup", onKeyUp);
                        cancelAnimationFrame(state.rafId);
                        state._disposeFs?.();
                    };

                    function setNavMode(m) {
                        state.mode = m;
                        if (m === "orbit") {
                            state.orbit.enabled = true;
                            if (state.plock.isLocked) state.plock.unlock();
                            ui.hint.textContent = "Orbit: drag = rotate, wheel = zoom, right-drag = pan";
                            activate(ui.btnOrbit, true);
                            activate(ui.btnWASD, false);
                        } else {
                            state.orbit.enabled = false;
                            ui.hint.textContent =
                                "WASD: click canvas to lock pointer • WASD = move • Space/Shift = up/down • Ctrl = sprint • ESC = release";
                            activate(ui.btnOrbit, false);
                            activate(ui.btnWASD, true);
                            if (state.bounds) state.speed = Math.max(0.05, state.bounds.radius * 0.6);
                        }
                    }

                    function setRenderMode(m) {
                        state.renderMode = m;
                        if (state.model) {
                            if (m === "points") buildPointsClone(THREE, state.model);
                            applyRenderMode(THREE, state.model, m);
                        }
                        activate(ui.btnSolid, m === "solid");
                        activate(ui.btnWire, m === "wireframe");
                        activate(ui.btnPoints, m === "points");
                    }

                    function setMaterialMode(m) {
                        state.materialMode = m;
                        if (state.model) {
                            applyMaterialMode(THREE, state.model, m);
                            applyRenderMode(THREE, state.model, state.renderMode);
                        }
                        activate(ui.btnUnlit, m === "unlit");
                        activate(ui.btnLit, m === "lit");
                    }

                    function setBg(m) {
                        state.bgMode = m;
                        scene.background = new THREE.Color(BG_COLORS[m]);
                        const isLight = m === "light";
                        const gridMain = isLight ? 0x888888 : 0x444444;
                        const gridSec = isLight ? 0xbbbbbb : 0x222222;
                        state.grid.material.color.setHex(gridMain);
                        state.grid.material.opacity = 1;
                        if (state.grid.material2) state.grid.material2.color.setHex(gridSec);
                        activate(ui.btnBgDark, m === "dark");
                        activate(ui.btnBgMid, m === "mid");
                        activate(ui.btnBgLight, m === "light");
                    }

                    function setGrid(on) {
                        state.grid.visible = on;
                        activate(ui.btnGrid, on);
                    }
                    function toggleFullscreen() {
                        const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
                        if (!fsEl) {
                            (ui.wrap.requestFullscreen || ui.wrap.webkitRequestFullscreen)?.call(ui.wrap);
                        } else {
                            (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
                        }
                    }
                    const onFsChange = () => {
                        const isFs = !!(document.fullscreenElement || document.webkitFullscreenElement);
                        activate(ui.btnFs, isFs);
                        setTimeout(resize, 50);
                    };
                    document.addEventListener("fullscreenchange", onFsChange);
                    document.addEventListener("webkitfullscreenchange", onFsChange);

                    ui.btnGrid.onclick = () => setGrid(!state.grid.visible);
                    ui.btnFs.onclick = toggleFullscreen;
                    ui.btnOrbit.onclick = () => setNavMode("orbit");
                    ui.btnWASD.onclick = () => setNavMode("wasd");
                    ui.btnSolid.onclick = () => setRenderMode("solid");
                    ui.btnWire.onclick = () => setRenderMode("wireframe");
                    ui.btnPoints.onclick = () => setRenderMode("points");
                    ui.btnUnlit.onclick = () => setMaterialMode("unlit");
                    ui.btnLit.onclick = () => setMaterialMode("lit");
                    ui.btnBgDark.onclick = () => setBg("dark");
                    ui.btnBgMid.onclick = () => setBg("mid");
                    ui.btnBgLight.onclick = () => setBg("light");
                    ui.btnReset.onclick = () => {
                        if (!state.model) return;
                        state.bounds = frameModel(THREE, state.model, camera, state.orbit, state.farMul);
                    };

                    ui.sBright.slider.addEventListener("input", () => {
                        renderer.toneMappingExposure = +ui.sBright.slider.value;
                    });
                    ui.sPoint.slider.addEventListener("input", () => {
                        if (state.model && state.model._mastPoints) {
                            state.model._mastPoints.material.size = +ui.sPoint.slider.value;
                            state.model._mastPoints.material.needsUpdate = true;
                        }
                    });
                    ui.sFog.slider.addEventListener("input", () => {
                        state.farMul = +ui.sFog.slider.value;
                        if (state.bounds) {
                            camera.far = state.bounds.dist * state.farMul;
                            camera.updateProjectionMatrix();
                        }
                    });

                    ui.canvas.addEventListener("click", () => {
                        if (state.mode === "wasd" && !state.plock.isLocked) {
                            try { state.plock.lock(); } catch (e) {}
                        }
                    });

                    ui.btnDownload.onclick = () => {
                        if (!state._currentGLB) {
                            ui.status.textContent = "no model to download";
                            ui.status.style.color = "#f88";
                            return;
                        }
                        const a = document.createElement("a");
                        a.href = state._currentGLB.url;
                        a.download = state._currentGLB.filename || "mast3r_scene.glb";
                        a.style.display = "none";
                        document.body.appendChild(a);
                        a.click();
                        setTimeout(() => a.remove(), 0);
                    };

                    activate(ui.btnOrbit, true);
                    activate(ui.btnSolid, true);
                    activate(ui.btnUnlit, true);
                    activate(ui.btnBgDark, true);
                    activate(ui.btnGrid, true);
                    renderer.toneMappingExposure = +ui.sBright.slider.value;

                    state._disposeFs = () => {
                        document.removeEventListener("fullscreenchange", onFsChange);
                        document.removeEventListener("webkitfullscreenchange", onFsChange);
                    };

                    state._loadGLB = (url, filename) => {
                        state._currentGLB = { url, filename };
                        if (state.model) {
                            scene.remove(state.model);
                            state.model.traverse?.((o) => {
                                if (o.geometry) o.geometry.dispose?.();
                                if (o.material) {
                                    const ms = Array.isArray(o.material) ? o.material : [o.material];
                                    for (const m of ms) m.dispose?.();
                                }
                                if (o.userData._basicMat) {
                                    for (const m of o.userData._basicMat) m.dispose?.();
                                }
                            });
                            if (state.model._mastPoints) {
                                state.model._mastPoints.geometry?.dispose();
                                state.model._mastPoints.material?.dispose();
                                state.model.parent?.remove(state.model._mastPoints);
                            }
                            state.model = null;
                        }
                        ui.status.textContent = "loading...";
                        loadThree().then(({ GLTFLoader }) => {
                            new GLTFLoader().load(
                                url,
                                (gltf) => {
                                    const root = gltf.scene || gltf.scenes[0];
                                    scene.add(root);
                                    state.model = root;
                                    state.bounds = frameModel(THREE, root, camera, state.orbit, state.farMul);
                                    applyMaterialMode(THREE, root, state.materialMode);
                                    applyRenderMode(THREE, root, state.renderMode);
                                    ui.status.textContent = filename || "loaded";
                                    ui.status.style.color = "#9fd";
                                },
                                (xhr) => {
                                    if (xhr.total) {
                                        const pct = Math.round((xhr.loaded / xhr.total) * 100);
                                        ui.status.textContent = `loading ${pct}%`;
                                    }
                                },
                                (err) => {
                                    console.error("[Mast3rViewer3D] load error", err);
                                    ui.status.textContent = "load failed (see console)";
                                    ui.status.style.color = "#f88";
                                }
                            );
                        });
                    };
                })
                .catch((e) => {
                    ui.status.textContent = "three.js failed (no internet?)";
                    ui.status.style.color = "#f88";
                    console.error("[Mast3rViewer3D] three.js failed:", e);
                });

            return ret;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, arguments);
            const state = this._mast3rViewerState;
            const ui = this._mast3rViewer3d;
            if (!state || !ui) return;
            const url = message?.glb_url?.[0];
            const filename = message?.filename?.[0] || "";
            if (!url) {
                ui.status.textContent = "no model";
                return;
            }
            const bust = `${url}${url.includes("?") ? "&" : "?"}_t=${Date.now()}`;
            if (state._loadGLB) state._loadGLB(bust, filename);
        };

        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            onRemoved?.apply(this, arguments);
            try { this._mast3rViewerState?._dispose?.(); } catch (e) {}
        };
    },
});
