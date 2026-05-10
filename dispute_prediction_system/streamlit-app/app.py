import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st

from db import fetch_latest, init_db, insert_prediction

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "random_forest_dispute_model.pkl"
INFO_PATH = ROOT / "models" / "feature_info.json"


@st.cache_resource
def load_artifacts():
    model = joblib.load(MODEL_PATH)
    info = json.loads(INFO_PATH.read_text(encoding="utf-8"))

    features = info.get("all_features")
    cat_cols = info.get("categorical_features", [])
    num_cols = info.get("numeric_features", [])
    cat_vals = info.get("categorical_values", {})
    classes = info.get("classes", ["No", "Yes"])

    return model, features, cat_cols, num_cols, cat_vals, classes


def main():
    st.set_page_config(page_title="Invoice Dispute Predictor", page_icon=":memo:")
    st.title("Invoice Dispute Predictor")
    init_db()

    model, features, cat_cols, num_cols, cat_vals, classes = load_artifacts()

    THRESHOLD = 0.35  # flag as dispute if probability >= this value

    mode = st.radio("Mode", ["Manual Input", "CSV Upload", "History"], horizontal=True)

    # ------------------ MANUAL INPUT ------------------
    if mode == "Manual Input":
        st.subheader("Input Features")

        inputs = {}
        for col in features:
            if col in cat_cols:
                inputs[col] = st.selectbox(col, cat_vals.get(col, []))
            elif col == "InvoiceMonth":
                inputs[col] = st.number_input(col, min_value=1, max_value=12, value=1, step=1)
            elif col == "InvoiceDayOfWeek":
                inputs[col] = st.number_input(col + " (0=Mon … 6=Sun)", min_value=0, max_value=6, value=0, step=1)
            else:
                inputs[col] = st.number_input(col, value=0.0)

        if st.button("Predict"):
            X = pd.DataFrame([inputs], columns=features)
            proba = float(model.predict_proba(X)[0, 1])
            label = classes[1] if proba >= THRESHOLD else classes[0]

            insert_prediction(
                datetime.now().isoformat(timespec="seconds"),
                json.dumps(inputs),
                label,
                proba,
            )

            if label == "Yes":
                st.error(f"Predicted: DISPUTE (probability {proba:.2%})")
            else:
                st.success(f"Predicted: NO DISPUTE (dispute probability {proba:.2%})")

    # ------------------ CSV UPLOAD ------------------
    elif mode == "CSV Upload":
        st.subheader("Upload CSV for Batch Prediction")
        st.caption("Upload the raw dataset or a CSV with these columns (InvoiceMonth & InvoiceDayOfWeek are auto-derived from InvoiceDate if present):")
        st.code(", ".join(features))

        file = st.file_uploader("Upload CSV", type=["csv"])
        if file:
            df = pd.read_csv(file)

            # Auto-engineer features from InvoiceDate if present
            if "InvoiceDate" in df.columns:
                df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")
                if "InvoiceMonth" not in df.columns:
                    df["InvoiceMonth"] = df["InvoiceDate"].dt.month
                if "InvoiceDayOfWeek" not in df.columns:
                    df["InvoiceDayOfWeek"] = df["InvoiceDate"].dt.dayofweek

            # countryCode must be string to match training
            if "countryCode" in df.columns:
                df["countryCode"] = df["countryCode"].astype(str)

            st.dataframe(df.head(20), use_container_width=True)

            if st.button("Predict CSV"):
                missing = [c for c in features if c not in df.columns]
                if missing:
                    st.error(f"Missing columns: {missing}")
                    return

                X = df[features].copy()
                proba = model.predict_proba(X)[:, 1]
                labels = np.where(proba >= THRESHOLD, classes[1], classes[0])

                out = df.copy()
                out["dispute_probability"] = proba
                out["prediction"] = labels

                disputed_only = st.checkbox("Show disputed invoices only", value=False)
                display = out[out["prediction"] == "Yes"] if disputed_only else out

                st.success(
                    f"Predicted {len(out)} rows — "
                    f"{(labels == 'Yes').sum()} flagged as disputed."
                )
                st.dataframe(display.head(50), use_container_width=True)

                st.download_button(
                    "Download disputed.csv" if disputed_only else "Download predictions.csv",
                    display.to_csv(index=False).encode("utf-8"),
                    "disputed.csv" if disputed_only else "predictions.csv",
                    "text/csv",
                )

    # ------------------ HISTORY ------------------
    else:
        st.subheader("Recent Predictions (DB)")
        disputed_only = st.checkbox("Show disputed invoices only", value=False)
        rows = fetch_latest(100)
        if rows:
            df_hist = pd.DataFrame(
                rows,
                columns=["id", "created_at", "features_json", "prediction", "probability"],
            )
            if disputed_only:
                df_hist = df_hist[df_hist["prediction"] == "Yes"]
            df_hist["probability"] = df_hist["probability"].map(lambda x: f"{x:.2%}")
            if df_hist.empty:
                st.info("No disputed predictions found.")
            else:
                st.dataframe(df_hist, use_container_width=True)
        else:
            st.info("No predictions yet.")


if __name__ == "__main__":
    main()
