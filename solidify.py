import os
import time

import numpy as np
import trimesh


class Mast3rSolidify:
    """Turn the MASt3R surface mesh into a denser/more-solid mesh.

    Methods (cheap -> high quality):
      passthrough    no change.
      convex_hull    wraps the whole point cloud in a convex shell.
      voxel_fill     voxelize and thicken each sample. Plugs small holes.
      voxel_close    voxel_fill plus morphological closing. Near-watertight.
      poisson        Screened Poisson surface reconstruction (pymeshlab).
                     Best detail-vs-smoothness tradeoff for noisy clouds.
      ball_pivoting  Ball-Pivoting reconstruction (pymeshlab). Sharper than
                     Poisson; leaves real holes intact (not watertight).

    Voxel and reconstruction methods sample the source mesh *surface*
    (not just vertex positions) to preserve detail that lives between
    samples. Vertex colors are transferred via nearest neighbor.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "method": (
                    [
                        "passthrough",
                        "voxel_fill",
                        "voxel_close",
                        "convex_hull",
                        "poisson",
                        "ball_pivoting",
                    ],
                    {"default": "poisson"},
                ),
                "voxel_resolution": (
                    "INT",
                    {
                        "default": 320,
                        "min": 30,
                        "max": 1024,
                        "step": 10,
                        "tooltip": "Voxel grid resolution along the longest axis. Higher = more detail, more memory. 1024^3 ~= 1GB.",
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
                        "default": 2,
                        "min": 0,
                        "max": 15,
                        "step": 1,
                        "tooltip": "Morphological closing radius. Higher fills larger gaps. Only used in voxel_close mode.",
                    },
                ),
                "smooth_iterations": (
                    "INT",
                    {
                        "default": 1,
                        "min": 0,
                        "max": 30,
                        "step": 1,
                        "tooltip": "Taubin smoothing iterations on the output surface. Keep low for poisson/ball_pivoting since they already smooth.",
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
                "surface_samples": (
                    "INT",
                    {
                        "default": 300000,
                        "min": 0,
                        "max": 4000000,
                        "step": 10000,
                        "tooltip": "Extra points sampled across the source mesh surface before voxelizing / reconstructing. 0 = vertices only. Higher preserves more detail.",
                    },
                ),
                "poisson_depth": (
                    "INT",
                    {
                        "default": 9,
                        "min": 5,
                        "max": 12,
                        "step": 1,
                        "tooltip": "Octree depth for Poisson. 8 = smooth, 9 = balanced, 10-11 = fine detail (slow, RAM-heavy).",
                    },
                ),
                "density_quantile": (
                    "FLOAT",
                    {
                        "default": 0.02,
                        "min": 0.0,
                        "max": 0.5,
                        "step": 0.01,
                        "tooltip": "Poisson only: crop vertices below this density quantile to remove balloon artifacts in empty regions. 0 disables.",
                    },
                ),
                "enabled": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "on",
                        "label_off": "off",
                        "tooltip": "Master on/off. When off the input GLB is passed through unchanged.",
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

    def _dense_points(self, source_mesh, surface_samples):
        """Return (N,3) points: source vertices + N samples across the surface."""
        verts = np.asarray(source_mesh.vertices, dtype=np.float64)
        if surface_samples <= 0 or len(source_mesh.faces) == 0:
            return verts
        try:
            sampled, _ = trimesh.sample.sample_surface(source_mesh, int(surface_samples))
            print(f"  sampled {len(sampled)} extra surface points")
            return np.vstack([verts, np.asarray(sampled, dtype=np.float64)])
        except Exception as e:
            print(f"  surface sampling failed ({e}), using vertices only")
            return verts

    def _voxelize_and_meshify(self, source_mesh, resolution, dilation, closing, surface_samples):
        from scipy.ndimage import binary_dilation, binary_closing

        try:
            from skimage.measure import marching_cubes
        except ImportError as e:
            raise RuntimeError(
                "Mast3rSolidify needs scikit-image. Install with:\n"
                "  python_embeded\\python.exe -m pip install scikit-image\n"
                f"(original error: {e})"
            )

        pts = self._dense_points(source_mesh, surface_samples)
        if len(pts) == 0:
            return source_mesh

        bbox_min = pts.min(axis=0)
        bbox_max = pts.max(axis=0)
        extent = bbox_max - bbox_min
        longest = float(extent.max())
        if longest <= 0:
            return source_mesh

        pitch = longest / max(resolution, 1)
        pad_voxels = max(dilation, closing) + 2
        bbox_min = bbox_min - pitch * pad_voxels
        bbox_max = bbox_max + pitch * pad_voxels
        dims = np.ceil((bbox_max - bbox_min) / pitch).astype(int)
        dims = np.clip(dims, 4, 1024)
        print(
            f"Mast3rSolidify: voxelizing into grid {tuple(int(d) for d in dims)} "
            f"(pitch={pitch:.5f} world-units, ~{int(dims.prod())} voxels)"
        )

        vox = ((pts - bbox_min) / pitch).astype(int)
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
        verts_world = verts_m * pitch + bbox_min

        return trimesh.Trimesh(
            vertices=verts_world,
            faces=faces_m,
            process=True,
            validate=True,
        )

    def _require_pymeshlab(self, method_name):
        try:
            import pymeshlab
            return pymeshlab
        except ImportError as e:
            raise RuntimeError(
                f"Mast3rSolidify: method '{method_name}' needs pymeshlab. Install with:\n"
                "  python_embeded\\python.exe -m pip install pymeshlab\n"
                f"(original error: {e})"
            )

    def _pcd_meshset(self, pymeshlab, source_mesh, surface_samples):
        """Build a pymeshlab MeshSet containing a point cloud (with normals) sampled from source_mesh."""
        pts = self._dense_points(source_mesh, surface_samples).astype(np.float64)
        ms = pymeshlab.MeshSet()
        ms.add_mesh(pymeshlab.Mesh(vertex_matrix=pts), "points")
        try:
            ms.compute_normal_for_point_clouds(k=16, smoothiter=2)
        except Exception as e:
            print(f"  normal estimation failed: {e}")
        return ms

    def _poisson_meshify(self, source_mesh, depth, density_quantile, surface_samples):
        pymeshlab = self._require_pymeshlab("poisson")
        ms = self._pcd_meshset(pymeshlab, source_mesh, surface_samples)
        print(f"  screened poisson depth={depth}")
        ms.generate_surface_reconstruction_screened_poisson(
            depth=int(depth),
            samplespernode=1.5,
            pointweight=4.0,
            iters=8,
            preclean=True,
        )
        out = ms.current_mesh()
        verts = np.asarray(out.vertex_matrix(), dtype=np.float64)
        faces = np.asarray(out.face_matrix(), dtype=np.int64)
        if len(faces) == 0:
            return source_mesh

        # pymeshlab's screened Poisson stores per-vertex density in the vertex
        # scalar (quality) array. Crop low-density verts to kill balloons.
        if density_quantile > 0:
            try:
                density = np.asarray(out.vertex_scalar_array())
                if len(density) == len(verts) and len(density) > 0:
                    threshold = float(np.quantile(density, density_quantile))
                    keep = density > threshold
                    removed = int((~keep).sum())
                    if removed > 0 and keep.sum() > 100:
                        # Remap faces so they only reference kept vertices.
                        new_idx = -np.ones(len(verts), dtype=np.int64)
                        new_idx[keep] = np.arange(keep.sum())
                        face_keep = keep[faces].all(axis=1)
                        faces = new_idx[faces[face_keep]]
                        verts = verts[keep]
                        print(f"  cropped {removed} low-density verts (q={density_quantile:.2f})")
            except Exception as e:
                print(f"  density crop skipped: {e}")

        if len(faces) == 0:
            return source_mesh
        return trimesh.Trimesh(vertices=verts, faces=faces, process=True, validate=True)

    def _ball_pivoting_meshify(self, source_mesh, surface_samples):
        pymeshlab = self._require_pymeshlab("ball_pivoting")
        ms = self._pcd_meshset(pymeshlab, source_mesh, surface_samples)
        # ballradius=0 lets MeshLab auto-pick from average nearest neighbor distance.
        print("  ball pivoting (auto radius)")
        ms.generate_surface_reconstruction_ball_pivoting(
            ballradius=pymeshlab.PercentageValue(0.0),
            clustering=20.0,
            creasethr=90.0,
            deletefaces=False,
        )
        out = ms.current_mesh()
        verts = np.asarray(out.vertex_matrix(), dtype=np.float64)
        faces = np.asarray(out.face_matrix(), dtype=np.int64)
        if len(faces) == 0:
            return source_mesh
        return trimesh.Trimesh(vertices=verts, faces=faces, process=True, validate=True)

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
        surface_samples=300000,
        poisson_depth=9,
        density_quantile=0.02,
        enabled=True,
    ):
        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(f"Mast3rSolidify: GLB not found: {glb_path!r}")

        if not enabled:
            print("Mast3rSolidify: disabled, passing GLB through unchanged")
            return (glb_path,)

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
            f"Mast3rSolidify: method={method} input verts={len(main.vertices)} faces={len(main.faces)}"
        )

        if method == "convex_hull":
            new_mesh = trimesh.convex.convex_hull(main.vertices)
        elif method in ("voxel_fill", "voxel_close"):
            close = int(closing) if method == "voxel_close" else 0
            new_mesh = self._voxelize_and_meshify(
                main, int(voxel_resolution), int(dilation), close, int(surface_samples)
            )
        elif method == "poisson":
            new_mesh = self._poisson_meshify(
                main, int(poisson_depth), float(density_quantile), int(surface_samples)
            )
        elif method == "ball_pivoting":
            new_mesh = self._ball_pivoting_meshify(main, int(surface_samples))
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
