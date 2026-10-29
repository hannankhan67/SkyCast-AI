"""SkyCast AI - Lightweight precipitation ML model.

Uses scikit-learn when available. Falls back to a deterministic rule-based
predictor so the assistant never breaks in offline/demo mode.
"""
import math
import os
import random

import database

try:
    from sklearn.ensemble import RandomForestClassifier
    _SKLEARN = True
except Exception:
    _SKLEARN = False


def _feature_vector(temp, humidity, wind, pressure, month, hour):
    return [
        float(temp or 0),
        float(humidity or 0),
        float(wind or 0),
        float(pressure or 1000),
        float(month or 1),
        float(hour or 12),
    ]


class PrecipitationModel:
    def __init__(self):
        self._model = None
        if _SKLEARN:
            try:
                self._model = self._train()
            except Exception:
                self._model = None

    def _synthetic_training_data(self):
        random.seed(42)
        X, y = [], []
        for _ in range(2000):
            temp = random.uniform(-5, 45)
            humidity = random.uniform(20, 100)
            wind = random.uniform(0, 60)
            pressure = random.uniform(980, 1040)
            month = random.randint(1, 12)
            hour = random.randint(0, 23)
            rain = 1 if (humidity > 75 and pressure < 1005 and temp < 35) else 0
            if month in (7, 8) and random.random() > 0.4:
                rain = 1
            X.append([temp, humidity, wind, pressure, month, hour])
            y.append(rain)
        return X, y

    def _train(self):
        X, y = self._synthetic_training_data()
        clf = RandomForestClassifier(n_estimators=120, random_state=42)
        clf.fit(X, y)
        return clf

    def predict(self, temp, humidity, wind, pressure, month=None, hour=None):
        now = __import__("datetime").datetime.now()
        month = month or now.month
        hour = hour or now.hour
        x = [_feature_vector(temp, humidity, wind, pressure, month, hour)]
        if self._model is not None:
            try:
                return int(self._model.predict(x)[0])
            except Exception:
                pass
        return 1 if (humidity > 75 and pressure < 1005) else 0

    def probability(self, temp, humidity, wind, pressure, month=None, hour=None):
        pred = self.predict(temp, humidity, wind, pressure, month, hour)
        return 0.85 if pred == 1 else 0.15


_model = PrecipitationModel()


def rain_probability(temp, humidity, wind, pressure, month=None, hour=None):
    return _model.probability(temp, humidity, wind, pressure, month, hour)


def will_rain(temp, humidity, wind, pressure, month=None, hour=None):
    return _model.predict(temp, humidity, wind, pressure, month, hour) == 1
