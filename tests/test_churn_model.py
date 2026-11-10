"""Fitted churn model: model file, features, prediction and the numpy fitter."""

import numpy as np
import pandas as pd
import pytest

from signals import churn_model


def test_model_file_matches_feature_spec():
    model = churn_model.load()
    assert model["features"] == churn_model.FEATURES
    assert set(model["coefficients"]) == set(churn_model.FEATURES)
    v = model["training"]["validation"]
    # The shipped model must beat the prior-plans-only baseline on held-out terms.
    assert v["test_auc"] > v["prior_only_auc"]
    assert abs(v["test_mean_predicted"] - v["test_actual_rate"]) < 0.03


def test_features_handle_missing_values():
    raw = pd.DataFrame({
        "prior_paid_plans": [None, 0, 3],
        "profile_views_60d": [None, 0, 90],
        "site_views_60d": [180_000, None, 180_000],
        "days_since_last_lead": [None, 4, pd.NA],
    })
    x = churn_model.features(raw)
    assert list(x.columns) == churn_model.FEATURES
    assert not x.isna().any().any()
    assert list(x["first_term"]) == [1.0, 1.0, 0.0]
    assert list(x["no_leads_90d"]) == [1.0, 0.0, 1.0]
    assert x.loc[2, "log_view_share"] == pytest.approx(np.log1p(50.0))


def test_fit_recovers_known_coefficients():
    rng = np.random.default_rng(7)
    n = 40_000
    x = pd.DataFrame(rng.normal(size=(n, len(churn_model.FEATURES))), columns=churn_model.FEATURES)
    true_b0, true_w = -1.0, np.array([-0.8, 0.4, -0.5, 0.3])
    p = 1 / (1 + np.exp(-(true_b0 + x.to_numpy() @ true_w)))
    y = pd.Series((rng.random(n) < p).astype(int))
    b0, coef = churn_model.fit(x, y, l2=1.0)
    assert b0 == pytest.approx(true_b0, abs=0.05)
    assert [coef[f] for f in churn_model.FEATURES] == pytest.approx(list(true_w), abs=0.05)


def test_predict_uses_supplied_model():
    model = {"intercept": 0.0, "coefficients": dict.fromkeys(churn_model.FEATURES, 0.0)}
    raw = pd.DataFrame({"prior_paid_plans": [1], "profile_views_60d": [10],
                        "site_views_60d": [1000], "days_since_last_lead": [3]})
    assert churn_model.predict(raw, model).iloc[0] == pytest.approx(0.5)
