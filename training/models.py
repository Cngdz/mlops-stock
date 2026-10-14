"""Model builders. Each returns ONE fitted sklearn Pipeline (preprocessing + model), so the
artifact takes the raw feature vector: Day 7 logs it with mlflow.sklearn, Day 8 serves it as is."""
from __future__ import annotations

import pandas as pd
from lightgbm import LGBMClassifier, early_stopping
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from training.config import UseCase


def preprocessor(uc: UseCase, scale: bool) -> ColumnTransformer:
    transformers = [("num", StandardScaler() if scale else "passthrough", uc.numeric_features)]
    if uc.categorical_features:
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                             uc.categorical_features))
    return ColumnTransformer(transformers, verbose_feature_names_out=False).set_output(transform="pandas")


def fit_lr(uc: UseCase, X: pd.DataFrame, y, sample_weight) -> Pipeline:
    model = LogisticRegression(C=uc.lr["C"], max_iter=uc.lr["max_iter"], random_state=uc.seed)
    pipe = Pipeline([("pre", preprocessor(uc, scale=True)), ("model", model)])
    return pipe.fit(X, y, model__sample_weight=sample_weight)


def fit_lgbm(uc: UseCase, X: pd.DataFrame, y, sample_weight, X_val: pd.DataFrame, y_val) -> Pipeline:
    """Early stopping needs the validation set transformed by the train-fitted preprocessor,
    so fit the two steps separately and assemble the Pipeline afterwards."""
    params = dict(uc.lgbm)
    rounds = params.pop("early_stopping_rounds")
    pre = preprocessor(uc, scale=False).fit(X)
    model = LGBMClassifier(**params, random_state=uc.seed, n_jobs=uc.n_jobs,
                           deterministic=True, force_row_wise=True, verbose=-1)
    model.fit(pre.transform(X), y, sample_weight=sample_weight,
              eval_X=pre.transform(X_val), eval_y=y_val, eval_metric="auc",
              callbacks=[early_stopping(rounds, first_metric_only=True, verbose=False)])
    return Pipeline([("pre", pre), ("model", model)])
