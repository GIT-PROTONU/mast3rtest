import os
import time

import numpy as np
import trimesh


class Mast3rSolidify:
    """Turn the MASt3R surface mesh into a denser/more-solid mesh.

    Modes:
      passthrough  — no change.
      voxel_fill   — voxelize the point cloud and thicken each point. Plugs
                     small holes between adjacent samples without trying to
                     close large gaps.
      voxel_close  — voxel_fill plus morphological closing. Fills bigger
                     gaps; produces a near-watertight surface in most cases.
      convex_hull  — wraps the whole point cloud in a convex shell. Useful
                     as a fallback or for simple convex objects only.

    Vertex colors from the original mesh are transferred to the new surface
    by nearest-neighbor lookup so the photometric look is preserved.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "method": (
                    ["passthrough", "voxel_fill", "voxel_close", "convex_hull"],
                    {"default": "voxel_close"},
                ),
                "voxel_resolution": (
                    "INT",
                    {
                        "default": 220,
                        "min": 30,
                        "max": 600,
                        "step": 10,
                        "tooltip": "Voxel grid resolution along the longest axis. Higher = more detail, more memory (600^3 ~= 200MB).",
                    },
                ),
                "dilation": (
                    "INT",
                    {
                        "default": 1,
                        "min": 0,
                        "max": 8,
                        "step": 1,
                        "tooltip": "Voxels to thicken around each input point.",
                    },
                ),
                "closing": (
                    "INT",
                    {
                        "default": 3,
                        "min": 0,
                        "max": 15,
                        "step": 1,
                        "tooltip": "Morphological closing radius. Higher fills larger gaps. Only used in voxel_close mode.",
                    },
                ),
                "smooth_iterations": (
                    "INT",
                    {
                        "default": 3,
                        "min": 0,
                        "max": 30,
                        "step": 1,
                        "tooltip": "Taubin smoothing iterations on the output surface.",
                    },
                ),
                "keep_largest": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Drop disconnected islands and keep only the biggest connected component.",
                    },
                ),
                "transfer_colors": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Copy vertex colors from the source mesh by nearest neighbor.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("glb_path",)
    FUNCTION = "solidify"
    CATEGORY = "MASt3R"

    @classmethod
    def IS_CHANGED(cls, glb_path, **kwargs):
        if glb_path and os.path.isfile(glb_path):
            return (os.path.getmtime(glb_path), tuple(sorted(kwargs.items())))
        return float("nan")

    def _find_main_mesh(self, scene):
        main = None
        main_name = None
        for name, geom in scene.geometry.items():
            if not hasattr(geom, "faces"):
                continue
            if main is None or len(geom.faces) > len(main.faces):
                main = geom
                main_name = name
        return main_name, main

    def _voxelize_and_meshify(self, source_mesh, resolution, dilation, closing):
        from scipy.ndimage import binary_dilation, binary_closing

        try:
            from skimage.measure import marching_cubes
        except ImportError as e:
            raise RuntimeError(
                "Mast3rSolidify needs scikit-image. Install with:\n"
                "  python_embeded\\python.exe -m pip install scikit-image\n"
                f"(original error: {e})"
            )

        verts = np.asarray(source_mesh.vertices, dtype=np.float64)
        if len(verts) == 0:
            return source_mesh

        bbox_min = verts.min(axis=0)
        bbox_max = verts.max(axis=0)
        extent = bbox_max - bbox_min
        longest = float(extent.max())
        if longest <= 0:
            return source_mesh

        pitch = longest / max(resolution, 1)
        pad_voxels = max(dilation, closing) + 2
        bbox_min = bbox_min - pitch * pad_voxels
        bbox_max = bbox_max + pitch * pad_voxels
        dims = np.ceil((bbox_max - bbox_min) / pitch).astype(int)
        dims = np.clip(dims, 4, 600)
        print(
            f"Mast3rSolidify: voxelizing into grid {tuple(int(d) for d in dims)} "
            f"(pitch={pitch:.5f} world-units, ~{int(dims.prod())} voxels)"
        )

        vox = ((verts - bbox_min) / pitch).astype(int)
        vox = np.clip(vox, 0, dims - 1)
        grid = np.zeros(tuple(dims), dtype=bool)
        grid[vox[:, 0], vox[:, 1], vox[:, 2]] = True

        if dilation > 0:
            grid = binary_dilation(grid, iterations=int(dilation))
        if closing > 0:
            grid = binary_closing(grid, iterations=int(closing))

        if not grid.any():
            return source_mesh

        verts_m, faces_m, _, _ = marching_cubes(grid.astype(np.float32), level=0.5)
        # Marching cubes returns vertices in (i, j, k) voxel indices.
        verts_world = verts_m * pitch + bbox_min

        new_mesh = trimesh.Trimesh(
            vertices=verts_world,
            faces=faces_m,
            process=True,
            validate=True,
        )
        return new_mesh

    def _transfer_colors(self, src_mesh, dst_mesh):
        from scipy.spatial import cKDTree

        src_colors = None
        if (
            hasattr(src_mesh, "visual")
            and src_mesh.visual is not None
            and getattr(src_mesh.visual, "vertex_colors", None) is not None
            and len(src_mesh.visual.vertex_colors) == len(src_mesh.vertices)
        ):
            src_colors = np.asarray(src_mesh.visual.vertex_colors)

        if src_colors is None or len(src_colors) == 0:
            print("  color transfer: no vertex colors on source, skipping")
            return

        tree = cKDTree(np.asarray(src_mesh.vertices))
        _, idx = tree.query(np.asarray(dst_mesh.vertices))
        dst_colors = src_colors[idx]
        if dst_colors.shape[1] == 3:
            alpha = np.full((len(dst_colors), 1), 255, dtype=np.uint8)
            dst_colors = np.hstack([dst_colors.astype(np.uint8), alpha])
        dst_mesh.visual = trimesh.visual.ColorVisuals(
            mesh=dst_mesh, vertex_colors=dst_colors.astype(np.uint8)
        )

    def solidify(
        self,
        glb_path,
        method,
        voxel_resolution,
        dilation,
        closing,
        smooth_iterations,
        keep_largest,
        transfer_colors,
    ):
        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(f"Mast3rSolidify: GLB not found: {glb_path!r}")

        if method == "passthrough":
            return (glb_path,)

        scene = trimesh.load(glb_path, force=None)
        if not isinstance(scene, trimesh.Scene):
            scene = trimesh.Scene([scene])

        name, main = self._find_main_mesh(scene)
        if main is None:
            print("Mast3rSolidify: no mesh in GLB, returning input unchanged")
            return (glb_path,)

        print(
            f"Mast3rSolidify: input mesh '{name}' "
            f"verts={len(main.vertices)} faces={len(main.faces)}"
        )

        if method == "convex_hull":
            new_mesh = trimesh.convex.convex_hull(main.vertices)
        elif method in ("voxel_fill", "voxel_close"):
            close = int(closing) if method == "voxel_close" else 0
            new_mesh = self._voxelize_and_meshify(
                main, int(voxel_resolution), int(dilation), close
            )
        else:
            new_mesh = main

        if new_mesh is None or len(new_mesh.faces) == 0:
            print("Mast3rSolidify: empty output, returning input unchanged")
            return (glb_path,)

        if keep_largest:
            try:
                comps = new_mesh.split(only_watertight=False)
                if len(comps) > 1:
                    new_mesh = max(comps, key=lambda m: len(m.faces))
                    print(f"  kept largest component of {len(comps)}")
            except Exception as e:
                print(f"  keep_largest failed: {e}")

        if smooth_iterations > 0:
            try:
                trimesh.smoothing.filter_taubin(
                    new_mesh, lamb=0.4, nu=-0.43, iterations=int(smooth_iterations)
                )
            except Exception as e:
                print(f"  smoothing failed: {e}")

        if transfer_colors and method != "passthrough":
            try:
                self._transfer_colors(main, new_mesh)
            except Exception as e:
                print(f"  color transfer failed: {e}")

        scene.geometry[name] = new_mesh
        print(
            f"Mast3rSolidify: output verts={len(new_mesh.vertices)} "
            f"faces={len(new_mesh.faces)}"
        )

        out_dir = os.path.dirname(glb_path) or "."
        out_name = f"scene_solid_{int(time.time())}.glb"
        out_path = os.path.join(out_dir, out_name)
        scene.export(out_path)
        print(f"Mast3rSolidify: saved -> {out_path}")
        return (out_path,)


NODE_CLASS_MAPPINGS = {"Mast3rSolidify": Mast3rSolidify}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rSolidify": "MASt3R Solidify Mesh"}
