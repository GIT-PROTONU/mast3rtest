"""Full-resolution epipolar sub-pixel refinement of MASt3R correspondences.

prtom.txt Step 4: ``Epipolar 1D Patch Refinement``.

For each high-confidence pixel in a MASt3R image, look up where MASt3R
predicts it lands in a neighbour image, then refine that 2-D match by
sliding a normalized-cross-correlation (NCC) template along the
epipolar line at the *original* image resolution. A parabolic fit on
the NCC peak gives sub-pixel accuracy. The refined matches are then
re-triangulated via linear-LSQ DLT using MASt3R's camera poses, and
the new dense point cloud is exported as a GLB so downstream Solidify
can mesh it.

Why this helps: MASt3R produces a dense pointmap at 512px working
resolution. The pointmap is already metric, but each pixel maps to a
specific 3-D coordinate whose error is a *function* of MASt3R's
sub-pixel correspondence precision at 512px and the parallax between
cameras. Refining the 2-D matches at full phone-camera resolution
(~12 MP -> 4000px) recovers a precision win bounded by the actual
sensor sharpness, not the 512px working res. On sharp phone shots
that's a real sub-mm improvement; on motion-blurred or out-of-focus
photos the NCC peak is wide and refinement is a no-op (the parabolic
fit returns ~the input).
"""

import os
import time

import numpy as np
import trimesh


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


