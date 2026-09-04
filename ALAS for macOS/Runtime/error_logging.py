"""文件只记录错误，终端和界面保留实时输出。"""
import logging


# 同时处理已有和后续新增的文件日志处理器。
def install_error_logging():
    if getattr(logging.Logger.addHandler, "_alas_error_only", False):
        return
    original = logging.Logger.addHandler

    def add_handler(logger, handler):
        if isinstance(handler, logging.FileHandler) or type(handler).__name__ == "RichFileHandler":
            handler.addFilter(lambda record: record.levelno >= logging.ERROR)
        original(logger, handler)

    add_handler._alas_error_only = True
    logging.Logger.addHandler = add_handler
    for logger in [logging.getLogger()] + list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger):
            for handler in logger.handlers[:]:
                add_handler(logger, handler)
