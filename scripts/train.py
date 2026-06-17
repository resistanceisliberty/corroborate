"""Train + calibrate the scorer, emit the reliability diagram.

Usage: uv run python scripts/train.py

TODO (M3): wires together cluster -> label vs ground_truth -> features ->
calibrate.train_and_calibrate(). Currently delegates to the stub.
"""

from __future__ import annotations

from corroborate.calibrate import train_and_calibrate


def main() -> None:
    train_and_calibrate()


if __name__ == "__main__":
    main()
