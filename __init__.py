import os
import subprocess
import threading
import sys
import locale
import traceback


def handle_stream(stream, prefix):
    stream.reconfigure(encoding=locale.getpreferredencoding(), errors='replace')
    for msg in stream:
        if prefix == '[!]' and ('it/s]' in msg or 's/it]' in msg) and ('%|' in msg or 'it [' in msg):
            if msg.startswith('100%'):
                print('\r' + msg, end="", file=sys.stderr),
            else:
                print('\r' + msg[:-1], end="", file=sys.stderr),
        else:
            if prefix == '[!]':
                print(prefix, msg, end="", file=sys.stderr)
            else:
                print(prefix, msg, end="")


def run_script(cmd, cwd='.'):
    if len(cmd) > 0 and cmd[0].startswith("#"):
        print(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
        return 0

    process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

    stdout_thread = threading.Thread(target=handle_stream, args=(process.stdout, ""))
    stderr_thread = threading.Thread(target=handle_stream, args=(process.stderr, "[!]"))

    stdout_thread.start()
    stderr_thread.start()

    stdout_thread.join()
    stderr_thread.join()

    return process.wait()


# Try to import nodes
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

try:
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
    print("## MASt3R: Nodes loaded successfully")
except Exception as e:
    print(f"## MASt3R: First import attempt failed: {e}")
    traceback.print_exc()
    
    my_path = os.path.dirname(__file__)
    requirements_path = os.path.join(my_path, "requirements.txt")

    print(f"## MASt3R: Installing dependencies from {requirements_path}")

    run_script([sys.executable, '-s', '-m', 'pip', 'install', '-r', requirements_path])

    try:
        from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
        print("## MASt3R: Nodes loaded successfully after installing dependencies")
    except Exception as e2:
        print(f"## [ERROR] MASt3R: Second import attempt failed: {e2}")
        traceback.print_exc()
        
        print(f"## [ERROR] MASt3R: Attempting to reinstall dependencies using --user flag")
        run_script([sys.executable, '-s', '-m', 'pip', 'install', '--user', '-r', requirements_path])

        try:
            from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
            print("## MASt3R: Nodes loaded successfully after --user install")
        except Exception as e3:
            print(f"## [ERROR] MASt3R: All import attempts failed")
            print(f"## [ERROR] MASt3R: Final error: {e3}")
            traceback.print_exc()
            print("## [ERROR] MASt3R: Please check:")
            print("##   1. That all dependencies are installed (torch, scipy, trimesh, roma, etc.)")
            print("##   2. That the mast3r and dust3r folders are present in the ComfyUI-mast3r directory")
            print("##   3. Check the console output above for specific import errors")

try:
    from .glb_viewer import (
        NODE_CLASS_MAPPINGS as _VIEWER_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _VIEWER_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_VIEWER_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_VIEWER_DISPLAY_MAPPINGS)
    print("## MASt3R: GLB staging node loaded")
except Exception as _viewer_err:
    print(f"## MASt3R: GLB staging node failed to load: {_viewer_err}")

try:
    from .multi_image import (
        NODE_CLASS_MAPPINGS as _MULTI_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _MULTI_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_MULTI_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_MULTI_DISPLAY_MAPPINGS)
    print("## MASt3R: Multi-image batch node loaded")
except Exception as _multi_err:
    print(f"## MASt3R: Multi-image batch node failed to load: {_multi_err}")

try:
    from .folder_input import (
        NODE_CLASS_MAPPINGS as _FOLDER_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _FOLDER_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_FOLDER_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_FOLDER_DISPLAY_MAPPINGS)
    print("## MASt3R: Folder input node loaded")
except Exception as _folder_err:
    print(f"## MASt3R: Folder input node failed to load: {_folder_err}")

try:
    from .mesh_filter import (
        NODE_CLASS_MAPPINGS as _MESH_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _MESH_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_MESH_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_MESH_DISPLAY_MAPPINGS)
    print("## MASt3R: Mesh filter node loaded")
except Exception as _mesh_err:
    print(f"## MASt3R: Mesh filter node failed to load: {_mesh_err}")

try:
    from .advanced_viewer import (
        NODE_CLASS_MAPPINGS as _ADV_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _ADV_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_ADV_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_ADV_DISPLAY_MAPPINGS)
    print("## MASt3R: Advanced 3D viewer node loaded")
except Exception as _adv_err:
    print(f"## MASt3R: Advanced 3D viewer node failed to load: {_adv_err}")

try:
    from .solidify import (
        NODE_CLASS_MAPPINGS as _SOLID_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _SOLID_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_SOLID_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_SOLID_DISPLAY_MAPPINGS)
    print("## MASt3R: Solidify node loaded")
except Exception as _solid_err:
    print(f"## MASt3R: Solidify node failed to load: {_solid_err}")

try:
    from .charuco_scale import (
        NODE_CLASS_MAPPINGS as _CHARUCO_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _CHARUCO_DISPLAY_MAPPINGS,
    )
    NODE_CLASS_MAPPINGS.update(_CHARUCO_CLASS_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS.update(_CHARUCO_DISPLAY_MAPPINGS)
    print("## MASt3R: ChArUco scale calibration node loaded")
except Exception as _charuco_err:
    print(f"## MASt3R: ChArUco scale calibration node failed to load: {_charuco_err}")

WEB_DIRECTORY = "./web"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
