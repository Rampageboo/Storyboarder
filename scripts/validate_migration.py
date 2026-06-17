#!/usr/bin/env python3
"""Post-migration validation: routes, runtime static files, and static tree shape."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from storyboard_tool import api as api_module  # noqa: E402

STATIC = ROOT / "storyboard_tool" / "web" / "static"
REQUIRED_STATIC = {
    STATIC / "runtime" / "scene3d.js",
    STATIC / "runtime" / "reference_model_preview.js",
    STATIC / "vendor" / "three" / "three.module.js",
    STATIC / "favicon.svg",
}
FORBIDDEN_STATIC = {
    STATIC / "index.html",
    STATIC / "app.js",
    STATIC / "scene3d.js",
    STATIC / "reference_model_preview.js",
    STATIC / "app",
    STATIC / "core",
}
FORBIDDEN_WEB = {
    ROOT / "storyboard_tool" / "web" / "index.html",
    ROOT / "storyboard_tool" / "web" / "ref_segment.html",
}


def check_static_tree() -> list[str]:
    errors: list[str] = []
    for path in REQUIRED_STATIC:
        if not path.is_file():
            errors.append(f"missing required static file: {path.relative_to(ROOT)}")
    for path in FORBIDDEN_STATIC:
        if path.exists():
            errors.append(f"legacy static path still present: {path.relative_to(ROOT)}")
    for path in FORBIDDEN_WEB:
        if path.exists():
            errors.append(f"legacy HTML still present: {path.relative_to(ROOT)}")
    return errors


def check_routes() -> list[str]:
    errors: list[str] = []
    react_index = ROOT / "storyboard_tool" / "web" / "dist" / "index.html"
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(api_module.create_app(Path(tmp)), raise_server_exceptions=False)
        expectations: list[tuple[str, int, str | None]] = [
            ("/legacy", 404, None),
            ("/ref-video", 302, "/"),
            ("/ref-segment", 302, "/"),
            ("/static/runtime/scene3d.js", 200, None),
            ("/static/scene3d.js", 404, None),
        ]
        if react_index.is_file():
            expectations.extend([("/", 200, None), ("/react", 200, None)])
        for route, status, location in expectations:
            response = client.get(route, follow_redirects=False)
            if response.status_code != status:
                errors.append(f"{route}: expected {status}, got {response.status_code}")
            elif location is not None and response.headers.get("location") != location:
                errors.append(f"{route}: expected Location {location!r}, got {response.headers.get('location')!r}")
    return errors


def main() -> int:
    errors = check_static_tree() + check_routes()
    if errors:
        print("Migration validation FAILED:")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("Migration validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
