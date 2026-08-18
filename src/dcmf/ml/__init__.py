"""Feature engineering and baseline machine-learning tools."""

from dcmf.ml.features import (
    FeatureDatasetResult,
    extract_trial_features,
    generate_feature_dataset,
)
from dcmf.ml.classifier import TrainingResult, train_random_forest

__all__ = [
    "FeatureDatasetResult",
    "extract_trial_features",
    "generate_feature_dataset",
    "TrainingResult",
    "train_random_forest",
]
