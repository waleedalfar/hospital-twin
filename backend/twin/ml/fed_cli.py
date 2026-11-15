"""`make fed-train`: federated training across the three hospitals from the command line (PROMPT.md §7.6).

Reads the training rows `make train` saved in data/ml/. With --json it prints one JSON object per line (a `round`
event after each federated round and a final `done` event), which is how the API shows live progress in the UI.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from twin.common.config import REPO_ROOT, get_settings
from twin.common.logging import configure_logging
from twin.ml.fed_model import FED_VERSION
from twin.ml.federated import LOCAL_EPOCHS, ROUNDS, SEED, gate_failures, run_federated, save_result
from twin.ml.model import MODELS_DIR

logger = logging.getLogger(__name__)
TRAIN_ROWS = REPO_ROOT / "data" / "ml" / "train.parquet"


def main(argv: list[str] | None = None, rows_path: Path = TRAIN_ROWS, models_dir: Path = MODELS_DIR) -> int:
    parser = argparse.ArgumentParser(description="Federated training of the deterioration model")
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--local-epochs", type=int, default=LOCAL_EPOCHS)
    parser.add_argument("--json", action="store_true", help="print machine-readable progress lines")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())

    def emit(event: dict[str, object]) -> None:
        if args.json:
            print(json.dumps(event), flush=True)

    if not rows_path.is_file():
        message = f"No training rows at {rows_path}. Run `make train` first."
        emit({"event": "error", "message": message})
        print(message, file=sys.stderr)
        return 1
    rows = pd.read_parquet(rows_path)
    try:
        result = run_federated(
            rows,
            args.rounds,
            args.local_epochs,
            SEED,
            lambda rnd, total, auroc: emit({"event": "round", "round": rnd, "rounds": total, "auroc": auroc}),
        )
    except (ValueError, RuntimeError) as error:
        logger.exception("Federated training failed")
        emit({"event": "error", "message": str(error)})
        print(f"Federated training failed: {error}", file=sys.stderr)
        return 1
    save_result(result, models_dir)
    problems = gate_failures(result.metrics)
    c = result.comparison
    summary = (
        f"federated {c['federated']['test']['auroc']:.3f} | centralized {c['centralized']['test']['auroc']:.3f} | "
        f"local-only mean {c['local_only']['mean_auroc']:.3f} (test AUROC)"
    )
    emit({"event": "done", "version": FED_VERSION, "gates_ok": not problems, "problems": problems, "summary": summary})
    if not args.json:
        print(f"Federated model {FED_VERSION}: {summary}")
    for problem in problems:
        print(f"QUALITY GATE FAILED: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover - process entry point; main() is tested directly
    sys.exit(main())
