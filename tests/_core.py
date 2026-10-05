"""Load addon/nova_fx/core.py without importing the Blender package."""
import importlib.util, os
_p = os.path.join(os.path.dirname(__file__), "..", "addon", "nova_fx", "core.py")
_spec = importlib.util.spec_from_file_location("nova_core_standalone", _p)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
