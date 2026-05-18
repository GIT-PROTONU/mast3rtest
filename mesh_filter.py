import os
import time

import numpy as np
import trimesh


class Mast3rMeshFilter:
    """Clean and smooth the largest mesh inside a MASt3R-produced GLB.

    The main reconstruction mesh is identified as the geometry with the
    most faces (camera-frustum widgets are tiny and are left untouched).
    Optional operations: vertex merging, hole filling, normal repair,
    Laplacian / Taubin / Humphrey smoothing.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "smoothing": (
                    ["none", "laplacian", "taubin", "humphrey"],
                    {"default": "none"},
                ),
                "smoothing_iterations": ("INT", {"default": 2, "min": 0, "max": 60, "step": 1}),
                "smoothing_strength": (
                    "FLOAT",
                    {"default": 0.3, "min": 0.05, "max": 1.0, "step": 0.05},
                ),
                "fill_holes": ("BOOLEAN", {"default": False}),
                "fix_normals": ("BOOLEAN", {"default": False}),
                "merge_close_vertices": ("BOOLEAN", {"default": True}),
                "outlier_std": (
                    "FLOAT",
                    {
                        "default": 0.0,
                        "min": 0.0,
                        "max": 6.0,
                        "step": 0.1,
                        "tooltip": "0 disables. Otherwise drop vertices farther than N stddev from the centroid.",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("glb_path",)
    FUNCTION = "filter"
    CATEGORY = "MASt3R"

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

    def _drop_outliers(self, mesh, k):
        if k <= 0:
            return mesh
        pts = mesh.vertices
        centroid = pts.mean(axis=0)
        dists = np.linalg.norm(pts - centroid, axis=1)
        threshold = dists.mean() + k * dists.std()
        keep = dists <= threshold
        if keep.sum() < 100 or keep.all():
            return mesh
        keep_idx = np.where(keep)[0]
        keep_set = set(keep_idx.tolist())
        face_mask = np.array(
            [all(v in keep_set for v in f) for f in mesh.faces], dtype=bool
        )
        if face_mask.sum() < 100:
            return mesh
        mesh.update_faces(face_mask)
        mesh.remove_unreferenced_vertices()
        return mesh

    def filter(
        self,
        glb_path,
        smoothing,
        smoothing_iterations,
        smoothing_strength,
        fill_holes,
        fix_normals,
        merge_close_vertices,
        outlier_std,
    ):
        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(f"Mast3rMeshFilter: GLB not found: {glb_path!r}")

        scene = trimesh.load(glb_path, force=None)
        if not isinstance(scene, trimesh.Scene):
            scene = trimesh.Scene([scene])

        if not scene.geometry:
            print("Mast3rMeshFilter: GLB has no geometry, passing through")
            return (glb_path,)

        name, main = self._find_main_mesh(scene)
        if main is None:
            print("Mast3rMeshFilter: no mesh geometry found (point cloud?), passing through")
            return (glb_path,)

        print(
            f"Mast3rMeshFilter: filtering '{name}' "
            f"(verts={len(main.vertices)}, faces={len(main.faces)})"
        )

        if merge_close_vertices:
            main.merge_vertices()

        if outlier_std > 0:
            main = self._drop_outliers(main, outlier_std)
            print(f"  outlier removal -> verts={len(main.vertices)}, faces={len(main.faces)}")

        if fill_holes:
            try:
                before = len(main.faces)
                main.fill_holes()
                print(f"  fill_holes added {len(main.faces) - before} faces")
            except Exception as e:
                print(f"  fill_holes skipped: {e}")

        if fix_normals:
            try:
                main.fix_normals()
            except Exception as e:
                print(f"  fix_normals skipped: {e}")

        if smoothing != "none" and smoothing_iterations > 0:
            try:
                if smoothing == "laplacian":
                    trimesh.smoothing.filter_laplacian(
                        main, lamb=smoothing_strength, iterations=smoothing_iterations
                    )
                elif smoothing == "taubin":
                    trimesh.smoothing.filter_taubin(
                        main,
                        lamb=smoothing_strength,
                        nu=-(smoothing_strength + 0.03),
                        iterations=smoothing_iterations,
                    )
                elif smoothing == "humphrey":
                    trimesh.smoothing.filter_humphrey(
                        main,
                        alpha=0.1,
                        beta=smoothing_strength,
                        iterations=smoothing_iterations,
                    )
                print(f"  {smoothing} smoothing x{smoothing_iterations} applied")
            except Exception as e:
                print(f"  smoothing failed: {e}")

        scene.geometry[name] = main

        out_dir = os.path.dirname(glb_path) or "."
        out_name = f"scene_filtered_{int(time.time())}.glb"
        out_path = os.path.join(out_dir, out_name)
        scene.export(out_path)
        print(f"Mast3rMeshFilter: saved -> {out_path}")
        return (out_path,)


NODE_CLASS_MAPPINGS = {"Mast3rMeshFilter": Mast3rMeshFilter}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rMeshFilter": "MASt3R Mesh Filter & Smoothing"}
