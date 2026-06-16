import pytest
from risk_models.ecl_engine import predict_lgd, calculate_ecl
from models.model_loader import load_lgd_model

def test_predict_lgd():
    features = {
        'collateral_ltv': 0.8,
        'collateral_type': 'vehicle',
        'loan_amount': 25000.0
    }
    lgd = predict_lgd(features, 'auto')
    assert lgd is not None
    assert 0.05 <= lgd <= 0.95

def test_calculate_ecl_with_model():
    features = {
        'collateral_ltv': 0.8,
        'collateral_type': 'vehicle',
        'loan_amount': 25000.0
    }
    ecl = calculate_ecl(pd_rate=0.1, ead=25000.0, features=features, product_type='auto', lgd_rate=0.40)
    assert ecl > 0.0
    # Because LGD is predicted between 0.05 and 0.95
    assert 0.1 * 0.05 * 25000 <= ecl <= 0.1 * 0.95 * 25000

def test_calculate_ecl_fallback(monkeypatch):
    features = {
        'collateral_ltv': 0.8,
        'collateral_type': 'vehicle',
        'loan_amount': 25000.0
    }
    # Force exception inside predict_lgd by removing the model file or mocking
    def mock_predict_lgd(*args, **kwargs):
        return None

    monkeypatch.setattr('risk_models.ecl_engine.predict_lgd', mock_predict_lgd)
    ecl = calculate_ecl(pd_rate=0.1, ead=25000.0, features=features, product_type='auto', lgd_rate=0.40)
    assert abs(ecl - (0.1 * 0.40 * 25000.0)) < 1e-5
