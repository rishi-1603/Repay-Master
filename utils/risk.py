"""RandomForest affordability-risk model: load, predict, and explain."""
import os
import json
import joblib
import numpy as np
import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "risk_model.joblib")
SCALER_PATH = os.path.join(BASE_DIR, "models", "risk_scaler.joblib")
METRICS_PATH = os.path.join(BASE_DIR, "models", "metrics.json")

FEATURE_NAMES = ["loan_amount", "interest_rate", "monthly_income", "monthly_expenses", "monthly_payment"]


@st.cache_resource(show_spinner=False)
def load_risk_model():
    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    return model, scaler


def load_model_metrics():
    try:
        with open(METRICS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"test_accuracy": None, "n_rows": None}


def _feature_vector(features: dict):
    return pd.DataFrame([[features[name] for name in FEATURE_NAMES]], columns=FEATURE_NAMES)


def predict_risk(model, scaler, features: dict):
    x = _feature_vector(features)
    x_scaled = scaler.transform(x)
    label = model.predict(x_scaled)[0]
    proba = model.predict_proba(x_scaled)[0]
    proba_dict = dict(zip(model.classes_, proba))
    return label, proba_dict


def explain_prediction(model, scaler, features: dict):
    """Return a DataFrame(feature, contribution) explaining this specific prediction.

    Tries SHAP TreeExplainer first; falls back to global feature_importances_
    (scaled by how far this input deviates from the training mean) if SHAP
    isn't available or errors out, so the UI never breaks because of it.
    """
    x = _feature_vector(features)
    x_scaled = scaler.transform(x)

    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(x_scaled)
        label = model.predict(x_scaled)[0]
        class_idx = list(model.classes_).index(label)
        if isinstance(shap_values, list):
            values = shap_values[class_idx][0]
        else:
            values = shap_values[0, :, class_idx]
        df = pd.DataFrame({"feature": FEATURE_NAMES, "contribution": values})
        df["approximate"] = False
        return df.sort_values("contribution", key=abs, ascending=False)
    except Exception:
        importances = model.feature_importances_
        deviation = x_scaled[0]
        contribution = importances * deviation
        df = pd.DataFrame({"feature": FEATURE_NAMES, "contribution": contribution})
        df["approximate"] = True
        return df.sort_values("contribution", key=abs, ascending=False)
