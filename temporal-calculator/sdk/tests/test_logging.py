import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from platform_sdk.logging import JsonFormatter, configure_logging  # noqa: E402


def _make_record(msg="hello", extra=None, exc_info=None):
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


class TestJsonFormatter:
    def test_basic_fields_present(self):
        formatter = JsonFormatter()
        record = _make_record("hello world")
        parsed = json.loads(formatter.format(record))

        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert "timestamp" in parsed

    def test_extra_fields_are_merged(self):
        formatter = JsonFormatter()
        record = _make_record("processing", extra={"task_queue": "add-task-queue"})
        parsed = json.loads(formatter.format(record))

        assert parsed["task_queue"] == "add-task-queue"

    def test_exception_info_included(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = _make_record("failed", exc_info=exc_info)
        parsed = json.loads(formatter.format(record))

        assert "exception" in parsed
        assert "boom" in parsed["exception"]

    def test_output_is_single_line(self):
        formatter = JsonFormatter()
        record = _make_record("multi\nline\nmessage")
        formatted = formatter.format(record)
        # json.dumps escapes newlines within the string value, so the
        # overall formatted output must still be exactly one line.
        assert "\n" not in formatted


class TestConfigureLogging:
    def test_sets_level_from_argument(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_is_idempotent_no_duplicate_handlers(self):
        configure_logging(level="INFO")
        configure_logging(level="INFO")
        assert len(logging.getLogger().handlers) == 1

    def test_defaults_to_info_when_no_env_or_arg(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        configure_logging()
        assert logging.getLogger().level == logging.INFO
