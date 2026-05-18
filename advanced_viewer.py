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
            },
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "view"
    CATEGORY = "MASt3R"

    @classmethod
    def IS_CHANGED(cls, glb_path):
        if glb_path and os.path.isfile(glb_path):
            return os.path.getmtime(glb_path)
        return float("nan")

    def view(self, glb_path):
        if not glb_path or not os.path.isfile(glb_path):
            return {"ui": {"glb_url": [""], "filename": [""]}}

        comfy_output = folder_paths.get_output_directory()
        out_name = f"mast3r_view_{int(time.time())}.glb"
        out_path = os.path.join(comfy_output, out_name)
        shutil.copy2(glb_path, out_path)

        url = f"/view?filename={out_name}&type=output&subfolder="
        return {"ui": {"glb_url": [url], "filename": [out_name]}}


NODE_CLASS_MAPPINGS = {"Mast3rViewer3D": Mast3rViewer3D}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rViewer3D": "MASt3R 3D Viewer (WASD)"}
