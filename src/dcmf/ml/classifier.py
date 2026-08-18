"""Deterministic Random Forest baseline for guided-action classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import (
    GroupShuffleSplit,
    StratifiedKFold,
    cross_val_predict,
)
from sklearn.pipeline import Pipeline


RANDOM_SEED = 42
NON_FEATURE_COLUMNS = {
    "experiment_id",
    "experiment_name",
    "action",
    "trial_number",
    "start_monotonic_ns",
    "end_monotonic_ns",
    "automatic_end",
}


@dataclass(slots=True, frozen=True)
class TrainingResult:
    """Output artifacts from one baseline training run."""

    output_directory: Path
    status: str
    model_path: Path | None
    metrics_path: Path
    predictions_path: Path | None
    feature_importance_path: Path | None


def _pipeline(feature_columns: list[str]) -> Pipeline:
    preprocessing = ColumnTransformer(
        [
            (
                "numeric",
                SimpleImputer(strategy="median"),
                feature_columns,
            )
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    classifier = RandomForestClassifier(
        n_estimators=400,
        class_weight="balanced_subsample",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    return Pipeline(
        [("preprocess", preprocessing), ("classifier", classifier)]
    )


def _write_confusion_plot(
    matrix: np.ndarray,
    labels: list[str],
    path: Path,
) -> None:
    figure, axis = plt.subplots(
        figsize=(max(6.0, len(labels) * 0.9), max(5.0, len(labels) * 0.75))
    )
    image = axis.imshow(matrix, interpolation="nearest", cmap="Blues")
    figure.colorbar(image, ax=axis)
    axis.set(
        xticks=np.arange(len(labels)),
        yticks=np.arange(len(labels)),
        xticklabels=labels,
        yticklabels=labels,
        xlabel="Predicted action",
        ylabel="True action",
        title="DCMF guided-action confusion matrix",
    )
    plt.setp(axis.get_xticklabels(), rotation=45, ha="right")
    threshold = matrix.max() / 2.0 if matrix.size and matrix.max() else 0.0
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            axis.text(
                column,
                row,
                str(int(matrix[row, column])),
                ha="center",
                va="center",
                color="white" if matrix[row, column] > threshold else "black",
            )
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def train_random_forest(
    dataset_csv: Path,
    output_directory: Path,
) -> TrainingResult:
    """Train and evaluate a baseline model without leaking identifiers."""
    dataset_csv = Path(dataset_csv)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    metrics_path = output_directory / "metrics.json"
    data = pd.read_csv(dataset_csv)

    base_metrics: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_csv": str(dataset_csv),
        "random_seed": RANDOM_SEED,
        "row_count": int(len(data)),
    }
    required = {"action", "experiment_id"}
    missing = sorted(required - set(data.columns))
    if missing or data.empty:
        base_metrics.update(
            {
                "status": "insufficient_data",
                "reason": (
                    "Dataset is empty or missing required columns: "
                    + ", ".join(missing)
                ),
            }
        )
        metrics_path.write_text(
            json.dumps(base_metrics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return TrainingResult(
            output_directory, "insufficient_data", None, metrics_path, None, None
        )

    numeric_columns = [
        column
        for column in data.columns
        if column not in NON_FEATURE_COLUMNS
        and pd.api.types.is_numeric_dtype(data[column])
        and not data[column].isna().all()
    ]
    labels = data["action"].astype(str)
    groups = data["experiment_id"].astype(str)
    class_names = sorted(labels.unique().tolist())
    base_metrics.update(
        {
            "class_count": len(class_names),
            "classes": class_names,
            "experiment_count": int(groups.nunique()),
            "feature_count": len(numeric_columns),
            "feature_columns": numeric_columns,
        }
    )
    if len(class_names) < 2 or not numeric_columns:
        base_metrics.update(
            {
                "status": "insufficient_data",
                "reason": "At least two action classes and one numeric feature are required.",
            }
        )
        metrics_path.write_text(
            json.dumps(base_metrics, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return TrainingResult(
            output_directory, "insufficient_data", None, metrics_path, None, None
        )

    features = data[numeric_columns]
    predictions: np.ndarray
    evaluation_method: str
    train_rows: int | None = None
    test_rows: int | None = None

    if groups.nunique() >= 2:
        splitter = GroupShuffleSplit(
            n_splits=1,
            test_size=0.25,
            random_state=RANDOM_SEED,
        )
        train_index, test_index = next(splitter.split(features, labels, groups))
        train_classes = set(labels.iloc[train_index].astype(str))
        test_classes = set(labels.iloc[test_index].astype(str))
        unseen_test_classes = sorted(test_classes - train_classes)
        if len(train_classes) < 2 or unseen_test_classes:
            base_metrics.update(
                {
                    "status": "insufficient_data",
                    "reason": (
                        "The session-held-out split cannot train a meaningful "
                        "multi-class model. Collect every guided action in each "
                        "of several independent experiments."
                    ),
                    "train_classes": sorted(train_classes),
                    "test_classes": sorted(test_classes),
                    "unseen_test_classes": unseen_test_classes,
                }
            )
            metrics_path.write_text(
                json.dumps(base_metrics, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return TrainingResult(
                output_directory, "insufficient_data", None, metrics_path, None, None
            )
        evaluation_model = _pipeline(numeric_columns)
        evaluation_model.fit(features.iloc[train_index], labels.iloc[train_index])
        predictions = evaluation_model.predict(features.iloc[test_index])
        truth = labels.iloc[test_index].to_numpy()
        prediction_rows = data.iloc[test_index][
            ["experiment_id", "experiment_name", "action", "trial_number"]
        ].copy()
        evaluation_method = "group_holdout_by_experiment"
        train_rows = int(len(train_index))
        test_rows = int(len(test_index))
    else:
        minimum_class = int(labels.value_counts().min())
        if minimum_class < 2:
            base_metrics.update(
                {
                    "status": "insufficient_data",
                    "reason": (
                        "Only one experiment is present and at least one class "
                        "has fewer than two trials; cross-validation is not valid."
                    ),
                }
            )
            metrics_path.write_text(
                json.dumps(base_metrics, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return TrainingResult(
                output_directory, "insufficient_data", None, metrics_path, None, None
            )
        folds = min(5, minimum_class)
        splitter = StratifiedKFold(
            n_splits=folds,
            shuffle=True,
            random_state=RANDOM_SEED,
        )
        predictions = cross_val_predict(
            _pipeline(numeric_columns),
            features,
            labels,
            cv=splitter,
            n_jobs=1,
        )
        truth = labels.to_numpy()
        prediction_rows = data[
            ["experiment_id", "experiment_name", "action", "trial_number"]
        ].copy()
        evaluation_method = f"stratified_{folds}_fold_within_single_experiment"

    prediction_rows["predicted_action"] = predictions
    prediction_rows["correct"] = prediction_rows["action"] == predictions
    predictions_path = output_directory / "predictions.csv"
    prediction_rows.to_csv(predictions_path, index=False)

    matrix = confusion_matrix(truth, predictions, labels=class_names)
    matrix_path = output_directory / "confusion_matrix.csv"
    pd.DataFrame(matrix, index=class_names, columns=class_names).to_csv(matrix_path)
    _write_confusion_plot(
        matrix, class_names, output_directory / "confusion_matrix.png"
    )

    final_model = _pipeline(numeric_columns)
    final_model.fit(features, labels)
    model_path = output_directory / "random_forest.joblib"
    joblib.dump(final_model, model_path)

    importances = final_model.named_steps["classifier"].feature_importances_
    importance = pd.DataFrame(
        {"feature": numeric_columns, "importance": importances}
    ).sort_values("importance", ascending=False)
    feature_importance_path = output_directory / "feature_importance.csv"
    importance.to_csv(feature_importance_path, index=False)

    base_metrics.update(
        {
            "status": "complete",
            "evaluation_method": evaluation_method,
            "train_rows": train_rows,
            "test_rows": test_rows,
            "accuracy": float(accuracy_score(truth, predictions)),
            "balanced_accuracy": float(
                balanced_accuracy_score(truth, predictions)
            ),
            "classification_report": classification_report(
                truth,
                predictions,
                labels=class_names,
                output_dict=True,
                zero_division=0,
            ),
            "artifacts": {
                "model": str(model_path),
                "predictions": str(predictions_path),
                "confusion_matrix_csv": str(matrix_path),
                "confusion_matrix_png": str(
                    output_directory / "confusion_matrix.png"
                ),
                "feature_importance": str(feature_importance_path),
            },
            "limitations": [
                "This is a baseline classifier, not a flight-safety model.",
                "Single-session cross-validation can overestimate generalization.",
                "Independent sessions are required for a meaningful session-held-out result.",
                "Host-timestamp and SDR frequency-hopping limitations remain present.",
            ],
        }
    )
    metrics_path.write_text(
        json.dumps(base_metrics, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return TrainingResult(
        output_directory=output_directory,
        status="complete",
        model_path=model_path,
        metrics_path=metrics_path,
        predictions_path=predictions_path,
        feature_importance_path=feature_importance_path,
    )
