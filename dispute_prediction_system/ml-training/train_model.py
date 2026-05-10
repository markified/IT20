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
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
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
                    n_estimators=300,
                    max_depth=None,
                    min_samples_split=4,
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )

    pipe.fit(X_tr, y_tr)

    pred = pipe.predict(X_te)
    proba = pipe.predict_proba(X_te)[:, 1]

    print("Accuracy:", accuracy_score(y_te, pred))
    print("ROC AUC :", roc_auc_score(y_te, proba))
    print(classification_report(y_te, pred, target_names=["No", "Yes"]))

    joblib.dump(pipe, MODEL_PATH)

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
    }
    INFO_PATH.write_text(json.dumps(info, indent=2), encoding="utf-8")

    print(f"\nSaved model to {MODEL_PATH}")
    print(f"Saved feature info to {INFO_PATH}")


if __name__ == "__main__":
    main()
