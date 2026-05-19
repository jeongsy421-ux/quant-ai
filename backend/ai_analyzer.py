"""
ai_analyzer.py - AI 분석 모듈
XGBoost + 앙상블 모델을 이용한 주가 방향성 예측
"""
import logging
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import classification_report, accuracy_score
from xgboost import XGBClassifier
from groq import Groq
import os
from config import GROQ_API_KEY

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "MA5", "MA20", "MA60",
    "RSI", "MACD", "MACD_Signal", "MACD_Hist",
    "BB_Width", "Volume_Ratio",
    "Daily_Return", "Volatility_20",
]


class AIAnalyzer:
    """XGBoost 기반 주가 방향성 예측 분석기"""

    def __init__(self):
        self.scaler = StandardScaler()
        self.models = {
            "xgb": XGBClassifier(
                n_estimators=200, max_depth=5, learning_rate=0.05,
                use_label_encoder=False, eval_metric="logloss", random_state=42
            ),
            "rf": RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42),
            "gb":  GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42),
        }
        self.trained = False

    # ── 데이터 준비 ───────────────────────────────────────
    def _prepare(self, df: pd.DataFrame, forward_days: int = 5):
        """피처·레이블 생성. forward_days 후 상승이면 1, 하락이면 0"""
        # 필수 피처 컬럼 존재 확인 및 생성
        for col in FEATURE_COLS:
            if col not in df.columns:
                df[col] = 0.0

        df = df.dropna(subset=FEATURE_COLS)
        close = df["Close"].squeeze()
        df["Target"] = (close.shift(-forward_days) > close).astype(int)
        df = df.dropna(subset=["Target"])

        X = df[FEATURE_COLS].values
        y = df["Target"].values
        return X, y, df.index

    # ── 학습 ──────────────────────────────────────────────
    def train(self, df: pd.DataFrame, forward_days: int = 5) -> dict:
        """모델 학습 및 성능 평가"""
        X, y, _ = self._prepare(df, forward_days)
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, shuffle=False)
        X_tr_s = self.scaler.fit_transform(X_tr)
        X_te_s = self.scaler.transform(X_te)

        results = {}
        for name, model in self.models.items():
            model.fit(X_tr_s, y_tr)
            preds = model.predict(X_te_s)
            acc = accuracy_score(y_te, preds)
            results[name] = {"accuracy": round(acc, 4)}
            logger.info(f"[{name}] 정확도: {acc:.4f}")

        self.trained = True
        return results

    # ── 예측 ──────────────────────────────────────────────
    def predict(self, df: pd.DataFrame) -> dict:
        """최신 데이터로 매수/매도 확률 예측 (앙상블 평균)"""
        if not self.trained:
            logger.warning("[예측] 모델이 아직 학습되지 않았습니다.")
            return {}

        X, _, _ = self._prepare(df)
        X_s = self.scaler.transform(X[-1:])  # 최신 데이터 1행

        probas = []
        for name, model in self.models.items():
            prob = model.predict_proba(X_s)[0][1]  # 상승 확률
            probas.append(prob)
            logger.debug(f"[{name}] 상승 확률: {prob:.4f}")

        ensemble_prob = float(np.mean(probas))
        signal = "BUY" if ensemble_prob > 0.55 else ("SELL" if ensemble_prob < 0.45 else "HOLD")

        return {
            "ensemble_prob": round(ensemble_prob, 4),
            "signal": signal,
            "individual": {n: round(p, 4) for n, p in zip(self.models.keys(), probas)},
        }

    # ── 특성 중요도 ───────────────────────────────────────
    def feature_importance(self) -> pd.DataFrame:
        """XGBoost 특성 중요도 반환"""
        if not self.trained:
            return pd.DataFrame()
        imp = self.models["xgb"].feature_importances_
        return pd.DataFrame({"feature": FEATURE_COLS, "importance": imp}).sort_values(
            "importance", ascending=False
        )

    # ── Groq API 감성 분석 ───────────────────────────────────────
    def analyze_news_sentiment(self, news_text: str) -> dict:
        """Groq API를 사용하여 뉴스 텍스트 감성 분석 (Llama 모델 활용)"""
        if not GROQ_API_KEY:
            logger.error("[Groq] API 키 없음 - 감성 분석 불가")
            return {"sentiment": "중립", "score": 0.0, "reason": "API Key Missing"}

        try:
            client = Groq(api_key=GROQ_API_KEY)
            prompt = (
                f"다음 텍스트의 주식 시장 관점 감성(긍정, 부정, 중립)을 판별하고, 점수(-1.0 ~ 1.0)를 매기며 이유를 설명하세요.\n\n"
                f"텍스트: {news_text}\n\n"
                f"출력 양식(엄격하게 아래 JSON 형태로만 대답하세요):\n"
                f'{{"sentiment": "긍정/부정/중립", "score": 0.5, "reason": "이유 설명"}}'
            )
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                temperature=0.1
            )
            response_text = chat_completion.choices[0].message.content
            import json
            # JSON만 파싱하기 위한 간단한 트릭
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                result = json.loads(response_text[start_idx:end_idx])
                return result
            else:
                return {"sentiment": "중립", "score": 0.0, "reason": "파싱 실패: " + response_text}
        except Exception as e:
            logger.error(f"[Groq 오류]: {e}")
            return {"sentiment": "중립", "score": 0.0, "reason": str(e)}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=== Groq API 모델 뉴스 감성 분석 테스트 시작 ===")
    analyzer = AIAnalyzer()
    sample_news = "미국 연준, 금리 인하 전격 결정... 시장의 기대감 폭발하며 기술주 일제히 급등."
    print(f"테스트 뉴스: {sample_news}")
    res = analyzer.analyze_news_sentiment(sample_news)
    print(f"\n[감성 분석 결과]")
    print(f"감성: {res.get('sentiment')}")
    print(f"점수: {res.get('score')}")
    print(f"이유: {res.get('reason')}")
