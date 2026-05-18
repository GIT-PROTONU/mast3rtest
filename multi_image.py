import torch
import comfy.utils


class Mast3rImageBatch:
    """Combine up to 10 optional IMAGE inputs into a single batch tensor.

    Mismatched H/W are auto-resized to match the first connected image
    (bilinear, center crop) so the batch can be stacked as a single 4D tensor.
    Muted or disconnected LoadImage nodes are skipped silently.
    Requires at least one connected image; MASt3R needs >= 2 for a real reconstruction.
    """

    MAX_IMAGES = 10

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                f"image_{i + 1}": ("IMAGE",) for i in range(cls.MAX_IMAGES)
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "combine"
    CATEGORY = "MASt3R"

    def combine(self, **kwargs):
        imgs = []
        for i in range(1, self.MAX_IMAGES + 1):
            v = kwargs.get(f"image_{i}")
            if v is not None:
                imgs.append(v)

        if len(imgs) == 0:
            raise ValueError(
                "Mast3rImageBatch: no images connected. Un-mute (right-click → "
                "Mode → Always) at least one Load Image node and upload a photo."
            )

        target_h, target_w = imgs[0].shape[1], imgs[0].shape[2]
        resized = []
        for im in imgs:
            if im.shape[1] != target_h or im.shape[2] != target_w:
                im = comfy.utils.common_upscale(
                    im.movedim(-1, 1), target_w, target_h, "bilinear", "center"
                ).movedim(1, -1)
            resized.append(im)

        return (torch.cat(resized, dim=0),)


NODE_CLASS_MAPPINGS = {
    "Mast3rImageBatch": Mast3rImageBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Mast3rImageBatch": "MASt3R Image Batch (up to 10)",
}
