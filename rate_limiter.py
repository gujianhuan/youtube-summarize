import json
import os
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, limit_file="usage_limits.json", max_daily=3):
        self.limit_file = limit_file
        self.max_daily = max_daily
        self.limits = self._load_limits()

    def _load_limits(self):
        if os.path.exists(self.limit_file):
            try:
                with open(self.limit_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading rate limits: {e}")
                return {}
        return {}

    def _save_limits(self):
        try:
            with open(self.limit_file, "w", encoding="utf-8") as f:
                json.dump(self.limits, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving rate limits: {e}")

    def is_owner(self, settings_dict: dict) -> bool:
        """
        判断是否为站长或提供了自定义 API Key 的用户。
        如果用户在设置中填写了 api_key，则视为不受限用户。
        """
        user_key = str(settings_dict.get("api_key") or "").strip()
        return bool(user_key)

    def check_limit(self, identifier: str) -> tuple[bool, str]:
        """
        检查标识符（如 IP）是否在限制范围内。
        返回 (is_allowed, message)
        """
        if not identifier or identifier == "unknown":
            return True, ""

        now = datetime.now()
        if identifier not in self.limits:
            return True, ""

        user_data = self.limits[identifier]
        try:
            reset_at = datetime.fromisoformat(user_data["reset_at"])
        except (ValueError, KeyError):
            # 如果格式错误，重置
            return True, ""

        if now > reset_at:
            # 窗口已过，允许并将在下一次 increment 时重置
            return True, ""

        if user_data.get("count", 0) >= self.max_daily:
            wait_time = reset_at - now
            hours, remainder = divmod(wait_time.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            
            wait_parts = []
            if hours > 0:
                wait_parts.append(f"{int(hours)} 小时")
            if minutes > 0 or not wait_parts:
                wait_parts.append(f"{int(minutes)} 分钟")
            
            wait_str = " ".join(wait_parts)
            return False, f"您今天已达到免费总结上限（每日 {self.max_daily} 个视频）。请在 {wait_str} 后重试，或在设置中配置您自己的 API Key 以解除限制。"

        return True, ""

    def increment(self, identifier: str):
        """
        增加使用计数。
        """
        if not identifier or identifier == "unknown":
            return

        now = datetime.now()
        if identifier not in self.limits:
            self.limits[identifier] = {
                "count": 1,
                "reset_at": (now + timedelta(days=1)).isoformat()
            }
        else:
            user_data = self.limits[identifier]
            try:
                reset_at = datetime.fromisoformat(user_data["reset_at"])
            except (ValueError, KeyError):
                reset_at = now - timedelta(seconds=1)

            if now > reset_at:
                user_data["count"] = 1
                user_data["reset_at"] = (now + timedelta(days=1)).isoformat()
            else:
                user_data["count"] = user_data.get("count", 0) + 1
        
        self._save_limits()
