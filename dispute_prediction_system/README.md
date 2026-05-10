# Invoice Dispute Prediction System (IT20)

A multi-component system mirroring the structure of `sales_prediction-main`, but
trained on the IT20 **Accounts-Receivable** dataset
(`WA_Fn-UseC_-Accounts-Receivable.csv`) to predict whether an invoice will be
**Disputed** (binary classification).

## Layout

```
dispute_prediction_system/
├── ml-training/        # Training script + requirements
├── models/             # Trained .pkl + feature_info.json
├── py-app/             # FastAPI inference service
├── streamlit-app/      # Streamlit UI (manual / CSV / history) with SQLite
└── web-app/            # ASP.NET Core MVC front-end calling FastAPI
```

## Features used

| Feature            | Type        | Notes                              |
|--------------------|-------------|------------------------------------|
| `countryCode`      | categorical | One of 391, 406, 770, 818, 897     |
| `PaperlessBill`    | categorical | `Paper` or `Electronic`            |
| `InvoiceAmount`    | numeric     | Invoice total                      |
| `InvoiceMonth`     | numeric     | 1–12 (from `InvoiceDate`)          |
| `InvoiceDayOfWeek` | numeric     | 0=Mon … 6=Sun (from `InvoiceDate`) |

Settlement-time fields (`DaysToSettle`, `DaysLate`, `SettledDate`) are
**intentionally excluded** to avoid target leakage for an early-prediction use
case.

## 1. Train the model

```powershell
cd dispute_prediction_system\ml-training
pip install -r requirements.txt
python train_model.py
```

Outputs:

- `..\models\random_forest_dispute_model.pkl`
- `..\models\feature_info.json`

## 2. Run the FastAPI service

```powershell
cd dispute_prediction_system\py-app
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Endpoints:

- `GET  /health`
- `GET  /features`
- `POST /predict`  → `{ "prediction": "Yes"|"No", "probability": 0.0-1.0 }`

Example body:

```json
{
  "features": {
    "countryCode": "391",
    "PaperlessBill": "Electronic",
    "InvoiceAmount": 65.88,
    "InvoiceMonth": 7,
    "InvoiceDayOfWeek": 2
  }
}
```

## 3. Run the Streamlit app

```powershell
cd dispute_prediction_system\streamlit-app
pip install -r requirements.txt
streamlit run app.py
```

Modes: **Manual Input**, **CSV Upload** (batch), **History** (SQLite log).

## 4. Run the ASP.NET Core web-app

The MVC site posts the form to its own controller, which calls the FastAPI
`/predict` endpoint and stores the result in a local SQLite database.

```powershell
cd dispute_prediction_system\web-app
dotnet run
```

Make sure the FastAPI service (step 2) is running at the URL configured in
`appsettings.Development.json` (`FastApi:BaseUrl`, default `http://127.0.0.1:8001`).
