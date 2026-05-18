# mast3rtest — ComfyUI-MASt3R with WASD viewer, folder upload, mesh filter & solidify

This is a fork of [jfirma1/ComfyUI-mast3r](https://github.com/jfirma1/ComfyUI-mast3r) (which itself wraps [Naver's MASt3R](https://github.com/naver/mast3r)) extended with:

- **Multi-image batching** up to 10 LoadImage nodes
- **Folder picker** that uploads a whole folder of phone photos via the WebUI
- **Mesh filter & smoothing** (Taubin / Laplacian / Humphrey, hole filling, outlier removal)
- **Solidify** (voxel → marching-cubes → solid mesh, with vertex color transfer)
- **Custom 3D viewer** with WASD navigation, fullscreen, brightness slider, point-size slider, far-plane slider, lit/unlit material, grid toggle, BG presets, in-browser GLB download
- **Bug fix** to upstream `nodes.py` so it doesn't double-load files on Windows (case-insensitive `*.jpg` + `*.JPG` glob)
- **Three ready-to-use workflows**

> Built and tested on Windows 11 + RTX 4070 Laptop (8GB VRAM) + ComfyUI portable v0.21.1 (Python 3.13, PyTorch 2.11.0+cu130).

---

## Quick setup

### 1. Install ComfyUI portable (if not already)

Download [ComfyUI_windows_portable_nvidia.7z](https://github.com/Comfy-Org/ComfyUI/releases/latest) and extract somewhere short like `C:\ComfyUI\`.

### 2. Clone this repo into custom_nodes

```powershell
cd C:\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes
git clone https://github.com/GIT-PROTONU/mast3rtest.git ComfyUI-mast3r
```

(The folder name must be `ComfyUI-mast3r` — Python imports use the directory name.)

### 3. Install Python dependencies

```powershell
cd C:\ComfyUI\ComfyUI_windows_portable
.\python_embeded\python.exe -m pip install scipy trimesh roma huggingface_hub matplotlib opencv-python scikit-image
```

`torch`, `torchvision`, `numpy`, `pillow`, `tqdm` come with portable ComfyUI — don't reinstall them.

### 4. Download the MASt3R checkpoint (2.75 GB)

```powershell
$dest = "C:\ComfyUI\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-mast3r\checkpoints"
mkdir $dest -ErrorAction SilentlyContinue
curl.exe -L -o "$dest\MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth" `
  https://download.europe.naverlabs.com/ComputerVision/MASt3R/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth
```

### 5. Copy the workflows into ComfyUI's user folder

```powershell
copy workflows\*.json C:\ComfyUI\ComfyUI_windows_portable\ComfyUI\user\default\workflows\
```

### 6. Launch

Double-click `C:\ComfyUI\ComfyUI_windows_portable\run_nvidia_gpu.bat`, then open http://127.0.0.1:8188 in your browser. The three workflows appear in the Workflow panel on the left sidebar.

---

## New nodes added by this fork

| Node | Display name | Purpose |
|---|---|---|
| `Mast3rImageBatch` | MASt3R Image Batch (up to 10) | Combines up to 10 optional IMAGE inputs into one batch (auto-resizes mismatched dimensions to match `image_1`) |
| `Mast3rFolderInput` | MASt3R Folder Input | Frontend file-picker that uploads a whole folder of images into `ComfyUI/input/mast3r_<timestamp>/` and emits the absolute path |
| `Mast3rMeshFilter` | MASt3R Mesh Filter & Smoothing | Taubin / Laplacian / Humphrey smoothing, fill_holes, fix_normals, merge_close_vertices, outlier_std removal (applied to the largest mesh; camera frustums untouched) |
| `Mast3rSolidify` | MASt3R Solidify Mesh | Converts the patchy surface mesh into a solid via voxel grid + dilation + morphological closing + marching cubes. Transfers vertex colors via KDTree. Modes: `passthrough` / `voxel_fill` / `voxel_close` / `convex_hull` |
| `Mast3rGLBViewer` | MASt3R Stage GLB for Preview3D | Copies the GLB into ComfyUI's output dir and emits the filename (so the built-in `Preview3D` node can render it) |
| `Mast3rViewer3D` | MASt3R 3D Viewer (WASD) | Custom three.js viewer with WASD + fullscreen + brightness slider + render-mode toggle + grid toggle + GLB download button |

---

## Workflows

### `MASt3R_2Images_Template.json`
Simplest workflow. Two `LoadImage` nodes → `ImageBatch` → `Mast3rRun` → `Stage GLB` → built-in `Preview3D`. Good for quick tests of a 2-photo pair.

### `MASt3R_Up_To_10_Images.json`
Ten `LoadImage` nodes in a 5×2 grid; two enabled, eight muted by default. Right-click a muted node → **Mode → Always** to enable. All feed into `Mast3rImageBatch` → `Mast3rRun` → `Preview3D`.

### `MASt3R_Folder_Advanced.json`
**Recommended.** Full pipeline: `Mast3rFolderInput` → `Mast3rRun` → `Mast3rMeshFilter` → `Mast3rSolidify` → `Mast3rViewer3D` (WASD).

Defaults tuned for an 8GB laptop and phone-photo input:

| Param | Value |
|---|---|
| `image_size` | 512 |
| `scenegraph_type` | complete |
| `niter1` / `niter2` | 700 / 700 |
| `lr1` / `lr2` | 0.07 / 0.014 |
| `min_conf_thr` | 2.0 |
| `matching_conf_thr` | 1.0 |
| `TSDF_thresh` | 0.15 |
| `cam_size` | 0.1 |
| `as_pointcloud` | false (mesh output) |
| `shared_intrinsics` | true |

---

## Viewer controls (Mast3rViewer3D)

```
[Orbit][WASD] │ [Solid][Wireframe][Points] │ [Unlit][Lit] │ Bright[──] Pt sz[──] Far[──] │ [BG·D][BG·M][BG·L][Grid] │ [Reset][Fullscreen][Download GLB]
```

| Control | What it does |
|---|---|
| Orbit | Drag = rotate, wheel = zoom, right-drag = pan (default) |
| WASD | Click canvas to lock pointer · WASD = move · Space/Shift = up/down · Ctrl = sprint · ESC = release |
| Solid / Wireframe / Points | Render mode toggle |
| Unlit / Lit | Material mode. **Unlit** (default) shows baked vertex colors directly — the right choice for photogrammetry meshes. Lit uses Hemisphere + 2× Directional lights with metalness=0, roughness=1 |
| Bright slider | Tone-mapping exposure (0.1 – 3.0) |
| Pt sz slider | Point size in Points mode |
| Far slider | Far-clip multiplier — push right if the model gets cut off |
| BG D/M/L | Dark / Mid-grey / Light background presets |
| Grid | Toggle the ground grid on/off |
| Reset | Re-frame the model in the camera |
| Fullscreen | Browser fullscreen (ESC to exit) |
| Download GLB | Saves the rendered GLB to your Downloads folder |

three.js + GLTFLoader + OrbitControls + PointerLockControls are loaded from `esm.sh` at runtime. Cached after first use.

---

## Bug fix applied to upstream

`nodes.py:370-372` had a Windows-only bug: it globbed for `*.jpg` and `*.JPG` separately. On Windows (case-insensitive FS) both patterns match the same files → every image is loaded twice → `sparse_global_alignment` crashes with `ValueError: not enough values to unpack (expected 4, got 0)` because zero-parallax matches between an image and its duplicate produce no reciprocal NN feature matches.

The fix dedupes by normalised absolute path:

```python
filelist = sorted({os.path.normcase(os.path.abspath(f)) for f in filelist})
```

---

## File layout

```
ComfyUI-mast3r/
├── __init__.py                   - registers all 11 nodes + WEB_DIRECTORY
├── nodes.py                      - upstream + Windows glob dedup fix
├── glb_viewer.py                 - Mast3rGLBViewer (stage for Preview3D)
├── multi_image.py                - Mast3rImageBatch (10 optional inputs)
├── folder_input.py               - Mast3rFolderInput (folder picker)
├── mesh_filter.py                - Mast3rMeshFilter
├── advanced_viewer.py            - Mast3rViewer3D
├── solidify.py                   - Mast3rSolidify
├── web/
│   ├── folder_picker.js          - 'Pick Folder' UI for Mast3rFolderInput
│   └── viewer_3d.js              - three.js viewer + WASD + sliders + fullscreen
├── workflows/                    - copy into ComfyUI/user/default/workflows/
│   ├── MASt3R_2Images_Template.json
│   ├── MASt3R_Up_To_10_Images.json
│   └── MASt3R_Folder_Advanced.json
├── mast3r/                       - upstream model code (Naver, CC-BY-NC-SA 4.0)
├── dust3r/                       - upstream (Naver, CC-BY-NC-SA 4.0)
├── croco/                        - upstream (Naver, CC-BY-NC-SA 4.0)
├── requirements.txt
├── LICENSE                       - CC-BY-NC-SA 4.0
└── UPSTREAM_README.md            - original README from the jfirma1 fork
```

---

## VRAM guidance (8GB / RTX 4070 Laptop)

| Image count | Recommended `scenegraph_type` | `image_size` |
|---|---|---|
| 2-4 | complete | 512 |
| 5-12 | complete or swin (winsize=4 cyclic) | 512 |
| 13-25 | swin (winsize=3-4) | 384-512 |
| 25+ | swin or retrieval mode | 384 |

If you OOM during reconstruction: drop `image_size` to 384 or 256. If you OOM during solidify: drop `voxel_resolution` to 150.

---

## Troubleshooting

**"not enough values to unpack (expected 4, got 0)"** — your input folder has duplicate files OR one image has no feature overlap with any other. Check the log for `Found N images in folder: ...` — N should match the number of unique files. If it's double, the Windows glob dedup fix needs to be applied (`nodes.py` line ~372).

**Output looks very dark in viewer** — make sure the viewer is in `Unlit` mode (default). The button should be highlighted green.

**Mesh has big holes** — in the Solidify node: increase `closing` from 3 → 5 or 6.

**Mesh looks blocky** — increase `voxel_resolution` in the Solidify node (e.g. 220 → 350). Uses more RAM.

**Viewer says "three.js failed (no internet?)"** — the viewer fetches three.js from `esm.sh`. First run needs internet; after that it's cached.

**Output is "melted" / floaters everywhere** — raise `matching_conf_thr` in Mast3rRun to 1.5-2.0 and `min_conf_thr` to 2.5-3.0.

---

## License

Upstream code from MASt3R / DUSt3R / CroCo is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) — **non-commercial use only**. By ShareAlike, all additions in this fork inherit the same license.

---

## Credits

- [MASt3R](https://github.com/naver/mast3r), [DUSt3R](https://github.com/naver/dust3r), [CroCo](https://github.com/naver/croco) — Naver Corporation
- [ComfyUI-mast3r](https://github.com/jfirma1/ComfyUI-mast3r) — upstream fork by jfirma1
- Custom nodes + viewer in this fork — assembled with [Claude Code](https://claude.com/claude-code)
