"""
Train a Random Forest classifier to predict invoice disputes (Disputed=Yes/No)
from the IT20 Accounts-Receivable dataset.

Outputs:
    ../models/random_forest_dispute_model.pkl
    ../models/feature_info.json
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score, precision_recall_curve
from sklearn.model_selection import train_test_split, GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "WA_Fn-UseC_-Accounts-Receivable.csv"
MODELS_DIR = ROOT / "dispute_prediction_system" / "models"
MODEL_PATH = MODELS_DIR / "random_forest_dispute_model.pkl"
INFO_PATH = MODELS_DIR / "feature_info.json"

CATEGORICAL = ["countryCode", "PaperlessBill"]
NUMERIC = ["InvoiceAmount", "InvoiceMonth", "InvoiceDayOfWeek"]
ALL_FEATURES = CATEGORICAL + NUMERIC


def load_data() -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["InvoiceMonth"] = df["InvoiceDate"].dt.month
    df["InvoiceDayOfWeek"] = df["InvoiceDate"].dt.dayofweek
    df["countryCode"] = df["countryCode"].astype(str)
    df["target"] = (df["Disputed"].str.strip().str.lower() == "yes").astype(int)
    return df


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_data()

    X = df[ALL_FEATURES].copy()
    y = df["target"].values

    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
        ],
        remainder="passthrough",
    )

    pipe = Pipeline(
        steps=[
            ("pre", pre),
            (
                "clf",
                RandomForestClassifier(
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    param_grid = {
        "clf__n_estimators": [100, 200, 300],
        "clf__max_depth": [None, 5, 10],
        "clf__min_samples_split": [2, 5, 10]
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    grid = GridSearchCV(pipe, param_grid=param_grid, cv=cv, scoring="f1", n_jobs=-1)

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    print("Running GridSearchCV to find optimal hyperparameters...")
    grid.fit(X_tr, y_tr)
    best_model = grid.best_estimator_
    print(f"Best parameters found: {grid.best_params_}")

    # Calibrate threshold for at least 0.50 precision on training data
    proba_tr = best_model.predict_proba(X_tr)[:, 1]
    precisions, recalls, thresholds = precision_recall_curve(y_tr, proba_tr)
    target_precision = 0.50
    valid = [(t, p, r) for p, r, t in zip(precisions[:-1], recalls[:-1], thresholds) if p >= target_precision]
    if valid:
        best_t, best_p, best_r = min(valid, key=lambda x: x[0])
        print(f"Calibrated threshold (train): {best_t:.3f} (Precision={best_p:.4f}, Recall={best_r:.4f})")
    else:
        best_t = 0.5
        print("Could not calibrate threshold for target precision. Defaulting to 0.5")

    proba = best_model.predict_proba(X_te)[:, 1]
    pred = (proba >= best_t).astype(int)

    print("\nTest Set Evaluation:")
    print("Accuracy:", accuracy_score(y_te, pred))
    print("ROC AUC :", roc_auc_score(y_te, proba))
    print(classification_report(y_te, pred, target_names=["No", "Yes"]))

    joblib.dump(best_model, MODEL_PATH)

    info = {
        "all_features": ALL_FEATURES,
        "categorical_features": CATEGORICAL,
        "numeric_features": NUMERIC,
        "categorical_values": {
            "countryCode": sorted(df["countryCode"].unique().tolist()),
            "PaperlessBill": sorted(df["PaperlessBill"].unique().tolist()),
        },
        "target": "Disputed",
        "classes": ["No", "Yes"],
        "operating_threshold": float(best_t),
    }
    INFO_PATH.write_text(json.dumps(info, indent=2), encoding="utf-8")

    print(f"\nSaved model to {MODEL_PATH}")
    print(f"Saved feature info to {INFO_PATH}")


if __name__ == "__main__":
    main()
