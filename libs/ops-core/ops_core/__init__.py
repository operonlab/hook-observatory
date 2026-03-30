"""Shared operator protocol, pipeline base, and combinators.

The GCD (greatest common factor) of audio-ops, image-ops, and video-ops.
Sync equivalents of core/src/shared/reactive.py (async).

All three media libs inherit from this base:
    from ops_core import Op, BasePipeline, ParallelOp, TapOp, ...

    class AudioPipeline(BasePipeline["AudioOp"]):
        @classmethod
        def of(cls, audio, sr): ...
        @classmethod
        def from_file(cls, path): ...
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Op Protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class Op(Protocol):
    """Pure function transform on a ctx dict — the atomic unit of all pipelines.

    Sync __call__ because all media operators are CPU-bound (no async I/O).
    """

    @property
    def name(self) -> str: ...

    @property
    def input_keys(self) -> tuple[str, ...]: ...

    @property
    def output_keys(self) -> tuple[str, ...]: ...

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


# ── BasePipeline ─────────────────────────────────────────────────────────


class BasePipeline:
    """Composable operator chain with static key validation.

    Subclasses add domain-specific creation methods (of, from_file).
    RxJS-style: Creation → pipe() → execute().
    """

    def __init__(self) -> None:
        self._ops: list[Op] = []
        self._initial_ctx: dict[str, Any] | None = None

    # ── Creation helper (used by subclass of/from_file) ──────────────

    @classmethod
    def _create(cls, ctx: dict[str, Any]) -> BasePipeline:
        """Internal factory — create a pipeline with pre-loaded ctx."""
        p = cls()
        p._initial_ctx = ctx
        return p

    # ── Operators ────────────────────────────────────────────────────────

    def pipe(self, *ops: Op) -> BasePipeline:
        self._ops.extend(ops)
        return self

    def compile(self, initial_keys: set[str] | None = None) -> list[str]:
        available = set(initial_keys) if initial_keys else set()
        if self._initial_ctx:
            available |= set(self._initial_ctx.keys())
        missing: list[str] = []
        for op in self._ops:
            for key in op.input_keys:
                if key not in available:
                    missing.append(f"{op.name}: requires '{key}'")
            for key in op.output_keys:
                available.add(key)
        return missing

    def execute(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = ctx if ctx is not None else (self._initial_ctx or {})
        for op in self._ops:
            ctx = op(ctx)
        return ctx

    def _repr_source(self) -> str:
        """Override in subclass for domain-specific repr."""
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        return ""

    def __repr__(self) -> str:
        source = self._repr_source()
        names = " -> ".join(op.name for op in self._ops)
        return f"{self.__class__.__name__}({source}{names})"

    def __len__(self) -> int:
        return len(self._ops)


# ── Combinators ──────────────────────────────────────────────────────────


class ParallelOp:
    """Fork ctx to multiple ops, execute concurrently, merge results.

    RxJS equivalent: forkJoin(op1(ctx), op2(ctx))
    Uses ThreadPoolExecutor because numpy/ONNX ops release the GIL.

    Usage:
        pipeline.pipe(ParallelOp(DiarizeOp(), EmotionOp()))
        # or via spec: "denoise,[diarize+emotion]"
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
    """Side-effect observer — runs callback without modifying ctx.

    RxJS equivalent: tap(x => console.log(x))
    """

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
    """Conditional branch — run then_op if predicate is true, else else_op.

    RxJS equivalent: iif(() => condition, thenObs$, elseObs$)
    """

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
    """Error recovery wrapper — catches exceptions and runs fallback.

    RxJS equivalent: catchError(err => of(fallbackValue))
    """

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


# ── DelayOp (RxJS: delay — rate-limit between ops) ──────────────────────


class DelayOp:
    """Pause execution for a fixed duration — rate-limit external API calls.

    RxJS equivalent: delay(ms)
    """

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


# ── RetryOp (RxJS: retry — retry N times on failure) ────────────────────


class RetryOp:
    """Retry a failing op up to N times with optional backoff.

    RxJS equivalent: retry({ count: 3, delay: 1000 })
    """

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


# ── FinalizeOp (RxJS: finalize — cleanup after pipeline) ────────────────


class FinalizeOp:
    """Cleanup callback that runs after an op, regardless of success/failure.

    RxJS equivalent: finalize(() => cleanup())
    """

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


# ── TimeoutOp (RxJS: timeout — abort if op exceeds duration) ────────────


class TimeoutOp:
    """Abort an op if it exceeds the specified duration.

    RxJS equivalent: timeout(ms)
    Uses a thread to enforce the deadline on CPU-bound ops.
    """

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
    """Parse operator spec string with [a+b] parallel group support.

    Args:
        spec: e.g. "denoise,normalize,[diarize+emotion]"
        make_op: Factory fn(name, kwargs) -> Op (from each lib's registry)
        sep: Token separator. Defaults to comma.
    """
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
