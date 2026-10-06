"""Logger facade, logger service, message, exporter, and formatting types.

The LoggerService provides structured logging with configurable exporters.
It supports multiple severity levels, printf-style formatting, and ANSI colors.

Key features:
- Named loggers via ctx.logger(name)
- Severity methods: error, info, warn, debug
- Configurable exporters for different output destinations
- Printf-style formatting with custom formatters
- Message buffering for later inspection
"""

from __future__ import annotations

import json
import re
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

from cordis.utils import symbols

if TYPE_CHECKING:
    from cordis.context import Context
    from cordis.fiber import Fiber


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

LoggerType = Literal['error', 'info', 'warn', 'debug']
"""Logger method name and severity category."""


class LoggerLevel(IntEnum):
    """Numeric severity used when exporters decide whether to emit a message."""
    ERROR = 0
    INFO = 1
    WARN = 2
    DEBUG = 3


@dataclass
class Message:
    """Structured log record delivered to exporters."""
    sn: int
    ts: float
    name: str
    type: LoggerType
    level: int
    args: list[Any]
    fiber: weakref.ref | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Formatter(Protocol):
    """Formatter used to resolve a printf-style placeholder."""
    def __call__(self, value: Any, exporter: Exporter, message: Message) -> Any: ...


class Exporter(Protocol):
    """Sink that receives structured log messages."""
    colors: int | bool | None
    max_length: int | None
    levels: dict[str, int] | None
    formatters: dict[str, Formatter] | None

    def export(self, message: Message) -> None: ...


# ---------------------------------------------------------------------------
# Default formatters
# ---------------------------------------------------------------------------

def _format_s(value: Any, exporter: Exporter, message: Message) -> str:
    return str(value)


def _format_d(value: Any, exporter: Exporter, message: Message) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _format_f(value: Any, exporter: Exporter, message: Message) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _format_o(value: Any, exporter: Exporter, message: Message) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _format_c(value: Any, exporter: Exporter, message: Message) -> str:
    return ''


def _format_C(value: Any, exporter: Exporter, message: Message) -> str:
    code = Logger.color_code(message.name, getattr(exporter, 'colors', None))
    return Logger.color(exporter, code, value)


DEFAULT_FORMATTERS: dict[str, Formatter] = {
    's': _format_s,
    'd': _format_d,
    'i': _format_d,
    'f': _format_f,
    'o': _format_o,
    'O': _format_o,
    'c': _format_c,
    'C': _format_C,
}


# ANSI color palettes
C16 = [6, 2, 3, 4, 5, 1]
C256 = [
    20, 21, 26, 27, 32, 33, 38, 39, 40, 41, 42, 43, 44, 45, 56, 57, 62,
    63, 68, 69, 74, 75, 76, 77, 78, 79, 80, 81, 92, 93, 98, 99, 112, 113,
    129, 134, 135, 148, 149, 160, 161, 162, 163, 164, 165, 166, 167, 168,
    169, 170, 171, 172, 173, 178, 179, 184, 185, 196, 197, 198, 199, 200,
    201, 202, 203, 204, 205, 206, 207, 208, 209, 214, 215, 220, 221,
]


# ---------------------------------------------------------------------------
# Logger class
# ---------------------------------------------------------------------------

class Logger:
    """Logger facade for one named subsystem.

    Mirrors ts_version Logger class.
    """

    def __init__(self, options: dict[str, Any], service: LoggerService) -> None:
        self.name: str = options.get('name', 'unknown')
        self.level: int = options.get('level', LoggerLevel.INFO)
        self.meta: dict[str, Any] = options.get('meta', {})
        self._service = service

        # Create severity methods
        self.error = self._method('error', LoggerLevel.ERROR)
        self.info = self._method('info', LoggerLevel.INFO)
        self.warn = self._method('warn', LoggerLevel.WARN)
        self.debug = self._method('debug', LoggerLevel.DEBUG)

    def _method(self, type_: LoggerType, level: int) -> Callable[..., None]:
        """Create a severity method."""
        def method(format_str: Any, *params: Any) -> None:
            # Handle Error objects specially
            if len(params) == 0 and isinstance(format_str, Exception):
                if hasattr(format_str, '__cause__') and format_str.__cause__:
                    self.error(format_str.__cause__)
                elif hasattr(format_str, 'errors'):
                    # AggregateError-like
                    for error in format_str.errors:
                        self.error(error)
                return

            sn = self._service._sn_message + 1
            self._service._sn_message = sn
            ts = time.time()

            for exporter in self._service.exporters.values():
                levels = getattr(exporter, 'levels', None) or {}
                target_level = (
                    levels.get(self.name) or
                    levels.get('default') or
                    self.level or
                    LoggerLevel.INFO
                )
                if target_level < level:
                    continue

                message = Message(
                    sn=sn,
                    ts=ts,
                    type=type_,
                    level=level,
                    name=self.name,
                    args=[format_str] + list(params),
                    fiber=self.meta.get('fiber'),
                    meta=self.meta,
                )
                exporter.export(message)

        return method

    @staticmethod
    def color(exporter: Exporter, code: int, value: Any, decoration: str = '') -> str:
        """Apply ANSI color to a value."""
        colors = getattr(exporter, 'colors', None)
        if not colors:
            return str(value)

        if isinstance(colors, bool):
            colors = 1 if colors else 0

        if code < 8:
            color_code = f'3{code}'
        else:
            color_code = f'38;5;{code}'

        if colors >= 2:
            color_code += decoration

        return f'\033[{color_code}m{value}\033[0m'

    @staticmethod
    def color_code(name: str, level: int | bool | None = None) -> int:
        """Compute a color code for a logger name."""
        hash_val = 0
        for char in name:
            hash_val = ((hash_val << 3) - hash_val) + ord(char) + 13
            hash_val = hash_val & 0xFFFFFFFF  # Keep as 32-bit
            if hash_val > 0x7FFFFFFF:
                hash_val -= 0x100000000

        if not level:
            colors: list[int] = []
        elif level >= 2:
            colors = C256
        else:
            colors = C16

        if not colors:
            return 0

        return colors[abs(hash_val) % len(colors)]

    @staticmethod
    def format(exporter: Exporter, message: Message) -> str:
        """Format a message for display."""
        args = list(message.args)

        # Handle Error as first argument
        if args and isinstance(args[0], Exception):
            error = args[0]
            args[0] = str(error) if not hasattr(error, '__traceback__') else str(error)
            args.insert(0, '%s')
        elif args and not isinstance(args[0], str):
            args.insert(0, '%o')

        if not args:
            return ''

        format_str = args.pop(0)
        if not isinstance(format_str, str):
            format_str = str(format_str)

        # Process format specifiers
        def replace_format(match: re.Match) -> str:
            char = match.group(1)
            if char == '%':
                return '%'
            formatter = getattr(exporter, 'formatters', {}).get(char) or DEFAULT_FORMATTERS.get(char)
            if formatter and args:
                value = args.pop(0)
                return str(formatter(value, exporter, message))
            return match.group(0)

        result = re.sub(r'%([a-zA-Z%])', replace_format, format_str)

        # Append remaining args
        o_formatter = getattr(exporter, 'formatters', {}).get('o') or DEFAULT_FORMATTERS.get('o')
        for arg in args:
            if isinstance(arg, (dict, list, tuple)):
                arg = o_formatter(arg, exporter, message) if o_formatter else str(arg)
            result += ' ' + str(arg)

        # Apply max length
        max_length = getattr(exporter, 'max_length', 10240) or 10240
        lines = result.split('\n')
        truncated = []
        for line in lines:
            if len(line) > max_length:
                truncated.append(line[:max_length] + '...')
            else:
                truncated.append(line)

        return '\n'.join(truncated)


