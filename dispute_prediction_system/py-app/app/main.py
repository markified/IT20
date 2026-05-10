from fastapi import FastAPI, HTTPException

from .model_loader import get_feature_order, predict_from_dict
from .schemas import PredictRequest, PredictResponse

app = FastAPI(title="Invoice Dispute Prediction API", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/features")
def features():
    try:
        return {"feature_order": get_feature_order()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    try:
        label, proba = predict_from_dict(req.features)
        return PredictResponse(prediction=label, probability=proba)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
