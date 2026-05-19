"""Metric scale calibration from a printed calibration target.

Supports two board types:

  chessboard  — plain printed chessboard. Cheapest, most common. Detected
                with cv2.findChessboardCorners + cornerSubPix. The full
                board must be visible in each calibration image.
  charuco     — ChArUco board (chessboard + ArUco markers in the white
                squares). Allows partial views and gives globally unique
                corner IDs across images.

For both modes:
  1. Detect calibration corners in every original-resolution input photo.
  2. For each detected corner, map its pixel coordinate to the MASt3R
     working resolution (~512px on the long edge) and look up the
     per-pixel 3D coordinate from the MASt3R dense pointmap.
  3. Each corner has a known position on the printed board (in mm),
     so we get paired (mast3r_3d_point, board_3d_point) samples.
  4. Solve for the scalar `s` (mm per MASt3R-unit) that makes
     pairwise corner distances *within the same image* match the
     board geometry. Within-image is essential: chessboard corner IDs
     are local per image, not globally consistent, so cross-image
     pairs would be wrong for that mode. (ChArUco IDs are global but
     we use the same code path for both — within-image pairs are
     always strictly correct.)
  5. Median-ratio estimator + MAD outlier rejection for robustness.
  6. Apply the scale uniformly to every geometry in the input GLB.

Addresses prtom.txt Steps 1-2 ("Scale Target Detection" / "Apply Scale
Anchor") in the software-only setting, without requiring hardware sync.
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

BOARD_TYPES = ["chessboard", "charuco"]

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class Mast3rCharucoScale:
    """Detect a chessboard or ChArUco board in the input photos and rescale the GLB to true metric units."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "scene": ("MAST3R_SCENE",),
                "image_folder_path": ("STRING", {"default": "", "forceInput": True}),
                "board_type": (
                    BOARD_TYPES,
                    {"default": "chessboard",
                     "tooltip": "chessboard = plain printed chessboard (whole board must be visible). charuco = chessboard + ArUco markers (supports partial views)."},
                ),
                "squares_x": (
                    "INT",
                    {"default": 8, "min": 2, "max": 40, "step": 1,
                     "tooltip": "Total chessboard squares along the X axis. e.g. an 8x8 board: squares_x=8, squares_y=8."},
                ),
                "squares_y": (
                    "INT",
                    {"default": 8, "min": 2, "max": 40, "step": 1,
                     "tooltip": "Total chessboard squares along the Y axis."},
                ),
                "square_size_mm": (
                    "FLOAT",
                    {"default": 25.0, "min": 0.5, "max": 500.0, "step": 0.1,
                     "tooltip": "Side length of one square in mm. Measure your printed board with calipers, don't trust the source PDF."},
                ),
                "marker_size_mm": (
                    "FLOAT",
                    {"default": 18.0, "min": 0.5, "max": 500.0, "step": 0.1,
                     "tooltip": "[charuco only] ArUco marker edge length in mm (usually ~70-75% of square_size). Ignored for chessboard."},
                ),
                "aruco_dict": (
                    ARUCO_DICTS,
                    {"default": "DICT_5X5_100",
                     "tooltip": "[charuco only] Must match the dictionary used when the board was generated. Ignored for chessboard."},
                ),
                "output_unit": (
                    ["mm", "m"],
                    {"default": "mm",
                     "tooltip": "Unit of the rescaled GLB. mm keeps the board's world; m divides by 1000 (typical CAD convention)."},
                ),
                "outlier_mad_k": (
                    "FLOAT",
                    {"default": 3.0, "min": 0.0, "max": 10.0, "step": 0.1,
                     "tooltip": "Reject pair-ratio samples more than k*MAD from the median. 0 disables. 3.0 is conservative."},
                ),
                "enabled": (
                    "BOOLEAN",
                    {"default": True, "label_on": "on", "label_off": "off",
                     "tooltip": "Master on/off. When off, GLB passes through unchanged (scale_factor=1.0)."},
                ),
                "min_detect_squares_x": (
                    "INT",
                    {"default": 0, "min": 0, "max": 40, "step": 1,
                     "tooltip": "[chessboard only] If >0 and < squares_x, sweep pattern sizes from squares_x down to this value to allow partial-board views. 0 disables the sweep (must see whole board)."},
                ),
                "min_detect_squares_y": (
                    "INT",
                    {"default": 0, "min": 0, "max": 40, "step": 1,
                     "tooltip": "[chessboard only] Same as min_detect_squares_x for the Y axis. Tip: set both to 4 to detect any 4x4-or-bigger contiguous chessboard region."},
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

    def _detect_charuco(self, cv2, board, gray):
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

    def _detect_chessboard(self, cv2, gray, pattern_size):
        flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK
        ret, corners = cv2.findChessboardCorners(gray, pattern_size, flags)
        if not ret or corners is None:
            return None
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        return corners.reshape(-1, 2)

    def _detect_chessboard_sweep(self, cv2, gray, max_interior, min_interior):
        """Try chessboard detection at multiple sub-pattern sizes.

        max_interior, min_interior are (nx, ny) interior-corner counts (pattern_size in cv2 terms).
        Returns (corners_Nx2, pattern_size_used) or (None, None). Sweeps largest-first so partial
        views still extract as many corners as possible.
        """
        max_x, max_y = max_interior
        min_x, min_y = min_interior
        if min_x > max_x or min_y > max_y:
            return None, None

        # Build candidate sizes: largest area first, square-ish before extreme aspect.
        candidates = []
        for nx in range(max_x, min_x - 1, -1):
            for ny in range(max_y, min_y - 1, -1):
                if nx < 2 or ny < 2:
                    continue
                # Score: prefer larger total corners + closer-to-square aspect.
                area = nx * ny
                ar_penalty = abs(nx - ny)
                candidates.append((-area, ar_penalty, nx, ny))
        candidates.sort()

        for _, _, nx, ny in candidates:
            corners = self._detect_chessboard(cv2, gray, (nx, ny))
            if corners is not None:
                return corners, (nx, ny)
        return None, None

    def _chessboard_known_corners(self, pattern_size, square_size_mm):
        nx, ny = pattern_size
        ys, xs = np.mgrid[0:ny, 0:nx]
        pts = np.stack([xs.ravel(), ys.ravel(), np.zeros(nx * ny)], axis=-1).astype(np.float64)
        return pts * float(square_size_mm)

    def _solve_scale_within_image(self, per_image_samples, mad_k):
        """Compute scale (mm per MASt3R unit) from within-image pairwise distance ratios.

        per_image_samples: list of (measured_Nx3, known_Nx3) tuples, one per image
                           that produced detections.
        Returns (scale, rel_std, n_kept_pairs, n_total_pairs).
        """
        all_ratios = []
        for measured, known in per_image_samples:
            n = len(measured)
            if n < 2:
                continue
            i_idx, j_idx = np.triu_indices(n, k=1)
            meas_d = np.linalg.norm(measured[i_idx] - measured[j_idx], axis=1)
            known_d = np.linalg.norm(known[i_idx] - known[j_idx], axis=1)
            good = (meas_d > 1e-9) & (known_d > 1e-9)
            if good.any():
                all_ratios.append(known_d[good] / meas_d[good])

        if not all_ratios:
            raise ValueError("No valid within-image pairs found.")
        ratios = np.concatenate(all_ratios)
        if len(ratios) == 0:
            raise ValueError("No valid pair-ratios after filtering.")

        median = float(np.median(ratios))
        if mad_k > 0 and len(ratios) > 10:
            mad = float(np.median(np.abs(ratios - median))) or 1e-12
            keep_mask = np.abs(ratios - median) < (mad_k * mad)
            kept = int(keep_mask.sum())
            if kept > 10:
                ratios = ratios[keep_mask]
                median = float(np.median(ratios))
        else:
            kept = len(ratios)

        rel_std = float(np.std(ratios) / median) if median > 0 else float("inf")
        return median, rel_std, kept, len(ratios) if kept == len(ratios) else int(np.sum([len(r) for r in all_ratios]))

    def calibrate(
        self,
        glb_path,
        scene,
        image_folder_path,
        board_type,
        squares_x,
        squares_y,
        square_size_mm,
        marker_size_mm,
        aruco_dict,
        output_unit,
        outlier_mad_k,
        enabled=True,
        min_detect_squares_x=0,
        min_detect_squares_y=0,
    ):
        if not enabled:
            print("Mast3rCharucoScale: disabled, passing GLB through unchanged")
            return (glb_path, 1.0)

        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(f"Mast3rCharucoScale: GLB not found: {glb_path!r}")
        if scene is None:
            raise ValueError(
                "Mast3rCharucoScale: scene input is required. Wire the 'scene' output of Mast3rRun."
            )
        if not image_folder_path or not os.path.isdir(image_folder_path):
            raise FileNotFoundError(f"Mast3rCharucoScale: image folder not found: {image_folder_path!r}")

        cv2 = self._require_cv2()
        from dust3r.utils.device import to_numpy

        sx_int = int(squares_x)
        sy_int = int(squares_y)
        sq_mm = float(square_size_mm)

        if board_type == "charuco":
            aruco_attr = getattr(cv2.aruco, aruco_dict, None)
            if aruco_attr is None:
                raise ValueError(f"Unknown aruco dict {aruco_dict!r}")
            dictionary = cv2.aruco.getPredefinedDictionary(aruco_attr)
            board = cv2.aruco.CharucoBoard(
                (sx_int, sy_int), sq_mm, float(marker_size_mm), dictionary
            )
            board_corners_mm = np.asarray(board.getChessboardCorners(), dtype=np.float64)
            print(f"Mast3rCharucoScale: mode=charuco, board {sx_int}x{sy_int} sq={sq_mm}mm, marker={marker_size_mm}mm, dict={aruco_dict}")
        elif board_type == "chessboard":
            board = None
            max_interior = (sx_int - 1, sy_int - 1)
            if max_interior[0] < 2 or max_interior[1] < 2:
                raise ValueError(
                    f"Chessboard needs at least 3x3 squares (so 2x2 interior corners). Got {sx_int}x{sy_int}."
                )
            min_dx = int(min_detect_squares_x) if int(min_detect_squares_x) > 0 else sx_int
            min_dy = int(min_detect_squares_y) if int(min_detect_squares_y) > 0 else sy_int
            min_dx = max(min(min_dx, sx_int), 3)
            min_dy = max(min(min_dy, sy_int), 3)
            min_interior = (min_dx - 1, min_dy - 1)
            sweep_enabled = min_interior != max_interior
            board_corners_mm = None  # built per-detection in the loop
            print(
                f"Mast3rCharucoScale: mode=chessboard, board {sx_int}x{sy_int} squares, "
                f"sq={sq_mm}mm, "
                + (f"partial sweep down to {min_dx}x{min_dy} squares" if sweep_enabled
                   else "full-board detection only")
            )
        else:
            raise ValueError(f"Unknown board_type {board_type!r}")

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
                f"  WARN: folder has {len(filelist)} images, scene has {n_scene_imgs}. Pairing by sorted order."
            )

        per_image_samples = []
        total_corner_samples = 0

        for i in range(min(len(filelist), n_scene_imgs)):
            fpath = filelist[i]
            img_orig = cv2.imread(fpath)
            if img_orig is None:
                print(f"  skipping unreadable image: {os.path.basename(fpath)}")
                continue
            gray = cv2.cvtColor(img_orig, cv2.COLOR_BGR2GRAY)
            H_orig, W_orig = gray.shape

            if board_type == "charuco":
                corners, ids = self._detect_charuco(cv2, board, gray)
                if corners is None or ids is None:
                    continue
                img_known_lookup = board_corners_mm
                detected_pattern = None
                print(f"  {os.path.basename(fpath)}: {len(ids)} charuco corners detected")
            else:
                if sweep_enabled:
                    corners, detected_pattern = self._detect_chessboard_sweep(
                        cv2, gray, max_interior, min_interior
                    )
                else:
                    corners = self._detect_chessboard(cv2, gray, max_interior)
                    detected_pattern = max_interior if corners is not None else None
                if corners is None:
                    continue
                # Known corners are built fresh for the detected sub-pattern size
                img_known_lookup = self._chessboard_known_corners(detected_pattern, sq_mm)
                ids = np.arange(len(corners), dtype=np.int32)
                print(
                    f"  {os.path.basename(fpath)}: {len(ids)} chessboard corners detected "
                    f"(pattern {detected_pattern[0]}x{detected_pattern[1]} interior)"
                )

            H_m, W_m = imgs[i].shape[:2]
            sx_f = W_m / W_orig
            sy_f = H_m / H_orig
            grid = pts3d_grids[i]

            img_measured = []
            img_known = []
            for k, cid in enumerate(ids):
                cid_int = int(cid)
                if cid_int < 0 or cid_int >= len(img_known_lookup):
                    continue
                px, py = corners[k]
                mx = int(round(px * sx_f))
                my = int(round(py * sy_f))
                if mx < 0 or mx >= W_m or my < 0 or my >= H_m:
                    continue
                p3d = grid[my, mx]
                if not np.all(np.isfinite(p3d)):
                    continue
                img_measured.append(p3d)
                img_known.append(img_known_lookup[cid_int])

            if len(img_measured) >= 2:
                per_image_samples.append(
                    (np.asarray(img_measured), np.asarray(img_known))
                )
                total_corner_samples += len(img_measured)

        if not per_image_samples:
            raise ValueError(
                f"Mast3rCharucoScale: no {board_type} detected in any image. "
                "Check: (1) board dimensions squares_x/squares_y, "
                f"(2) {'aruco_dict matches the printed board' if board_type == 'charuco' else 'the full chessboard is visible and not too oblique'}, "
                "(3) the board is in focus and well-lit."
            )
        if total_corner_samples < 4:
            raise ValueError(
                f"Mast3rCharucoScale: only {total_corner_samples} valid 3D-corner samples (need >=4). "
                "Try shooting closer or with more board coverage."
            )

        scale_mm_per_unit, rel_std, kept, total = self._solve_scale_within_image(
            per_image_samples, float(outlier_mad_k)
        )

        print(
            f"Mast3rCharucoScale: samples={total_corner_samples} from {len(per_image_samples)} images; "
            f"scale = {scale_mm_per_unit:.6f} mm / MASt3R-unit "
            f"(rel-std {rel_std * 100:.2f}%, kept {kept}/{total} pairs)"
        )

        if rel_std > 0.15:
            print(
                "  WARN: rel-std > 15% - high variance suggests MASt3R pose drift across "
                "images or some corner samples landed on bad pixels. Consider raising "
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
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rCharucoScale": "MASt3R Scale Calibration (Chess/ChArUco)"}
