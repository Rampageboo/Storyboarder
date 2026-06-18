from __future__ import annotations

import contextlib
import io
import logging
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import logging_config


class _ListHandler(logging.Handler):
    """Captures log records for assertion in tests."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class TestLoggingConfig(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._log_file = Path(self._tmp) / "test.log"
        self._pkg_logger = logging.getLogger("storyboard_tool")
        self._saved_handlers = list(self._pkg_logger.handlers)
        self._pkg_logger.handlers.clear()

    def tearDown(self) -> None:
        for h in self._pkg_logger.handlers:
            h.close()
        self._pkg_logger.handlers.clear()
        self._pkg_logger.handlers.extend(self._saved_handlers)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_setup_logging_adds_handlers(self) -> None:
        logging_config.setup_logging(log_file=self._log_file)
        self.assertGreater(len(self._pkg_logger.handlers), 0)

    def test_setup_logging_idempotent(self) -> None:
        logging_config.setup_logging(log_file=self._log_file)
        count = len(self._pkg_logger.handlers)
        logging_config.setup_logging(log_file=self._log_file)
        self.assertEqual(len(self._pkg_logger.handlers), count)

    def test_log_file_is_written(self) -> None:
        logging_config.setup_logging(log_file=self._log_file)
        self._pkg_logger.warning("test_sentinel_message")
        for h in self._pkg_logger.handlers:
            h.flush()
        self.assertTrue(self._log_file.exists())
        self.assertIn("test_sentinel_message", self._log_file.read_text(encoding="utf-8"))


class TestNoRawTracebackInResponse(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._app = api_module.create_app(Path(self._tmp))
        self._client = TestClient(self._app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_bad_project_path_no_traceback_in_detail(self) -> None:
        response = _quiet(
            lambda: self._client.post(
                "/api/project/open",
                json={"project_json_path": "/nonexistent/nowhere/project.json"},
            )
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json().get("detail", "")
        self.assertNotIn("Traceback", detail)
        self.assertNotIn("  File ", detail)

    def test_export_failure_no_traceback_in_detail(self) -> None:
        _quiet(lambda: self._client.post("/api/project/new", json={"path": self._tmp}))

        def _raise(*args, **kwargs) -> None:
            raise RuntimeError("intentional export error for test")

        with patch("storyboard_tool.service_exports._export_storyboard_pdf", _raise):
            response = _quiet(
                lambda: self._client.post("/api/export/pdf", json={"layout": "two_per_page"})
            )

        self.assertEqual(response.status_code, 500)
        detail = response.json().get("detail", "")
        self.assertNotIn("Traceback", detail)
        self.assertNotIn("  File ", detail)
        self.assertIn("intentional export error for test", detail)


class TestBackendExceptionLogging(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._app = api_module.create_app(Path(self._tmp))
        self._client = TestClient(self._app, raise_server_exceptions=False)
        self._handler = _ListHandler()
        self._handler.setLevel(logging.ERROR)
        self._pkg_logger = logging.getLogger("storyboard_tool")
        self._pkg_logger.addHandler(self._handler)

    def tearDown(self) -> None:
        self._pkg_logger.removeHandler(self._handler)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _error_records(self) -> list[logging.LogRecord]:
        return [r for r in self._handler.records if r.levelno >= logging.ERROR]

    def test_save_project_failure_is_logged(self) -> None:
        _quiet(lambda: self._client.post("/api/project/new", json={"path": self._tmp}))
        self._handler.records.clear()

        with patch("storyboard_tool.project_manager.save_project", side_effect=OSError("disk full")):
            _quiet(lambda: self._client.post("/api/project/save"))

        self.assertTrue(self._error_records(), "Expected at least one ERROR log when save fails")

    def test_project_open_failure_is_logged(self) -> None:
        self._handler.records.clear()
        _quiet(
            lambda: self._client.post(
                "/api/project/open",
                json={"project_json_path": "/nonexistent/project.json"},
            )
        )
        self.assertTrue(self._error_records(), "Expected at least one ERROR log when project open fails")

    def test_blender_open_failure_is_logged(self) -> None:
        _quiet(lambda: self._client.post("/api/project/new", json={"path": self._tmp}))
        self._handler.records.clear()

        with patch(
            "storyboard_tool.project_manager.open_blender_scene",
            side_effect=RuntimeError("no blender"),
        ):
            _quiet(lambda: self._client.post("/api/project/scene3d/open-blender"))

        self.assertTrue(self._error_records(), "Expected at least one ERROR log for Blender failure")

    def test_export_failure_is_logged(self) -> None:
        _quiet(lambda: self._client.post("/api/project/new", json={"path": self._tmp}))
        self._handler.records.clear()

        with patch(
            "storyboard_tool.service_exports._export_storyboard_pdf",
            side_effect=RuntimeError("export crash"),
        ):
            _quiet(lambda: self._client.post("/api/export/pdf", json={"layout": "two_per_page"}))

        self.assertTrue(self._error_records(), "Expected at least one ERROR log for export failure")


if __name__ == "__main__":
    unittest.main()