# ---------------------------------------------------------------------------
# LoggerService
# ---------------------------------------------------------------------------

class LoggerService:
    """Built-in logging service.

    Call ctx.logger() to create a named logger, or call ctx.logger.info()
    directly to log with the current fiber-derived name.

    Mirrors ts_version LoggerService.
    """

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.buffer_size = 1000
        self.buffer: list[Message] = []
        self._sn_message = 0
        self._sn_exporter = 0
        self.exporters: dict[int, Exporter] = {}

        # Set up tracker
        tracker = {
            'property': 'ctx',
            'noShadow': True,
        }
        object.__setattr__(self, symbols.tracker, tracker)

        # Register default buffer exporter
        self.exporter(BufferExporter(self))

        # Make the service callable
        self._make_callable()

    def _make_callable(self) -> None:
        """Make this service callable: ctx.logger(name)."""
        if callable(self):
            return  # Already wrapped

        original_class = self.__class__

        class CallableLoggerService(original_class):
            def __call__(self_inner, name: str | None = None) -> Logger:
                return self._invoke(name)

        self.__class__ = CallableLoggerService

    def _invoke(self, name: str | None = None) -> Logger:
        """Create a named logger facade."""
        config = self._resolve_config()
        fiber = self.ctx.fiber

        if name is None:
            name = config.get('name')
        if name is None and fiber is not None:
            name = fiber.name

        return Logger({
            'name': name or 'unknown',
            'level': config.get('level'),
            'meta': {'fiber': weakref.ref(fiber) if fiber else None},
        }, self)

    def _resolve_config(self) -> dict[str, Any]:
        """Resolve intercept config for logger by walking parent chain."""
        configs: list[dict[str, Any]] = []

        ctx: Any = self.ctx
        while ctx is not None:
            intercept = ctx._intercept_map
            if 'logger' in intercept:
                configs.insert(0, intercept['logger'])
            ctx = getattr(ctx, '_parent', None)

        result: dict[str, Any] = {}
        for cfg in configs:
            if isinstance(cfg, dict):
                result.update(cfg)
        return result

    def exporter(self, exp: Exporter) -> Callable[[], None]:
        """Register an exporter and dispose it with the current fiber.

        Mirrors ts_version LoggerService.exporter().
        """
        def do_register() -> Callable[[], None]:
            self._sn_exporter += 1
            id_ = self._sn_exporter
            self.exporters[id_] = exp

            def dispose() -> None:
                self.exporters.pop(id_, None)

            return dispose

        # Register as effect on fiber
        fiber = self.ctx.fiber
        if fiber is not None:
            return fiber.effect(do_register, 'ctx.logger.exporter()')
        else:
            return do_register()

    # Severity methods that delegate to a default logger
    def error(self, *args: Any) -> None:
        self._invoke().error(*args)

    def info(self, *args: Any) -> None:
        self._invoke().info(*args)

    def warn(self, *args: Any) -> None:
        self._invoke().warn(*args)

    def debug(self, *args: Any) -> None:
        self._invoke().debug(*args)


# ---------------------------------------------------------------------------
# BufferExporter
# ---------------------------------------------------------------------------

class BufferExporter:
    """Default exporter that buffers messages in memory."""

    def __init__(self, service: LoggerService) -> None:
        self.service = service
        self.colors: int | bool = 3
        self.max_length: int = 10240
        self.levels: dict[str, int] | None = None
        self.formatters: dict[str, Formatter] | None = None

    def export(self, message: Message) -> None:
        self.service.buffer.append(message)
        if len(self.service.buffer) > self.service.buffer_size:
            self.service.buffer = self.service.buffer[-self.service.buffer_size:]
