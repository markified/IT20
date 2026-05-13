import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st
import shap
import matplotlib.pyplot as plt

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

    mode = st.radio("Mode", ["Manual Input", "CSV Upload", "Analytics Dashboard", "History"], horizontal=True)

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

            # Justification using SHAP inside an expander (to avoid nested button reload issues)
            with st.expander("Show Prediction Justification (How it works)", expanded=False):
                st.write("This chart shows how much each feature contributed to the final dispute probability, starting from the base average probability.")
                
                # Transform inputs and prepare feature names
                X_transformed = model.named_steps["pre"].transform(X)
                cat_features_out = model.named_steps["pre"].named_transformers_["cat"].get_feature_names_out(cat_cols).tolist()
                all_feature_names = cat_features_out + num_cols
                
                # Make feature names easier to read (e.g. "countryCode_391" -> "countryCode: 391")
                clean_feature_names = [f.replace("_", ": ") if f in cat_features_out else f for f in all_feature_names]
                
                # Initialize SHAP explainer
                clf = model.named_steps["clf"]
                explainer = shap.TreeExplainer(clf)
                shap_values = explainer.shap_values(X_transformed)
                
                # Create Explanation object for the positive class (Dispute = Yes)
                exp = shap.Explanation(
                    values=shap_values[0, :, 1] if len(shap_values.shape) == 3 else shap_values[1][0], 
                    base_values=explainer.expected_value[1] if isinstance(explainer.expected_value, (list, np.ndarray)) else explainer.expected_value, 
                    data=X_transformed[0], 
                    feature_names=clean_feature_names
                )
                
                # Plot
                fig, ax = plt.subplots(figsize=(8, 4))
                shap.plots.waterfall(exp, show=False)
                st.pyplot(fig)
                plt.close(fig)

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

    # ------------------ ANALYTICS DASHBOARD ------------------
    elif mode == "Analytics Dashboard":
        st.subheader("High-Level Analytics & KPIs")
        rows = fetch_latest(2000)  # pull decent amount of history
        
        if not rows:
            st.info("Not enough data for analytics. Process some invoices first.")
        else:
            # Parse DB rows into a combined pandas DataFrame
            df_hist = pd.DataFrame(rows, columns=["id", "created_at", "features_json", "prediction", "probability"])
            features_df = df_hist["features_json"].apply(json.loads).apply(pd.Series)
            df_analytics = pd.concat([df_hist.drop(columns=["features_json"]), features_df], axis=1)
            
            # Clean up numeric types
            if "InvoiceAmount" in df_analytics.columns:
                df_analytics["InvoiceAmount"] = pd.to_numeric(df_analytics["InvoiceAmount"], errors="coerce").fillna(0)
                
            # Calculate KPIs
            total_predictions = len(df_analytics)
            df_disputed = df_analytics[df_analytics["prediction"] == "Yes"]
            disputed_count = len(df_disputed)
            dispute_rate = disputed_count / total_predictions if total_predictions > 0 else 0
            
            amount_at_risk = df_disputed["InvoiceAmount"].sum() if "InvoiceAmount" in df_analytics.columns else 0
            
            # Display KPIs
            st.markdown("### 📊 1. Business Impact Summary")
            st.info("Provides a bird's-eye view of your processed invoices and the monetary value currently at risk due to predicted disputes.", icon="💡")
            
            c1, c2, c3 = st.columns(3)
            c1.metric(label="🧾 Total Invoices Scored", value=f"{total_predictions:,}", help="The total count of invoices the system has analyzed.")
            c2.metric(label="⚠️ Predicted Disputes", value=f"{disputed_count:,}", delta=f"{dispute_rate:.1%} of total", delta_color="inverse", help="How many invoices are flagged as likely to be disputed.")
            c3.metric(label="💰 Revenue at Risk", value=f"${amount_at_risk:,.2f}", help="Total dollar amount of invoices marked as expected disputes.")
            
            st.divider()
            
            st.markdown("### 🔍 2. Where are disputes happening?")
            st.caption("These charts help you identify operational patterns—like whether a specific region or billing method is causing more friction with customers.")
            
            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                # Chart 1: Disputes Volume by Country 
                if "countryCode" in df_analytics.columns:
                    st.markdown("**Total Disputes by Region (Country Code)**")
                    st.write("Which countries generate the highest volume of disputes?")
                    if not df_disputed.empty:
                        st.bar_chart(df_disputed.groupby("countryCode").size(), color="#ff4b4b")
                    else:
                        st.info("No disputes to chart yet.")
                        
            with c_chart2:
                # Chart 2: Dispute Risk Rate by Paperless vs Paper
                if "PaperlessBill" in df_analytics.columns:
                    st.markdown("**Dispute Risk % by Billing Type**")
                    st.write("Does paper vs. electronic billing affect dispute chances?")
                    billing_rates = df_analytics.groupby("PaperlessBill").apply(
                        lambda x: (x["prediction"] == "Yes").mean() * 100
                    )
                    st.bar_chart(billing_rates, color="#5787ef")

            st.divider()

            # Global Justification (SHAP Summary Plot)
            st.markdown("### 🧠 3. How the AI makes its decisions")
            with st.expander("View Global AI Logic (Feature Importance)", expanded=False):
                st.write("This chart shows the **Average Impact** of each feature on predicting a dispute across recent history.")
                st.caption("Longer bars mean the feature is generally more important to the model. The value represents the average percentage change in dispute probability caused by this feature.")
                
                # Use recent data (up to 500 to keep it snappy)
                X_history = df_analytics[[f for f in features if f in df_analytics.columns]].head(500).copy()
                
                # Ensure all features exist and are correctly ordered and formatted
                missing_cols = [c for c in features if c not in X_history.columns]
                if not missing_cols and not X_history.empty:
                    # Fix types to match training schema
                    for col in cat_cols:
                        X_history[col] = X_history[col].astype(str)
                    for col in num_cols:
                        X_history[col] = pd.to_numeric(X_history[col], errors="coerce").fillna(0)

                    # Transform features
                    X_transformed = model.named_steps["pre"].transform(X_history)
                    cat_features_out = model.named_steps["pre"].named_transformers_["cat"].get_feature_names_out(cat_cols).tolist()
                    all_feature_names = cat_features_out + num_cols
                    
                    # Make feature names easier to read
                    clean_feature_names = [f.replace("_", ": ") if f in cat_features_out else f for f in all_feature_names]
                    
                    # Compute SHAP
                    clf = model.named_steps["clf"]
                    explainer = shap.TreeExplainer(clf)
                    shap_values = explainer.shap_values(X_transformed)
                    sv_positive = shap_values[1] if isinstance(shap_values, list) else shap_values[:, :, 1] if len(shap_values.shape) == 3 else shap_values

                    # Plot
                    fig, ax = plt.subplots(figsize=(8, 5))
                    # Use a clear Bar Chart instead of a complex Beeswarm plot
                    shap.summary_plot(sv_positive, X_transformed, feature_names=clean_feature_names, plot_type="bar", show=False)
                    st.pyplot(fig)
                    plt.close(fig)
                else:
                    st.warning("Ensure all required features are present to generate overall justification.")

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
