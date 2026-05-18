import os

import folder_paths


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class Mast3rFolderInput:
    """Pick a folder of images via the WebUI 'Pick Folder' button.

    The frontend uploads every image in the chosen folder into a unique
    subfolder of ComfyUI's input directory and writes the subfolder name
    into the `subfolder` widget. This node resolves it to an absolute
    path that the Mast3rRun node can consume as `image_folder_path`.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "subfolder": ("STRING", {"default": "", "multiline": False}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("folder_path",)
    FUNCTION = "resolve"
    CATEGORY = "MASt3R"

    @classmethod
    def IS_CHANGED(cls, subfolder):
        if not subfolder:
            return float("nan")
        path = os.path.join(folder_paths.get_input_directory(), subfolder.strip())
        if not os.path.isdir(path):
            return float("nan")
        try:
            return max(
                (os.path.getmtime(os.path.join(path, f)) for f in os.listdir(path)),
                default=0.0,
            )
        except OSError:
            return float("nan")

    def resolve(self, subfolder):
        sub = (subfolder or "").strip()
        if not sub:
            raise ValueError(
                "MASt3R Folder Input: no folder selected. Click 'Pick Folder' on the node "
                "and choose a folder containing your scene images."
            )

        path = os.path.join(folder_paths.get_input_directory(), sub)
        if not os.path.isdir(path):
            raise FileNotFoundError(
                f"MASt3R Folder Input: folder '{path}' does not exist. "
                "Did the upload complete? Try 'Pick Folder' again."
            )

        n = sum(1 for f in os.listdir(path) if f.lower().endswith(IMAGE_EXTS))
        if n < 2:
            raise ValueError(
                f"MASt3R Folder Input: folder contains only {n} image(s); MASt3R needs "
                f"at least 2 for a real reconstruction. Path: {path}"
            )

        print(f"MASt3R Folder Input: using {n} images from {path}")
        return (path,)


NODE_CLASS_MAPPINGS = {"Mast3rFolderInput": Mast3rFolderInput}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rFolderInput": "MASt3R Folder Input"}
