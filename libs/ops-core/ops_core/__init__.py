"""Shared operator protocol, unified pipe, and combinators.

The GCD (greatest common factor) of audio-ops, image-ops, and video-ops.
Sync equivalents of core/src/shared/reactive.py (async).

Two execution modes in ONE class:
    Batch:     of/from_file → pipe() → execute()        (one ctx in, one out)
    Streaming: from_iter/from_* → pipe() → subscribe()  (many in, many out)

All three media libs inherit from BasePipe:
    class AudioPipe(BasePipe):
        def of(cls, audio, sr): ...
        def from_file(cls, path): ...
        def from_chunks(cls, gen, sr): ...   # streaming source
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Op Protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class Op(Protocol):
    """Pure function transform on a ctx dict — the atomic unit of all pipes.

    Sync __call__ because all media operators are CPU-bound (no async I/O).
    """

    @property
    def name(self) -> str: ...

    @property
    def input_keys(self) -> tuple[str, ...]: ...

    @property
    def output_keys(self) -> tuple[str, ...]: ...

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


# ── StreamOp Protocol ────────────────────────────────────────────────────


@runtime_checkable
class StreamOp(Protocol):
    """Transform on a stream of ctx dicts — generator in, generator out."""

    @property
    def name(self) -> str: ...

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]: ...


# ── BasePipe (unified batch + streaming) ─────────────────────────────────


class BasePipe:
    """Unified pipe — batch or streaming, decided by source.

    Batch sources (of, from_file) → execute() returns one ctx.
    Streaming sources (from_iter, from_chunks) → subscribe()/collect().

    RxJS-style: Source → pipe() → consume.
    """

    def __init__(self) -> None:
        self._ops: list[Op | StreamOp] = []
        # Batch mode
        self._initial_ctx: dict[str, Any] | None = None
        # Streaming mode
        self._source: Iterable[dict[str, Any]] | None = None

    @property
    def _is_streaming(self) -> bool:
        return self._source is not None

    # ── Creation helpers (used by subclass factories) ────────────────

    @classmethod
    def _create_batch(cls, ctx: dict[str, Any]) -> BasePipe:
        """Internal: create batch pipe with pre-loaded ctx."""
        p = cls()
        p._initial_ctx = ctx
        return p

    @classmethod
    def _create_stream(cls, source: Iterable[dict[str, Any]]) -> BasePipe:
        """Internal: create streaming pipe from generator."""
        p = cls()
        p._source = source
        return p

    # Backward compat alias
    _create = _create_batch

    @classmethod
    def from_iter(cls, source: Iterable[dict[str, Any]]) -> BasePipe:
        """from() — create stream from any iterable of ctx dicts."""
        return cls._create_stream(source)

    # ── Operators ────────────────────────────────────────────────────

    def pipe(self, *ops: Op | StreamOp) -> BasePipe:
        self._ops.extend(ops)
        return self

    def compile(self, initial_keys: set[str] | None = None) -> list[str]:
        """Static key validation (batch mode only)."""
        available = set(initial_keys) if initial_keys else set()
        if self._initial_ctx:
            available |= set(self._initial_ctx.keys())
        missing: list[str] = []
        for op in self._ops:
            if not hasattr(op, "input_keys"):
                continue  # stream-only ops skip validation
            for key in op.input_keys:
                if key not in available:
                    missing.append(f"{op.name}: requires '{key}'")
            for key in op.output_keys:
                available.add(key)
        return missing

    # ── Batch consumption ────────────────────────────────────────────

    def execute(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        """execute() — run batch pipeline, return one ctx."""
        ctx = ctx if ctx is not None else (self._initial_ctx or {})
        for op in self._ops:
            ctx = op(ctx)
        return ctx

    # ── Streaming consumption ────────────────────────────────────────

    def _build_chain(self) -> Iterable[dict[str, Any]]:
        """Build the generator chain — lazy, nothing runs until consumed."""
        stream: Iterable[dict[str, Any]] = self._source or []
        for op in self._ops:
            if isinstance(op, StreamOp) and not isinstance(op, Op):
                stream = op(stream)
            elif hasattr(op, "input_keys"):
                stream = _lift_to_stream(op, stream)
            else:
                stream = op(stream)
        return stream

    def subscribe(
        self,
        callback: Callable[[dict[str, Any]], None],
    ) -> int:
        """subscribe() — consume stream, call callback for each item.

        Returns the number of items processed.
        """
        count = 0
        for ctx in self._build_chain():
            callback(ctx)
            count += 1
        return count

    def collect(self) -> list[dict[str, Any]]:
        """toArray() — collect all stream items into a list."""
        return list(self._build_chain())

    def first(self) -> dict[str, Any] | None:
        """first() — get the first item or None."""
        for ctx in self._build_chain():
            return ctx
        return None

    def __iter__(self) -> Iterable[dict[str, Any]]:
        """Allow direct iteration over the stream."""
        return iter(self._build_chain())

    # ── Repr ─────────────────────────────────────────────────────────

    def _repr_source(self) -> str:
        """Override in subclass for domain-specific repr."""
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        if self._is_streaming:
            return "stream -> "
        return ""

    def __repr__(self) -> str:
        source = self._repr_source()
        names = " -> ".join(getattr(op, "name", op.__class__.__name__) for op in self._ops)
        return f"{self.__class__.__name__}({source}{names})"

    def __len__(self) -> int:
        return len(self._ops)


def _lift_to_stream(
    op: Op,
    source: Iterable[dict[str, Any]],
) -> Iterable[dict[str, Any]]:
    """Lift a batch Op (ctx→ctx) into a stream transform (map)."""
    for ctx in source:
        yield op(ctx)


# Backward compat aliases
BasePipeline = BasePipe
BaseStream = BasePipe


# ── Batch Combinators ────────────────────────────────────────────────────


class ParallelOp:
    """Fork ctx to multiple ops, execute concurrently, merge results.

    RxJS equivalent: forkJoin(op1(ctx), op2(ctx))
    """

    def __init__(self, *ops: Op, name: str | None = None):
        if len(ops) < 2:
            raise ValueError("ParallelOp requires at least 2 operators")
        self._ops = ops
        self._name = name or f"parallel({'+'.join(op.name for op in ops)})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return tuple(sorted({k for op in self._ops for k in op.input_keys}))

    @property
    def output_keys(self) -> tuple[str, ...]:
        return tuple(sorted({k for op in self._ops for k in op.output_keys}))

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=len(self._ops)) as pool:
            futures = [pool.submit(op, copy.deepcopy(ctx)) for op in self._ops]
            results = [f.result() for f in futures]

        output_keys = {k for op in self._ops for k in op.output_keys}
        merged = dict(ctx)
        for result in results:
            for key in result:
                if key not in ctx or key in output_keys:
                    merged[key] = result[key]
        return merged

    def __repr__(self) -> str:
        return self._name


class TapOp:
    """Side-effect observer — runs callback without modifying ctx."""

    name = "tap"
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()

    def __init__(
        self,
        fn: Callable[[dict[str, Any]], None],
        name: str = "tap",
    ):
        self._fn = fn
        self.name = name  # type: ignore[assignment]

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self._fn(ctx)
        return ctx

    def __repr__(self) -> str:
        return self.name


class ConditionalOp:
    """Conditional branch — run then_op if predicate is true, else else_op."""

    def __init__(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        then_op: Op,
        else_op: Op | None = None,
        *,
        name: str = "conditional",
    ):
        self._predicate = predicate
        self._then_op = then_op
        self._else_op = else_op
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        keys: set[str] = set(self._then_op.input_keys)
        if self._else_op:
            keys |= set(self._else_op.input_keys)
        return tuple(sorted(keys))

    @property
    def output_keys(self) -> tuple[str, ...]:
        keys: set[str] = set(self._then_op.output_keys)
        if self._else_op:
            keys |= set(self._else_op.output_keys)
        return tuple(sorted(keys))

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if self._predicate(ctx):
            return self._then_op(ctx)
        elif self._else_op:
            return self._else_op(ctx)
        return ctx

    def __repr__(self) -> str:
        then_name = self._then_op.name
        else_name = self._else_op.name if self._else_op else "pass"
        return f"{self._name}({then_name}|{else_name})"


class CatchOp:
    """Error recovery wrapper — catches exceptions and runs fallback."""

    def __init__(
        self,
        op: Op,
        *,
        fallback_ctx: dict[str, Any] | None = None,
        handler: Callable[[dict, Exception], dict] | None = None,
        name: str | None = None,
    ):
        self._op = op
        self._fallback = fallback_ctx
        self._handler = handler
        self._name = name or f"catch({op.name})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return self._op.input_keys

    @property
    def output_keys(self) -> tuple[str, ...]:
        return self._op.output_keys

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._op(ctx)
        except Exception as e:
            logger.warning("CatchOp: %s failed: %s", self._op.name, e)
            if self._handler:
                return self._handler(ctx, e)
            if self._fallback:
                return {**ctx, **self._fallback}
            return ctx

    def __repr__(self) -> str:
        return self._name


class DelayOp:
    """Pause execution for a fixed duration — rate-limit external API calls."""

    name = "delay"
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()

    def __init__(self, seconds: float = 1.0, name: str = "delay"):
        self._seconds = seconds
        self.name = name  # type: ignore[assignment]

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import time

        time.sleep(self._seconds)
        return ctx

    def __repr__(self) -> str:
        return f"delay({self._seconds}s)"


class RetryOp:
    """Retry a failing op up to N times with exponential backoff."""

    def __init__(
        self,
        op: Op,
        *,
        count: int = 3,
        backoff: float = 1.0,
        name: str | None = None,
    ):
        self._op = op
        self._count = count
        self._backoff = backoff
        self._name = name or f"retry({op.name}, {count}x)"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return self._op.input_keys

    @property
    def output_keys(self) -> tuple[str, ...]:
        return self._op.output_keys

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import time

        last_err: Exception | None = None
        for attempt in range(self._count):
            try:
                return self._op(ctx)
            except Exception as e:
                last_err = e
                if attempt < self._count - 1:
                    wait = self._backoff * (2**attempt)
                    logger.warning(
                        "RetryOp: %s attempt %d/%d failed: %s (wait %.1fs)",
                        self._op.name,
                        attempt + 1,
                        self._count,
                        e,
                        wait,
                    )
                    time.sleep(wait)
        raise last_err  # type: ignore[misc]

    def __repr__(self) -> str:
        return self._name


class FinalizeOp:
    """Cleanup callback that runs after an op, regardless of success/failure."""

    def __init__(
        self,
        op: Op,
        cleanup: Callable[[dict[str, Any]], None],
        *,
        name: str | None = None,
    ):
        self._op = op
        self._cleanup = cleanup
        self._name = name or f"finalize({op.name})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return self._op.input_keys

    @property
    def output_keys(self) -> tuple[str, ...]:
        return self._op.output_keys

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._op(ctx)
        finally:
            try:
                self._cleanup(ctx)
            except Exception as e:
                logger.warning("FinalizeOp: cleanup failed: %s", e)

    def __repr__(self) -> str:
        return self._name


class TimeoutOp:
    """Abort an op if it exceeds the specified duration."""

    def __init__(
        self,
        op: Op,
        *,
        seconds: float = 30.0,
        name: str | None = None,
    ):
        self._op = op
        self._seconds = seconds
        self._name = name or f"timeout({op.name}, {seconds}s)"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return self._op.input_keys

    @property
    def output_keys(self) -> tuple[str, ...]:
        return self._op.output_keys

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._op, ctx)
            try:
                return future.result(timeout=self._seconds)
            except TimeoutError:
                raise TimeoutError(f"{self._op.name} exceeded {self._seconds}s timeout") from None

    def __repr__(self) -> str:
        return self._name


# ── Stream Combinators ───────────────────────────────────────────────────


class BufferCount:
    """Accumulate N items, emit as a merged batch ctx."""

    name = "buffer-count"

    def __init__(self, count: int, merge_key: str | None = None):
        self._count = count
        self._merge_key = merge_key

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        buffer: list[dict[str, Any]] = []
        for ctx in source:
            buffer.append(ctx)
            if len(buffer) >= self._count:
                yield self._merge(buffer)
                buffer = []
        if buffer:
            yield self._merge(buffer)

    def _merge(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        import numpy as np

        if self._merge_key:
            arrays = [it[self._merge_key] for it in items if self._merge_key in it]
            merged = dict(items[-1])
            if arrays and isinstance(arrays[0], np.ndarray):
                merged[self._merge_key] = np.concatenate(arrays)
            return merged

        merged = {}
        for it in items:
            for k, v in it.items():
                if isinstance(v, np.ndarray) and k in merged and isinstance(merged[k], np.ndarray):
                    merged[k] = np.concatenate([merged[k], v])
                else:
                    merged[k] = v
        merged["_buffer_size"] = len(items)
        return merged

    def __repr__(self) -> str:
        return f"buffer-count({self._count})"


class BufferTime:
    """Accumulate items for a time window, emit as batch."""

    name = "buffer-time"

    def __init__(self, seconds: float, merge_key: str | None = None):
        self._seconds = seconds
        self._bc = BufferCount(count=999999, merge_key=merge_key)

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        import time

        buffer: list[dict[str, Any]] = []
        window_start = time.monotonic()

        for ctx in source:
            buffer.append(ctx)
            if time.monotonic() - window_start >= self._seconds:
                if buffer:
                    yield self._bc._merge(buffer)
                    buffer = []
                window_start = time.monotonic()
        if buffer:
            yield self._bc._merge(buffer)

    def __repr__(self) -> str:
        return f"buffer-time({self._seconds}s)"


class Window:
    """Sliding window of N items — emit overlapping batches."""

    name = "window"

    def __init__(self, size: int, merge_key: str | None = None):
        self._size = size
        self._bc = BufferCount(count=size, merge_key=merge_key)

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        from collections import deque

        window: deque[dict[str, Any]] = deque(maxlen=self._size)
        for ctx in source:
            window.append(ctx)
            if len(window) == self._size:
                yield self._bc._merge(list(window))

    def __repr__(self) -> str:
        return f"window({self._size})"


class Scan:
    """Running accumulation — emit intermediate results."""

    name = "scan"

    def __init__(
        self,
        accumulator: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        seed: dict[str, Any] | None = None,
    ):
        self._acc_fn = accumulator
        self._seed = seed or {}

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        acc = dict(self._seed)
        for ctx in source:
            acc = self._acc_fn(acc, ctx)
            yield dict(acc)

    def __repr__(self) -> str:
        return "scan"


class Filter:
    """Only pass through items matching predicate."""

    name = "filter"

    def __init__(self, predicate: Callable[[dict[str, Any]], bool]):
        self._predicate = predicate

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        for ctx in source:
            if self._predicate(ctx):
                yield ctx

    def __repr__(self) -> str:
        return "filter"


class Take:
    """Take first N items then stop."""

    name = "take"

    def __init__(self, count: int):
        self._count = count

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        for i, ctx in enumerate(source):
            if i >= self._count:
                break
            yield ctx

    def __repr__(self) -> str:
        return f"take({self._count})"


class Skip:
    """Skip first N items."""

    name = "skip"

    def __init__(self, count: int):
        self._count = count

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        for i, ctx in enumerate(source):
            if i >= self._count:
                yield ctx

    def __repr__(self) -> str:
        return f"skip({self._count})"


class Throttle:
    """Emit at most once per interval — drop intermediate items."""

    name = "throttle"

    def __init__(self, seconds: float):
        self._seconds = seconds

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        import time

        last_emit = 0.0
        for ctx in source:
            now = time.monotonic()
            if now - last_emit >= self._seconds:
                yield ctx
                last_emit = now

    def __repr__(self) -> str:
        return f"throttle({self._seconds}s)"


class Debounce:
    """Emit only after a silence period."""

    name = "debounce"

    def __init__(self, seconds: float):
        self._seconds = seconds

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        import time

        pending: dict[str, Any] | None = None
        pending_time = 0.0

        for ctx in source:
            now = ctx.get("_ts", time.monotonic())
            if pending is not None and now - pending_time >= self._seconds:
                yield pending
            pending = ctx
            pending_time = now

        if pending is not None:
            yield pending

    def __repr__(self) -> str:
        return f"debounce({self._seconds}s)"


class DistinctUntilChanged:
    """Skip consecutive duplicates based on a key function."""

    name = "distinct-until-changed"

    def __init__(
        self,
        key_fn: Callable[[dict[str, Any]], Any] | None = None,
    ):
        self._key_fn = key_fn

    def __call__(
        self,
        source: Iterable[dict[str, Any]],
    ) -> Iterable[dict[str, Any]]:
        _sentinel = object()
        prev = _sentinel
        for ctx in source:
            key = self._key_fn(ctx) if self._key_fn else ctx
            if key != prev:
                yield ctx
                prev = key

    def __repr__(self) -> str:
        return "distinct-until-changed"


# ── Parser Utilities ─────────────────────────────────────────────────────

_PARALLEL_RE = re.compile(r"^\[(.+)]$")


def split_top_level(spec: str, sep: str = ",") -> list[str]:
    """Split by sep, but respect [...] groups."""
    tokens: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in spec:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == sep and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def parse_single(token: str, make_op: Callable[[str, dict], Op]) -> Op:
    """Parse a single operator token like 'normalize:target_db=-6'."""
    if ":" in token:
        name, params_str = token.split(":", 1)
        kwargs: dict[str, Any] = {}
        for pair in params_str.split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                try:
                    kwargs[k.strip()] = float(v.strip())
                except ValueError:
                    kwargs[k.strip()] = v.strip()
        return make_op(name.strip(), kwargs)
    return make_op(token.strip(), {})


def parse_spec(
    spec: str,
    make_op: Callable[[str, dict], Op],
    sep: str = ",",
) -> list[Op]:
    """Parse operator spec string with [a+b] parallel group support."""
    ops: list[Op] = []
    for token in split_top_level(spec, sep):
        token = token.strip()
        if not token:
            continue
        parallel_match = _PARALLEL_RE.match(token)
        if parallel_match:
            inner = parallel_match.group(1)
            sub_ops = [parse_single(t.strip(), make_op) for t in inner.split("+") if t.strip()]
            ops.append(ParallelOp(*sub_ops))
        else:
            ops.append(parse_single(token, make_op))
    return ops