class Mast3rEpipolarRefine:
    """Refine MASt3R dense correspondences by 1-D NCC along epipolar lines at full image resolution."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_path": ("STRING", {"default": "", "forceInput": True}),
                "scene": ("MAST3R_SCENE",),
                "image_folder_path": ("STRING", {"default": "", "forceInput": True}),
                "samples_per_image": (
                    "INT",
                    {"default": 4000, "min": 100, "max": 200000, "step": 100,
                     "tooltip": "Pixels per source image to refine. 4000 = ~1.4s per image-pair on a fast CPU. Higher = denser, slower."},
                ),
                "min_conf": (
                    "FLOAT",
                    {"default": 3.0, "min": 0.0, "max": 30.0, "step": 0.1,
                     "tooltip": "Only sample MASt3R pixels with confidence above this. 3.0 is typical; raise to be stricter."},
                ),
                "patch_size": (
                    "INT",
                    {"default": 21, "min": 7, "max": 51, "step": 2,
                     "tooltip": "Side length of the NCC template patch in full-resolution pixels. Must be odd. 21 = good balance; 31 = smoother match on flat textures."},
                ),
                "search_radius_px": (
                    "INT",
                    {"default": 8, "min": 1, "max": 50, "step": 1,
                     "tooltip": "Half-length of the 1-D search range along the epipolar line, in full-resolution pixels. Bigger handles bigger MASt3R errors but slows the search."},
                ),
                "ncc_min": (
                    "FLOAT",
                    {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01,
                     "tooltip": "Discard refinements whose peak NCC is below this. Low-texture / featureless patches won't have a sharp peak; rejecting them prevents bad outliers."},
                ),
                "pair_neighbors": (
                    "INT",
                    {"default": 2, "min": 1, "max": 8, "step": 1,
                     "tooltip": "How many of each camera's nearest neighbours (by pose distance) to refine against. 2 = sequential-ish, 4-6 = denser triangulation."},
                ),
                "enabled": (
                    "BOOLEAN",
                    {"default": True, "label_on": "on", "label_off": "off",
                     "tooltip": "Master on/off. When off, GLB passes through unchanged."},
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("glb_path",)
    FUNCTION = "refine"
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
                "Mast3rEpipolarRefine needs opencv-python. Install with:\n"
                "  python_embeded\\python.exe -m pip install opencv-python\n"
                f"(original error: {e})"
            )

    def _collect_filelist(self, folder):
        files = []
        for f in os.listdir(folder):
            if f.lower().endswith(IMAGE_EXTS):
                files.append(os.path.join(folder, f))
        return sorted({os.path.normcase(os.path.abspath(f)) for f in files})

    def _build_cameras(self, scene, imgs_low, full_shapes, focals, poses):
        """Return per-image (K_full, P_full, R_w2c, t_w2c).

        K is intrinsic at FULL resolution, P = K @ [R|t] is the 3x4 projection
        matrix mapping world points to full-res pixel coords.
        """
        n = len(imgs_low)
        K_list, P_list, R_list, t_list = [], [], [], []
        for i in range(n):
            H_low, W_low = imgs_low[i].shape[:2]
            H_full, W_full = full_shapes[i]
            sx, sy = W_full / W_low, H_full / H_low
            f_low = float(np.asarray(focals[i]).reshape(-1)[0])
            fx_full = f_low * sx
            fy_full = f_low * sy
            K = np.array(
                [[fx_full, 0.0, W_full / 2.0],
                 [0.0, fy_full, H_full / 2.0],
                 [0.0, 0.0, 1.0]],
                dtype=np.float64,
            )
            # poses[i] is cam->world
            T_cw = np.linalg.inv(np.asarray(poses[i], dtype=np.float64))
            R, t = T_cw[:3, :3], T_cw[:3, 3]
            P = K @ np.hstack([R, t.reshape(3, 1)])
            K_list.append(K)
            P_list.append(P)
            R_list.append(R)
            t_list.append(t)
        return K_list, P_list, R_list, t_list

    def _fundamental(self, K_i, R_i, t_i, K_j, R_j, t_j):
        """Fundamental matrix mapping points in image i to epipolar lines in image j.

        l_j = F @ [x_i; y_i; 1] is a 3-vector (a, b, c) with the line a*x + b*y + c = 0.
        """
        # Relative pose from camera i to camera j: R_rel = R_j @ R_i.T, t_rel = t_j - R_rel @ t_i
        R_rel = R_j @ R_i.T
        t_rel = t_j - R_rel @ t_i
        t_x = np.array(
            [[0, -t_rel[2], t_rel[1]],
             [t_rel[2], 0, -t_rel[0]],
             [-t_rel[1], t_rel[0], 0]],
            dtype=np.float64,
        )
        E = t_x @ R_rel
        F = np.linalg.inv(K_j).T @ E @ np.linalg.inv(K_i)
        return F

    def _sample_patch(self, image, cx, cy, half):
        """Bilinear-sampled patch of shape (2*half+1, 2*half+1) centered at sub-pixel (cx, cy).

        Returns None if any sample falls outside the image.
        """
        H, W = image.shape
        x0 = cx - half
        y0 = cy - half
        size = 2 * half + 1
        if x0 < 0 or y0 < 0 or x0 + size >= W or y0 + size >= H:
            return None
        xs = np.arange(size, dtype=np.float64) + x0
        ys = np.arange(size, dtype=np.float64) + y0
        xi = xs.astype(np.int64)
        yi = ys.astype(np.int64)
        fx = (xs - xi).reshape(1, -1)
        fy = (ys - yi).reshape(-1, 1)
        # 4 neighbors
        I00 = image[yi[0]:yi[0] + size, xi[0]:xi[0] + size]
        # Above slicing assumes contiguous + integer step; bilinear sample at fractional offset:
        x_lo = xi
        x_hi = np.clip(xi + 1, 0, W - 1)
        y_lo = yi
        y_hi = np.clip(yi + 1, 0, H - 1)
        A = image[np.ix_(y_lo, x_lo)]
        B = image[np.ix_(y_lo, x_hi)]
        C = image[np.ix_(y_hi, x_lo)]
        D = image[np.ix_(y_hi, x_hi)]
        patch = (A * (1 - fx) * (1 - fy) + B * fx * (1 - fy)
                 + C * (1 - fx) * fy + D * fx * fy)
        return patch.astype(np.float64)

    def _ncc(self, a, b):
        a = a - a.mean()
        b = b - b.mean()
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na < 1e-9 or nb < 1e-9:
            return 0.0
        return float((a * b).sum() / (na * nb))

    def _refine_along_epipolar(
        self, src_patch, dst_image, dst_pred, line_normal, search_radius, half
    ):
        """Slide src_patch along the epipolar line near dst_pred, return refined (x, y, peak_ncc).

        line_normal is the 2-vector (a, b) normalised; the epipolar direction is the perpendicular.
        """
        a, b = line_normal[0], line_normal[1]
        ndir = np.sqrt(a * a + b * b)
        if ndir < 1e-9:
            return dst_pred[0], dst_pred[1], 0.0
        # Direction along the line: perpendicular to (a, b).
        dx, dy = -b / ndir, a / ndir

        offsets = np.arange(-search_radius, search_radius + 1, dtype=np.float64)
        scores = np.full(len(offsets), -1.0, dtype=np.float64)
        for k, d in enumerate(offsets):
            cx = dst_pred[0] + dx * d
            cy = dst_pred[1] + dy * d
            patch = self._sample_patch(dst_image, cx, cy, half)
            if patch is None:
                continue
            scores[k] = self._ncc(src_patch, patch)

        if not np.any(scores > -1.0):
            return dst_pred[0], dst_pred[1], 0.0
        best = int(np.argmax(scores))
        # Parabolic sub-pixel fit on the 3-sample peak neighbourhood.
        sub = 0.0
        if 0 < best < len(offsets) - 1 and scores[best - 1] > -1 and scores[best + 1] > -1:
            ya, yb, yc = scores[best - 1], scores[best], scores[best + 1]
            denom = 2.0 * (ya - 2.0 * yb + yc)
            if abs(denom) > 1e-9:
                sub = (ya - yc) / denom
                sub = float(np.clip(sub, -1.0, 1.0))
        d_refined = offsets[best] + sub
        cx_r = dst_pred[0] + dx * d_refined
        cy_r = dst_pred[1] + dy * d_refined
        return cx_r, cy_r, float(scores[best])

    def _triangulate(self, P1, P2, x1, x2):
        """DLT triangulation. P*: (3,4); x*: (2,) image coords. Returns world (3,)."""
        A = np.stack([
            x1[0] * P1[2] - P1[0],
            x1[1] * P1[2] - P1[1],
            x2[0] * P2[2] - P2[0],
            x2[1] * P2[2] - P2[1],
        ], axis=0)
        _, _, vt = np.linalg.svd(A)
        X = vt[-1]
        if abs(X[3]) < 1e-12:
            return None
        return (X[:3] / X[3]).astype(np.float64)

    def _pair_neighbors(self, poses, k):
        """For each camera, return indices of its k nearest neighbours by translation distance."""
        n = len(poses)
        centers = np.stack([np.asarray(p, dtype=np.float64)[:3, 3] for p in poses], axis=0)
        dists = np.linalg.norm(centers[:, None, :] - centers[None, :, :], axis=2)
        np.fill_diagonal(dists, np.inf)
        neighbors = np.argsort(dists, axis=1)[:, :k]
        return neighbors

    def refine(
        self,
        glb_path,
        scene,
        image_folder_path,
        samples_per_image,
        min_conf,
        patch_size,
        search_radius_px,
        ncc_min,
        pair_neighbors,
        enabled=True,
    ):
        if not enabled:
            print("Mast3rEpipolarRefine: disabled, passing GLB through unchanged")
            return (glb_path,)

        if not glb_path or not os.path.isfile(glb_path):
            raise FileNotFoundError(f"Mast3rEpipolarRefine: GLB not found: {glb_path!r}")
        if scene is None:
            raise ValueError("Mast3rEpipolarRefine: scene input is required.")
        if not image_folder_path or not os.path.isdir(image_folder_path):
            raise FileNotFoundError(f"Mast3rEpipolarRefine: folder not found: {image_folder_path!r}")
        if patch_size % 2 == 0:
            raise ValueError("patch_size must be odd")

        cv2 = self._require_cv2()
        from dust3r.utils.device import to_numpy

        imgs_low = scene.imgs
        pts3d_flat, _, confs_flat = to_numpy(scene.get_dense_pts3d(clean_depth=True))
        focals = to_numpy(scene.get_focals())
        poses = to_numpy(scene.get_im_poses())
        n = len(imgs_low)

        filelist = self._collect_filelist(image_folder_path)
        if len(filelist) < n:
            raise ValueError(
                f"Folder has {len(filelist)} images, scene needs {n}."
            )
        filelist = filelist[:n]

        # Load full-res grayscale (float32, for accurate NCC)
        full_images = []
        full_shapes = []
        for f in filelist:
            img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise RuntimeError(f"Mast3rEpipolarRefine: cannot read {f}")
            full_images.append(img.astype(np.float32))
            full_shapes.append(img.shape)

        K_list, P_list, R_list, t_list = self._build_cameras(
            scene, imgs_low, full_shapes, focals, poses
        )
        neighbors = self._pair_neighbors(poses, int(pair_neighbors))

        # Per-image scale factor low-res -> full-res
        scales = []
        for i in range(n):
            H_low, W_low = imgs_low[i].shape[:2]
            H_full, W_full = full_shapes[i]
            scales.append((W_full / W_low, H_full / H_low))

        half = int(patch_size) // 2
        sample_target = int(samples_per_image)
        ncc_min = float(ncc_min)

        # Reshape pts3d/confs to per-image grids
        pts3d_grids = []
        conf_grids = []
        for i in range(n):
            H_low, W_low = imgs_low[i].shape[:2]
            pts3d_grids.append(np.asarray(pts3d_flat[i], dtype=np.float64).reshape(H_low, W_low, 3))
            conf_grids.append(np.asarray(confs_flat[i], dtype=np.float64).reshape(H_low, W_low))

        all_refined = []   # refined 3-D points (world frame)
        all_colors = []    # RGB per point, uint8
        ncc_pass = 0
        ncc_total = 0
        skipped_oob = 0
        skipped_lowconf = 0

        t0 = time.time()
        for i in range(n):
            H_low, W_low = imgs_low[i].shape[:2]
            H_full, W_full = full_shapes[i]
            sx, sy = scales[i]

            # Sample top-conf pixels in image i
            conf_i = conf_grids[i]
            mask = conf_i > float(min_conf)
            ys, xs = np.where(mask)
            if len(ys) == 0:
                skipped_lowconf += 1
                continue
            if len(ys) > sample_target:
                idx = np.linspace(0, len(ys) - 1, sample_target).astype(np.int64)
                ys = ys[idx]
                xs = xs[idx]

            src_full = full_images[i]
            color_i_low = (np.clip(imgs_low[i], 0.0, 1.0) * 255.0).astype(np.uint8)

            for px_low, py_low in zip(xs, ys):
                X = pts3d_grids[i][py_low, px_low]
                if not np.all(np.isfinite(X)):
                    continue
                # Source patch at full-res
                px_full = (px_low + 0.5) * sx - 0.5
                py_full = (py_low + 0.5) * sy - 0.5
                src_patch = self._sample_patch(src_full, px_full, py_full, half)
                if src_patch is None:
                    skipped_oob += 1
                    continue

                Xh = np.append(X, 1.0)
                # Refine against each pair neighbour
                best_ncc = -1.0
                best_obs = None  # (j, x_j, y_j)
                for j in neighbors[i]:
                    j = int(j)
                    P_j = P_list[j]
                    proj = P_j @ Xh
                    if proj[2] <= 1e-6:
                        continue
                    pred_x = proj[0] / proj[2]
                    pred_y = proj[1] / proj[2]
                    H_j, W_j = full_shapes[j]
                    if pred_x < 0 or pred_x >= W_j or pred_y < 0 or pred_y >= H_j:
                        continue
                    # Epipolar line in image j: l = F @ x_i_full_homog
                    F_ij = self._fundamental(
                        K_list[i], R_list[i], t_list[i],
                        K_list[j], R_list[j], t_list[j],
                    )
                    line = F_ij @ np.array([px_full, py_full, 1.0])
                    cx_r, cy_r, peak = self._refine_along_epipolar(
                        src_patch, full_images[j], (pred_x, pred_y),
                        (line[0], line[1]), int(search_radius_px), half,
                    )
                    ncc_total += 1
                    if peak > best_ncc:
                        best_ncc = peak
                        best_obs = (j, cx_r, cy_r)

                if best_obs is None or best_ncc < ncc_min:
                    continue
                ncc_pass += 1
                # Triangulate (i, x_i_full) with (j, refined)
                j_b, x_jr, y_jr = best_obs
                X_refined = self._triangulate(
                    P_list[i], P_list[j_b],
                    np.array([px_full, py_full]),
                    np.array([x_jr, y_jr]),
                )
                if X_refined is None:
                    continue
                all_refined.append(X_refined)
                all_colors.append(color_i_low[py_low, px_low])

            elapsed = time.time() - t0
            print(
                f"  img {i+1}/{n}: cumulative refined={len(all_refined)} "
                f"(ncc-pass {ncc_pass}/{ncc_total}, t={elapsed:.1f}s)"
            )

        if len(all_refined) == 0:
            raise RuntimeError(
                "Mast3rEpipolarRefine: no points refined. Try lowering min_conf or ncc_min, "
                "or raising patch_size / samples_per_image."
            )

        verts = np.asarray(all_refined, dtype=np.float64)
        colors = np.asarray(all_colors, dtype=np.uint8)
        if colors.shape[1] == 3:
            alpha = np.full((len(colors), 1), 255, dtype=np.uint8)
            colors = np.hstack([colors, alpha])

        pc = trimesh.PointCloud(vertices=verts, colors=colors)
        out_scene = trimesh.Scene([pc])

        out_dir = os.path.dirname(glb_path) or "."
        out_name = f"scene_refined_{int(time.time())}.glb"
        out_path = os.path.join(out_dir, out_name)
        out_scene.export(out_path)
        elapsed = time.time() - t0
        print(
            f"Mast3rEpipolarRefine: refined {len(verts)} points in {elapsed:.1f}s "
            f"(ncc-pass {ncc_pass}/{ncc_total}={100*ncc_pass/max(ncc_total,1):.1f}%). "
            f"Saved -> {out_path}"
        )
        return (out_path,)


NODE_CLASS_MAPPINGS = {"Mast3rEpipolarRefine": Mast3rEpipolarRefine}
NODE_DISPLAY_NAME_MAPPINGS = {"Mast3rEpipolarRefine": "MASt3R Epipolar Sub-pixel Refine"}
