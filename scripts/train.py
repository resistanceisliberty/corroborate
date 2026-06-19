"""Train + calibrate the scorer, emit the reliability diagram.

Usage: uv run python scripts/train.py

Labels events vs USGS ground truth, fits the calibrated model, writes scores back,
and saves the model + reliability artifacts (see corroborate.calibrate).
"""

from __future__ import annotations

from corroborate.calibrate import train_and_calibrate


def main() -> None:
    train_and_calibrate()


if __name__ == "__main__":
    main()
