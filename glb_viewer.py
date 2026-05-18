import os
import shutil
import time

import folder_paths


class Mast3rGLBViewer:
    """Stage the MASt3R GLB into ComfyUI's output directory and return its filename.

    Chain this into the built-in `Preview3D` node to view the reconstructed
    point cloud / mesh along with the camera frustums baked in by MASt3R.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("model_file",)
    FUNCTION = "stage"
    CATEGORY = "MASt3R"

    @classmethod
    def IS_CHANGED(cls, glb_path):
        if glb_path and os.path.isfile(glb_path):
            return os.path.getmtime(glb_path)
        return float("nan")

    def stage(self, glb_path):
        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(
                f"MASt3R GLB not found at: {glb_path!r}. "
                "Make sure the upstream Mast3rRun node finished successfully."
            )

        comfy_output = folder_paths.get_output_directory()
        out_name = f"mast3r_scene_{int(time.time())}.glb"
        out_path = os.path.join(comfy_output, out_name)
        shutil.copy2(glb_path, out_path)
        return (out_name,)


NODE_CLASS_MAPPINGS = {
    "Mast3rGLBViewer": Mast3rGLBViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Mast3rGLBViewer": "MASt3R Stage GLB for Preview3D",
}
