import logging
from datetime import UTC, datetime


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        from core.middleware import get_request_id

        record.request_id = get_request_id()
        return True


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", "unknown")
        timestamp = datetime.now(UTC).isoformat()
        base = (
            f"[{record.levelname}] {timestamp} "
            f"request_id={request_id} "
            f"logger={record.name} "
            f"msg={record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            base += "\n" + self.formatStack(record.stack_info)
        return base
