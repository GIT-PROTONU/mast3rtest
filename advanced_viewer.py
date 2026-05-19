import os
import shutil
import time

import folder_paths


class Mast3rViewer3D:
    """Custom three.js viewer for MASt3R reconstructions.

    Features (provided by the frontend extension web/viewer_3d.js):
    - Orbit mode (default): drag to rotate, scroll to zoom.
    - WASD mode: click canvas to capture pointer, WASD to move,
      Space/Shift for up/down, mouse to look, ESC to release.
    - Render modes: Solid (textured fill), Wireframe, Points.
    - Reset camera button.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "remove_cameras": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "strip",
                        "label_off": "keep",
                        "tooltip": "Strip MASt3R camera frustums from the GLB before viewing/downloading. Only the largest mesh (the actual reconstruction) is kept.",
                    },
                ),
                "scale": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.001,
                        "max": 1000.0,
                        "step": 0.01,
                        "tooltip": "Uniform scale applied to the exported GLB. MASt3R 'metric' output is often off by a constant factor; tune this so CAD-imported size matches real-world. e.g. 0.5 if CAD shows 2x.",
                    },
                ),
            },
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "view"
    CATEGORY = "MASt3R"

    @classmethod
    def IS_CHANGED(cls, glb_path, remove_cameras=False, scale=1.0):
        if glb_path and os.path.isfile(glb_path):
            return (os.path.getmtime(glb_path), bool(remove_cameras), float(scale))
        return float("nan")

    def _post_process(self, src_path, dst_path, remove_cameras, scale):
        """Load src, optionally strip non-main geoms, optionally uniform-scale, export to dst."""
        import trimesh

        scene = trimesh.load(src_path, force=None)
        if not isinstance(scene, trimesh.Scene):
            scene = trimesh.Scene([scene])

        if remove_cameras:
            main_name = None
            main = None
            for name, geom in scene.geometry.items():
                if not hasattr(geom, "faces"):
                    continue
                if main is None or len(geom.faces) > len(main.faces):
                    main = geom
                    main_name = name
            if main_name is not None:
                dropped = len(scene.geometry) - 1
                scene = trimesh.Scene({main_name: main})
                print(
                    f"Mast3rViewer3D: stripped {dropped} non-main geometry/ies "
                    f"(kept '{main_name}': verts={len(main.vertices)}, faces={len(main.faces)})"
                )
            else:
                print("Mast3rViewer3D: no mesh geometry found, skipping strip")

        if abs(scale - 1.0) > 1e-9:
            for g in scene.geometry.values():
                g.apply_scale(float(scale))
            print(f"Mast3rViewer3D: applied uniform scale={scale:.4f}")

        scene.export(dst_path)

    def view(self, glb_path, remove_cameras=False, scale=1.0):
        if not glb_path or not os.path.isfile(glb_path):
            return {"ui": {"glb_url": [""], "filename": [""]}}

        comfy_output = folder_paths.get_output_directory()
        out_name = f"mast3r_view_{int(time.time())}.glb"
        out_path = os.path.join(comfy_output, out_name)

        needs_rewrite = remove_cameras or abs(scale - 1.0) > 1e-9
        if needs_rewrite:
            try:
                self._post_process(glb_path, out_path, remove_cameras, scale)
            except Exception as e:
                print(f"Mast3rViewer3D: post-process failed ({e}), copying GLB unchanged")
                shutil.copy2(glb_path, out_path)
        else:
            shutil.copy2(glb_path, out_path)

        url = f"/view?filename={out_name}&type=output&subfolder="
        return {"ui": {"glb_url": [url], "filename": [out_name]}}


NODE_CLASS_MAPPINGS = {"Mast3rViewer3D": Mast3rViewer3D}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rViewer3D": "MASt3R 3D Viewer (WASD)"}
