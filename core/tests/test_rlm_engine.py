"""Tests for RLM Engine — validates core claims from arXiv:2512.24601.

Test 1 (unit): REPL sandbox safety + code execution
Test 2 (unit): Parsing (find_code_blocks, find_final_answer)
Test 3 (integration): S-NIAH — find a magic phrase in ~100K chars of noise
Test 4 (integration): Aggregation — count items across chunked data

Integration tests require `claude` CLI available and make real LLM calls.
Run: ~/.local/bin/python3 -m pytest core/tests/test_rlm_engine.py -v
"""

import random

import pytest
from src.shared.rlm_engine import (
    REPLSandbox,
    RLMConfig,
    RLMEngine,
    find_code_blocks,
    find_final_answer,
)

# ── Unit Tests: REPL Sandbox ─────────────────────────────────────────────────


class TestREPLSandbox:
    def test_basic_execution(self):
        env = REPLSandbox()
        stdout, stderr = env.execute("x = 42\nprint(x)")
        assert "42" in stdout
        assert env.get_var("x") == 42

    def test_safe_builtins(self):
        env = REPLSandbox()
        stdout, stderr = env.execute("print(len([1,2,3]))")
        assert "3" in stdout

    def test_blocked_eval(self):
        env = REPLSandbox()
        _, stderr = env.execute("eval('1+1')")
        assert "Error" in stderr or "TypeError" in stderr

    def test_blocked_exec(self):
        env = REPLSandbox()
        _, stderr = env.execute("exec('x=1')")
        assert "Error" in stderr or "TypeError" in stderr

    def test_import_allowed(self):
        env = REPLSandbox()
        stdout, _ = env.execute("import math\nprint(math.pi)")
        assert "3.14" in stdout

    def test_protected_variable(self):
        env = REPLSandbox()
        env.inject("context", "hello", protected=True)
        # LLM might try to overwrite context
        env.execute('context = "overwritten"')
        # Protected variable should still be accessible
        assert env.get_var("context") is not None

    def test_list_vars(self):
        env = REPLSandbox()
        env.inject("llm_query", lambda p: "mock", protected=True)
        env.execute("x = 1\ny = 'hello'")
        user_vars = env.list_vars()
        assert "x" in user_vars
        assert "y" in user_vars
        assert "llm_query" not in user_vars  # protected

    def test_injected_function(self):
        env = REPLSandbox()
        env.inject("llm_query", lambda p, model=None: f"answer to: {p}", protected=True)
        stdout, _ = env.execute('result = llm_query("what is 2+2")\nprint(result)')
        assert "answer to: what is 2+2" in stdout

    def test_final_var(self):
        env = REPLSandbox()
        env.inject(
            "FINAL_VAR",
            lambda v: (
                setattr(env, "_final_answer", str(env.get_var(v) if isinstance(v, str) else v))
                or str(v)
            ),
            protected=True,
        )
        env.execute("my_answer = 'the result is 42'")
        env.execute("FINAL_VAR('my_answer')")
        assert env._final_answer is not None


# ── Unit Tests: Parsing ──────────────────────────────────────────────────────


class TestParsing:
    def test_find_code_blocks(self):
        text = "Let me check:\n```repl\nprint(context[:100])\n```\nNow I see."
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert "print(context[:100])" in blocks[0]

    def test_find_multiple_code_blocks(self):
        text = "```repl\nx = 1\n```\nThen:\n```repl\ny = 2\n```"
        blocks = find_code_blocks(text)
        assert len(blocks) == 2

    def test_no_code_blocks(self):
        text = "Just text, no code."
        assert find_code_blocks(text) == []

    def test_find_final_answer(self):
        text = "Based on analysis:\nFINAL(The magic number is 42)"
        answer = find_final_answer(text)
        assert answer == "The magic number is 42"

    def test_find_final_var(self):
        env = REPLSandbox()
        env.execute("my_result = 'success'")
        text = "FINAL_VAR(my_result)"
        answer = find_final_answer(text, env)
        assert answer == "success"

    def test_no_final(self):
        text = "I need to continue analyzing..."
        assert find_final_answer(text) is None

    def test_ignore_non_repl_code_blocks(self):
        text = "```python\nprint('not repl')\n```\n```repl\nprint('repl')\n```"
        blocks = find_code_blocks(text)
        assert len(blocks) == 1
        assert "repl" in blocks[0]


