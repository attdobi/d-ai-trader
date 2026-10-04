import os

def get_trading_mode() -> str:
    raw = (os.getenv("TRADING_MODE") or "simulation").strip().lower()
    aliases = {"real_world": "live", "realworld": "live", "real": "live"}
    canonical = aliases.get(raw, raw)
    if canonical not in {"simulation", "live"}:
        canonical = "simulation"
    return canonical
