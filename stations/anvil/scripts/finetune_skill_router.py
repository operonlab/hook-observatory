#!/Users/joneshong/.local/bin/python3
"""Fine-tune Qwen3-Embedding for behaviour-aligned skill routing.

Uses InfoNCE contrastive loss on (anchor, positive, negative) triples
exported by export_routing_training.py.

Base model: mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ (already deployed)
Framework: MLX (Apple Silicon optimized)

Usage:
    python finetune_skill_router.py --data ~/.claude/data/skill-router/training.jsonl

Prerequisites:
    - Training data from: export_routing_training.py
    - MLX framework: pip install mlx mlx-lm
    - Minimum 500 training pairs recommended
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_DATA = str(Path.home() / ".claude" / "data" / "skill-router" / "training.jsonl")
DEFAULT_OUTPUT = str(Path.home() / ".venvs" / "omlx" / "models" / "skill-router-v1")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune embedding model for skill routing")
    parser.add_argument("--data", default=DEFAULT_DATA, help="Training JSONL")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output model dir")
    parser.add_argument("--epochs", type=int, default=3, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")
    parser.add_argument("--temperature", type=float, default=0.07, help="InfoNCE temperature")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(
            f"Training data not found: {data_path}\nRun export_routing_training.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load training data
    pairs = []
    with open(data_path) as f:
        for line in f:
            if line.strip():
                pairs.append(json.loads(line))

    print(f"Loaded {len(pairs)} training pairs", file=sys.stderr)

    if len(pairs) < 100:
        print(
            "Too few pairs for meaningful fine-tuning (need 100+). "
            "Collect more invocation data first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Split train/eval
    split_idx = int(len(pairs) * 0.9)
    train_pairs = pairs[:split_idx]
    eval_pairs = pairs[split_idx:]

    print(f"Train: {len(train_pairs)}, Eval: {len(eval_pairs)}", file=sys.stderr)

    try:
        import mlx.core as mx  # noqa: F401
        import mlx.nn as nn  # noqa: F401
    except ImportError:
        print(
            "MLX not available. Install: pip install mlx mlx-lm\n"
            "This script requires Apple Silicon with MLX framework.",
            file=sys.stderr,
        )
        sys.exit(1)

    # TODO: Implement MLX fine-tuning loop
    # This is a scaffold — full implementation requires:
    # 1. Load base model (Qwen3-Embedding-0.6B-4bit-DWQ)
    # 2. InfoNCE contrastive loss
    # 3. Training loop with gradient accumulation
    # 4. Evaluation on held-out pairs (Recall@1, @5, @10)
    # 5. Save fine-tuned weights
    #
    # Reference: Memento-Skills paper Section 2.3 (InfoNCE routing)
    # Loss: L = -log( exp(s(d,q)/tau) / sum_Q exp(s(d_k,q)/tau) )

    print(
        "\n=== Fine-tuning scaffold ===\n"
        f"Base model: mlx-community/Qwen3-Embedding-0.6B-4bit-DWQ\n"
        f"Training pairs: {len(train_pairs)}\n"
        f"Eval pairs: {len(eval_pairs)}\n"
        f"Epochs: {args.epochs}\n"
        f"Batch size: {args.batch_size}\n"
        f"Learning rate: {args.lr}\n"
        f"Temperature (tau): {args.temperature}\n"
        f"Output: {args.output}\n"
        "\nFull training loop not yet implemented.\n"
        "Run export_routing_training.py periodically to accumulate data.\n"
        "When 1000+ pairs available, implement the MLX training loop.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
