"""
kakao_alert.py - 카카오톡 알림 발송 모듈
카카오 메시지 API를 통한 매매 시그널 알림
"""
import logging
import requests
import os
from datetime import datetime
from config import KAKAO_REST_API_KEY

logger = logging.getLogger(__name__)

KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoAlert:
    """카카오톡 자기 자신에게 알림 발송 (나에게 보내기)"""

    def __init__(self, access_token: str = ""):
        # access_token: OAuth 인증 후 발급받은 사용자 토큰
        self.access_token = access_token or KAKAO_REST_API_KEY
        self.history = []

    def get_history(self, limit: int = 10):
        """최근 발송 이력 반환"""
        return self.history[-limit:]

    def _send(self, text: str) -> bool:
        """카카오 API로 텍스트 메시지 발송"""
        # 이력에 기록 (발송 성공 여부와 관계없이 기록)
        self.history.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": text
        })
        
        if not self.access_token:
            logger.error("[카카오] access_token이 설정되지 않았습니다.")
            return False
        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            template = {
                "object_type": "text",
                "text": text,
                "link": {"web_url": "", "mobile_web_url": ""},
            }
            import json
            resp = requests.post(
                KAKAO_SEND_URL,
                headers=headers,
                data={"template_object": json.dumps(template)},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f"[카카오] 알림 발송 성공")
                return True
            else:
                logger.error(f"[카카오] 발송 실패: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"[카카오] 발송 예외: {e}")
            return False

    # ── 시그널 알림 ───────────────────────────────────────
    def send_signal_alert(self, ticker: str, signal_data: dict) -> bool:
        """매매 시그널 알림 발송"""
        token = os.getenv("KAKAO_ACCESS_TOKEN", "")
        if not token or token in ("나중에입력", "", "your_kakao_token"):
            return False
        signal = signal_data.get("signal", "HOLD")
        score = signal_data.get("combined_score", 0)
        ai_prob = signal_data.get("ai", {}).get("ensemble_prob", 0.5)
        reasons = signal_data.get("technical", {}).get("reasons", [])
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        emoji = {"BUY": "", "SELL": "", "HOLD": "➖"}.get(signal, "➖")
        text = (
            f"[Quant AI 시그널] {now}\n"
            f"종목: {ticker}\n"
            f"시그널: {emoji} {signal}\n"
            f"AI 상승확률: {ai_prob*100:.1f}%\n"
            f"복합점수: {score:.4f}\n"
            f"근거: {', '.join(reasons)}"
        )
        return self._send(text)

    # ── 리스크 경고 알림 ──────────────────────────────────
    def send_risk_alert(self, ticker: str, risk_data: dict) -> bool:
        """리스크 지표 경고 알림 발송"""
        mdd = risk_data.get("mdd", 0) * 100
        var = risk_data.get("var_95_1d", 0) * 100
        sharpe = risk_data.get("sharpe", 0)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        text = (
            f"[Quant AI 리스크] {now}\n"
            f"종목: {ticker}\n"
            f"⚠️ MDD: {mdd:.2f}%\n"
            f"⚠️ 1일 VaR(95%): {var:.2f}%\n"
            f" 샤프비율: {sharpe:.4f}"
        )
        return self._send(text)

    # ── 일일 요약 알림 ────────────────────────────────────
    def send_daily_summary(self, summary: dict) -> bool:
        """일일 포트폴리오 요약 알림 발송"""
        now = datetime.now().strftime("%Y-%m-%d")
        lines = [f"[Quant AI 일일 요약] {now}"]
        for ticker, info in summary.items():
            sig = info.get("signal", "HOLD")
            emoji = {"BUY": "", "SELL": "", "HOLD": "➖"}.get(sig, "➖")
        return self._send("\n".join(lines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("=== 카카오 알림 테스트 시작 ===")
    import config
    # API 키 대신 빈값이나 환경변수에 있는 값으로 테스트 
    alert = KakaoAlert(config.KAKAO_REST_API_KEY)
    
    test_signal = {
        "signal": "BUY",
        "combined_score": 0.85,
        "ai": {"ensemble_prob": 0.8},
        "technical": {"reasons": ["테스트 알림 발송"]}
    }
    
    # 실제 토큰 없으면 401 오류가 날 수 있지만, 호출되는 자체를 확인
    alert.send_signal_alert("TEST.KS", test_signal)
