"""Metric scale calibration from a ChArUco board.

Replaces the heuristic `scale` knob on the viewer with a real scale factor
derived from a printed calibration target detected in the input photos.

How it works:
  1. Detect ChArUco corners in every original-resolution input image.
  2. For each detected corner, map its pixel coordinate to the MASt3R
     working resolution (~512px on the long edge) and look up the
     per-pixel 3D coordinate from the MASt3R dense pointmap.
  3. ChArUco corner IDs encode known positions on the printed board
     (in millimeters), so each detection gives us a paired
     (mast3r_3d_point, board_3d_point) sample.
  4. Solve for the single scalar `s` such that pairwise distances
     between mast3r points match pairwise distances on the physical
     board: minimize sum_{i,j} (s * ||m_i - m_j|| - ||b_i - b_j||)^2.
     We use a median-ratio estimate + MAD outlier rejection so a few
     bad lookups (occluded corners, blurry samples) don't poison the
     fit.
  5. Apply the scale uniformly to every geometry in the input GLB and
     re-export.

This addresses prtom.txt Steps 1-2 ("Scale Target Detection" / "Apply
Scale Anchor") for the software-only case where no hardware sync is
available.
"""

import os
import time

import numpy as np
import trimesh


ARUCO_DICTS = [
    "DICT_4X4_50", "DICT_4X4_100", "DICT_4X4_250", "DICT_4X4_1000",
    "DICT_5X5_50", "DICT_5X5_100", "DICT_5X5_250", "DICT_5X5_1000",
    "DICT_6X6_50", "DICT_6X6_100", "DICT_6X6_250", "DICT_6X6_1000",
    "DICT_7X7_50", "DICT_7X7_100", "DICT_7X7_250", "DICT_7X7_1000",
]

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class Mast3rCharucoScale:
    """Detect a ChArUco board in the input photos and rescale the GLB to true metric units."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "scene": ("MAST3R_SCENE",),
                "image_folder_path": ("STRING", {"default": "", "forceInput": True}),
                "squares_x": (
                    "INT",
                    {"default": 7, "min": 2, "max": 40, "step": 1,
                     "tooltip": "Number of chessboard squares along the X axis (full board, not interior corners)."},
                ),
                "squares_y": (
                    "INT",
                    {"default": 5, "min": 2, "max": 40, "step": 1,
                     "tooltip": "Number of chessboard squares along the Y axis."},
                ),
                "square_size_mm": (
                    "FLOAT",
                    {"default": 30.0, "min": 0.5, "max": 500.0, "step": 0.1,
                     "tooltip": "Side length of one chessboard square, measured in mm. Measure the printed board with calipers, don't trust the source PDF."},
                ),
                "marker_size_mm": (
                    "FLOAT",
                    {"default": 22.0, "min": 0.5, "max": 500.0, "step": 0.1,
                     "tooltip": "Side length of an ArUco marker inside each white square (mm). Usually ~70-75% of square_size."},
                ),
                "aruco_dict": (ARUCO_DICTS, {"default": "DICT_5X5_100"}),
                "output_unit": (
                    ["mm", "m"],
                    {"default": "mm",
                     "tooltip": "Unit of the rescaled GLB. mm keeps the board world; m divides by 1000 (typical CAD convention)."},
                ),
                "outlier_mad_k": (
                    "FLOAT",
                    {"default": 3.0, "min": 0.0, "max": 10.0, "step": 0.1,
                     "tooltip": "Reject pair-ratio samples more than k * MAD from the median. 0 disables outlier rejection. 3.0 is conservative."},
                ),
                "enabled": (
                    "BOOLEAN",
                    {"default": True, "label_on": "on", "label_off": "off",
                     "tooltip": "Master on/off. When off, GLB passes through unchanged (scale_factor=1.0)."},
                ),
            },
        }

    RETURN_TYPES = ("STRING", "FLOAT")
    RETURN_NAMES = ("glb_path", "scale_factor")
    FUNCTION = "calibrate"
    CATEGORY = "MASt3R"

    @classmethod
    def IS_CHANGED(cls, glb_path, **kwargs):
        if glb_path and os.path.isfile(glb_path):
            return (os.path.getmtime(glb_path), tuple(sorted(kwargs.items())))
        return float("nan")

    def _require_cv2(self):
        try:
            import cv2
            return cv2
        except ImportError as e:
            raise RuntimeError(
                "Mast3rCharucoScale needs opencv-python. Install with:\n"
                "  python_embeded\\python.exe -m pip install opencv-python\n"
                f"(original error: {e})"
            )

    def _collect_filelist(self, folder):
        files = []
        for f in os.listdir(folder):
            if f.lower().endswith(IMAGE_EXTS):
                files.append(os.path.join(folder, f))
        return sorted({os.path.normcase(os.path.abspath(f)) for f in files})

    def _detect_corners(self, cv2, board, gray):
        """Return (corners_Nx2, ids_N) or (None, None) if nothing detected."""
        try:
            detector = cv2.aruco.CharucoDetector(board)
            corners, ids, _, _ = detector.detectBoard(gray)
            if corners is not None and ids is not None and len(ids) >= 4:
                return corners.reshape(-1, 2), ids.ravel()
        except Exception as e:
            print(f"  CharucoDetector failed: {e}, trying legacy API")

        dictionary = board.getDictionary()
        mcorners, mids, _ = cv2.aruco.detectMarkers(gray, dictionary)
        if mids is None or len(mids) == 0:
            return None, None
        retval, ccorners, cids = cv2.aruco.interpolateCornersCharuco(
            mcorners, mids, gray, board
        )
        if retval is None or retval < 4 or ccorners is None or cids is None:
            return None, None
        return ccorners.reshape(-1, 2), cids.ravel()

    def _solve_scale(self, measured, known, rng, mad_k):
        """Median-ratio scale estimator from pairwise distances with MAD outlier rejection.

        Returns (scale_mm_per_unit, rel_std_pct, n_kept_pairs, n_total_pairs)."""
        n = len(measured)
        if n < 2:
            raise ValueError(f"Only {n} corner samples; need at least 2 to compute pairwise distances.")

        # Limit pair count for speed; subsample if n is huge.
        max_pairs = 50000
        all_pairs = n * (n - 1) // 2
        if all_pairs <= max_pairs:
            i_idx, j_idx = np.triu_indices(n, k=1)
        else:
            i_idx = rng.integers(0, n, max_pairs)
            j_idx = rng.integers(0, n, max_pairs)
            keep = i_idx != j_idx
            i_idx, j_idx = i_idx[keep], j_idx[keep]

        meas_d = np.linalg.norm(measured[i_idx] - measured[j_idx], axis=1)
        known_d = np.linalg.norm(known[i_idx] - known[j_idx], axis=1)
        good = (meas_d > 1e-9) & (known_d > 1e-9)
        meas_d, known_d = meas_d[good], known_d[good]
        if len(meas_d) == 0:
            raise ValueError("All paired distances were degenerate.")

        ratios = known_d / meas_d
        median = float(np.median(ratios))

        if mad_k > 0 and len(ratios) > 10:
            mad = float(np.median(np.abs(ratios - median))) or 1e-12
            keep = np.abs(ratios - median) < (mad_k * mad)
            kept = int(keep.sum())
            if kept > 10:
                ratios = ratios[keep]
                median = float(np.median(ratios))
        else:
            kept = len(ratios)

        rel_std = float(np.std(ratios) / median) if median > 0 else float("inf")
        return median, rel_std, kept, len(meas_d)

    def calibrate(
        self,
        glb_path,
        scene,
        image_folder_path,
        squares_x,
        squares_y,
        square_size_mm,
        marker_size_mm,
        aruco_dict,
        output_unit,
        outlier_mad_k,
        enabled=True,
    ):
        if not enabled:
            print("Mast3rCharucoScale: disabled, passing GLB through unchanged")
            return (glb_path, 1.0)

        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(f"Mast3rCharucoScale: GLB not found: {glb_path!r}")
        if scene is None:
            raise ValueError(
                "Mast3rCharucoScale: scene input is required. Wire the 'scene' output of Mast3rRun to this node."
            )
        if not image_folder_path or not os.path.isdir(image_folder_path):
            raise FileNotFoundError(f"Mast3rCharucoScale: image folder not found: {image_folder_path!r}")

        cv2 = self._require_cv2()
        from dust3r.utils.device import to_numpy

        aruco_attr = getattr(cv2.aruco, aruco_dict, None)
        if aruco_attr is None:
            raise ValueError(f"Unknown aruco dict {aruco_dict!r}")
        dictionary = cv2.aruco.getPredefinedDictionary(aruco_attr)
        board = cv2.aruco.CharucoBoard(
            (int(squares_x), int(squares_y)),
            float(square_size_mm),
            float(marker_size_mm),
            dictionary,
        )
        board_corners_mm = np.asarray(board.getChessboardCorners(), dtype=np.float64)

        imgs = scene.imgs
        pts3d, _, _ = to_numpy(scene.get_dense_pts3d(clean_depth=True))
        pts3d_grids = []
        for i, img in enumerate(imgs):
            H_m, W_m = img.shape[:2]
            grid = np.asarray(pts3d[i]).reshape(H_m, W_m, 3)
            pts3d_grids.append(grid)
        n_scene_imgs = len(imgs)

        filelist = self._collect_filelist(image_folder_path)
        if len(filelist) != n_scene_imgs:
            print(
                f"Mast3rCharucoScale: WARN folder has {len(filelist)} images, "
                f"scene has {n_scene_imgs}. Pairing by sorted order."
            )

        measured_pts = []
        known_pts = []
        detections_per_image = 0

        for i in range(min(len(filelist), n_scene_imgs)):
            fpath = filelist[i]
            img_orig = cv2.imread(fpath)
            if img_orig is None:
                print(f"  skipping unreadable image: {os.path.basename(fpath)}")
                continue
            gray = cv2.cvtColor(img_orig, cv2.COLOR_BGR2GRAY)
            H_orig, W_orig = gray.shape

            corners, ids = self._detect_corners(cv2, board, gray)
            if corners is None or ids is None:
                continue
            detections_per_image += 1
            print(f"  {os.path.basename(fpath)}: {len(ids)} ChArUco corners detected")

            H_m, W_m = imgs[i].shape[:2]
            sx, sy = W_m / W_orig, H_m / H_orig
            grid = pts3d_grids[i]

            for k, cid in enumerate(ids):
                if cid < 0 or cid >= len(board_corners_mm):
                    continue
                px, py = corners[k]
                mx = int(round(px * sx))
                my = int(round(py * sy))
                if mx < 0 or mx >= W_m or my < 0 or my >= H_m:
                    continue
                p3d = grid[my, mx]
                if not np.all(np.isfinite(p3d)):
                    continue
                measured_pts.append(p3d)
                known_pts.append(board_corners_mm[int(cid)])

        if detections_per_image == 0:
            raise ValueError(
                "Mast3rCharucoScale: no ChArUco board detected in any image. "
                "Check: (1) board dimensions squares_x/squares_y, (2) aruco_dict matches the printed board, "
                "(3) the board is visible and in focus in at least one input photo."
            )
        if len(measured_pts) < 4:
            raise ValueError(
                f"Mast3rCharucoScale: only {len(measured_pts)} valid 3D-corner samples (need >=4). "
                "Some corners may be on invalid pixels (sky/occluded). Try shooting closer or with more board coverage."
            )

        measured = np.asarray(measured_pts)
        known = np.asarray(known_pts)
        rng = np.random.default_rng(0)
        scale_mm_per_unit, rel_std, kept, total = self._solve_scale(
            measured, known, rng, float(outlier_mad_k)
        )

        print(
            f"Mast3rCharucoScale: samples={len(measured)} from {detections_per_image} images; "
            f"scale = {scale_mm_per_unit:.6f} mm / MASt3R-unit "
            f"(rel-std {rel_std * 100:.2f}%, kept {kept}/{total} pairs)"
        )

        if rel_std > 0.15:
            print(
                "  WARN: rel-std > 15% - high variance suggests the scene's metric is non-uniform "
                "(MASt3R pose drift) or some corner samples landed on bad pixels. Consider raising "
                "outlier_mad_k or re-shooting with the board closer to the subject."
            )

        scale = scale_mm_per_unit
        if output_unit == "m":
            scale = scale / 1000.0

        gscene = trimesh.load(glb_path, force=None)
        if not isinstance(gscene, trimesh.Scene):
            gscene = trimesh.Scene([gscene])
        for g in gscene.geometry.values():
            g.apply_scale(float(scale))

        out_dir = os.path.dirname(glb_path) or "."
        out_path = os.path.join(out_dir, f"scene_charuco_{int(time.time())}.glb")
        gscene.export(out_path)
        print(f"Mast3rCharucoScale: saved -> {out_path}  (unit={output_unit}, scale={scale:.6f})")

        return (out_path, float(scale))


NODE_CLASS_MAPPINGS = {"Mast3rCharucoScale": Mast3rCharucoScale}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rCharucoScale": "MASt3R ChArUco Scale Calibration"}
