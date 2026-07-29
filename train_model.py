"""One-off training script: builds the affordability-risk RandomForest model.

Run manually with `python train_model.py` whenever synthesized_student_loan_data.csv
changes. Not imported by app.py at runtime -- the app just loads the joblib
artifacts this script produces in models/.
"""
import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "synthesized_student_loan_data.csv")
MODELS_DIR = os.path.join(BASE_DIR, "models")


def build_features_and_label(df: pd.DataFrame):
    df = df.rename(columns={
        "Loan_Amount_USD": "loan_amount",
        "Monthly_Income_USD": "monthly_income",
        "Monthly_Expenses_USD": "monthly_expenses",
        "Interest_Rate": "interest_rate",
        "Monthly_Installment_USD": "monthly_payment",
    })

    # No risk label ships with the dataset, so engineer one from the same
    # affordability logic the app itself uses: DTI ratio + total monthly burden.
    dti_ratio = df["monthly_payment"] / df["monthly_income"]
    total_burden = (df["monthly_payment"] + df["monthly_expenses"]) / df["monthly_income"]

    conditions = [
        (dti_ratio < 0.28) & (total_burden < 0.7),
        (dti_ratio < 0.43) & (total_burden < 0.85),
    ]
    choices = ["Low", "Medium"]
    df["risk_level"] = np.select(conditions, choices, default="High") if hasattr(np, "select") else None
    # np.select exists; keep a safe fallback in case of numpy version quirks
    if df["risk_level"].isna().any():
        df["risk_level"] = np.where(
            (dti_ratio < 0.28) & (total_burden < 0.7), "Low",
            np.where((dti_ratio < 0.43) & (total_burden < 0.85), "Medium", "High"),
        )

    feature_cols = ["loan_amount", "interest_rate", "monthly_income", "monthly_expenses", "monthly_payment"]
    return df[feature_cols], df["risk_level"]


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    df = pd.read_csv(DATA_PATH)
    X, y = build_features_and_label(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y)

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(X_train_scaled, y_train)

    preds = model.predict(X_test_scaled)
    accuracy = accuracy_score(y_test, preds)
    print(f"Test-set accuracy: {accuracy * 100:.1f}% on {len(y_test)} held-out rows")
    print("Class distribution:", y.value_counts().to_dict())

    joblib.dump(model, os.path.join(MODELS_DIR, "risk_model.joblib"))
    joblib.dump(scaler, os.path.join(MODELS_DIR, "risk_scaler.joblib"))

    with open(os.path.join(MODELS_DIR, "metrics.json"), "w") as f:
        json.dump({
            "test_accuracy": round(accuracy * 100, 1),
            "n_rows": int(len(df)),
            "n_test": int(len(y_test)),
            "classes": sorted(y.unique().tolist()),
        }, f, indent=2)


if __name__ == "__main__":
    main()