# ── Integration Tests ────────────────────────────────────────────────────────
# These make real LLM calls via `claude -p` and may take 30-120 seconds each.


def _generate_noise(length: int) -> str:
    """Generate random text that looks like paragraphs."""
    words = [
        "the",
        "quick",
        "brown",
        "fox",
        "jumps",
        "over",
        "lazy",
        "dog",
        "lorem",
        "ipsum",
        "dolor",
        "sit",
        "amet",
        "consectetur",
        "adipiscing",
        "elit",
        "sed",
        "do",
        "eiusmod",
        "tempor",
        "incididunt",
        "ut",
        "labore",
        "et",
        "dolore",
        "magna",
        "aliqua",
        "enim",
        "ad",
        "minim",
        "veniam",
        "quis",
        "nostrud",
        "exercitation",
        "ullamco",
        "laboris",
        "nisi",
        "aliquip",
        "ex",
        "ea",
        "commodo",
        "consequat",
        "duis",
        "aute",
        "irure",
        "in",
        "reprehenderit",
        "voluptate",
        "velit",
        "esse",
        "cillum",
        "fugiat",
        "nulla",
        "pariatur",
        "excepteur",
        "sint",
        "occaecat",
        "cupidatat",
        "non",
        "proident",
        "sunt",
        "culpa",
        "qui",
        "officia",
        "deserunt",
        "mollit",
        "anim",
        "est",
    ]
    rng = random.Random(42)
    result = []
    while len(" ".join(result)) < length:
        sentence_len = rng.randint(8, 20)
        sentence = " ".join(rng.choice(words) for _ in range(sentence_len))
        result.append(sentence.capitalize() + ".")
        if rng.random() < 0.15:
            result.append("\n")
    return " ".join(result)[:length]


@pytest.mark.integration
class TestSNIAH:
    """S-NIAH: Single Needle in a Haystack.

    Paper claim: RLM can find specific information in text far exceeding
    the model's context window by recursively chunking and querying.
    """

    def test_needle_in_100k(self):
        """Insert a unique phrase in ~100K chars of noise, ask RLM to find it."""
        noise_before = _generate_noise(50_000)
        needle = "THE_SECRET_PASSPHRASE_IS: ZephyrOmega7749"
        noise_after = _generate_noise(50_000)
        haystack = noise_before + "\n" + needle + "\n" + noise_after

        engine = RLMEngine(
            RLMConfig(
                model="sonnet",
                sub_model="haiku",
                max_depth=2,
                max_iterations=15,
                max_timeout_secs=180,
                verbose=True,
            )
        )

        result = engine.completion(
            prompt="Find the secret passphrase hidden in the context. Return ONLY the passphrase value.",
            context=haystack,
        )

        print("\n=== S-NIAH Result ===")
        print(f"Status: {result.status}")
        print(f"Response: {result.response}")
        print(f"Iterations: {result.iterations}")
        print(f"LLM calls: {result.usage.total_calls}")
        print(f"Time: {result.execution_time_secs:.1f}s")
        print(f"Trajectory: {result.trajectory}")

        assert result.status == "ok", f"Expected ok, got {result.status}"
        assert "ZephyrOmega7749" in result.response, (
            f"Needle not found in response: {result.response[:200]}"
        )

    def test_needle_in_chunked_context(self):
        """Same test but with context provided as a list of chunks."""
        chunks = []
        needle_chunk_idx = 7  # hide in chunk 7

        for i in range(15):
            if i == needle_chunk_idx:
                chunk = (
                    _generate_noise(5_000)
                    + "\nSECRET_CODE=Avalanche2024\n"
                    + _generate_noise(5_000)
                )
            else:
                chunk = _generate_noise(10_000)
            chunks.append(chunk)

        engine = RLMEngine(
            RLMConfig(
                model="sonnet",
                sub_model="haiku",
                max_depth=2,
                max_iterations=15,
                max_timeout_secs=180,
                verbose=True,
            )
        )

        result = engine.completion(
            prompt="Find the SECRET_CODE value hidden in the context chunks. Return ONLY the code value.",
            context=chunks,
        )

        print("\n=== Chunked S-NIAH Result ===")
        print(f"Status: {result.status}")
        print(f"Response: {result.response}")
        print(f"Iterations: {result.iterations}")
        print(f"LLM calls: {result.usage.total_calls}")
        print(f"Time: {result.execution_time_secs:.1f}s")

        assert result.status == "ok"
        assert "Avalanche2024" in result.response


