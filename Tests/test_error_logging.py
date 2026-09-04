import importlib.util
import io
import logging
from pathlib import Path
import tempfile
import unittest

path = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime/error_logging.py"
spec = importlib.util.spec_from_file_location("error_logging", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ErrorLoggingTests(unittest.TestCase):
    # 错误落盘且实时输出不变
    def test_errors_only_with_tracebacks_and_future_handlers(self):
        original = logging.Logger.addHandler
        logger = logging.Logger("test", logging.DEBUG)
        try:
            module.install_error_logging()
            module.install_error_logging()
            with tempfile.TemporaryDirectory() as directory:
                file = Path(directory) / "errors.log"
                disk = logging.FileHandler(file)
                screen = io.StringIO()
                logger.addHandler(disk)
                logger.addHandler(logging.StreamHandler(screen))
                logger.info("normal")
                logger.warning("warning")
                logger.error("first error")
                try:
                    raise ValueError("second error")
                except ValueError:
                    logger.exception("failure")
                disk.close()
                saved = file.read_text()
                self.assertNotIn("normal", saved)
                self.assertNotIn("warning", saved)
                self.assertIn("first error", saved)
                self.assertIn("Traceback", saved)
                self.assertIn("second error", saved)
                self.assertIn("normal", screen.getvalue())
                rich_output = io.StringIO()
                RichFileHandler = type("RichFileHandler", (logging.StreamHandler,), {})
                logger.handlers.clear()
                logger.addHandler(RichFileHandler(rich_output))
                logger.info("normal")
                logger.critical("critical error")
                self.assertEqual(rich_output.getvalue(), "critical error\n")
        finally:
            logging.Logger.addHandler = original
