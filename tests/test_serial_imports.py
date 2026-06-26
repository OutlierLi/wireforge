import importlib.util
from pathlib import Path


def test_project_does_not_shadow_pyserial_import_name():
    spec = importlib.util.find_spec("serial")
    if spec is None or spec.origin is None:
        return

    project_root = Path(__file__).resolve().parent.parent
    origin = Path(spec.origin).resolve()
    assert not origin.is_relative_to(project_root), origin