@pytest.mark.integration
class TestAggregation:
    """Aggregation test: count specific items across many chunks.

    Paper claim: RLM can aggregate information from distributed data
    by chunking, querying per chunk, and combining results.
    """

    def test_count_animals(self):
        """Hide animal names across chunks, ask RLM to count total unique animals."""
        rng = random.Random(123)
        animals_per_chunk = {
            0: ["cat", "dog"],
            2: ["elephant", "cat", "parrot"],
            5: ["dog", "whale", "tiger"],
            8: ["parrot", "snake", "cat"],
            11: ["lion", "whale"],
        }
        all_unique = set()
        for v in animals_per_chunk.values():
            all_unique.update(v)

        chunks = []
        for i in range(13):
            noise = _generate_noise(3_000)
            if i in animals_per_chunk:
                animal_text = f"\nAnimals spotted in area {i}: {', '.join(animals_per_chunk[i])}\n"
                noise = noise[:1500] + animal_text + noise[1500:]
            chunks.append(noise)

        engine = RLMEngine(
            RLMConfig(
                model="sonnet",
                sub_model="haiku",
                max_depth=2,
                max_iterations=15,
                max_timeout_secs=600,
                verbose=True,
            )
        )

        result = engine.completion(
            prompt=(
                "Search through all context chunks and find every mention of "
                "'Animals spotted in area'. List all UNIQUE animal names found "
                "across all areas. Return the count of unique animals."
            ),
            context=chunks,
        )

        print("\n=== Aggregation Result ===")
        print(f"Status: {result.status}")
        print(f"Response: {result.response}")
        print(f"Expected unique animals: {len(all_unique)} — {sorted(all_unique)}")
        print(f"Iterations: {result.iterations}")
        print(f"LLM calls: {result.usage.total_calls}")
        print(f"Time: {result.execution_time_secs:.1f}s")

        assert result.status == "ok"
        # Should find the correct count (7 unique animals)
        assert str(len(all_unique)) in result.response or "7" in result.response


# ── Quick smoke test (no LLM calls) ─────────────────────────────────────────


class TestEngineUnit:
    def test_config_defaults(self):
        config = RLMConfig()
        assert config.model == "sonnet"
        assert config.max_depth == 2
        assert config.max_iterations == 20

    def test_engine_creation(self):
        engine = RLMEngine(RLMConfig(model="haiku"))
        assert engine.depth == 0
        assert engine.config.model == "haiku"

    def test_context_metadata_string(self):
        from src.shared.rlm_engine import _build_context_metadata

        meta = _build_context_metadata("hello world")
        assert "11" in meta  # 11 chars

    def test_context_metadata_list(self):
        from src.shared.rlm_engine import _build_context_metadata

        meta = _build_context_metadata(["abc", "defgh"])
        assert "2 chunks" in meta
        assert "8" in meta  # total chars
