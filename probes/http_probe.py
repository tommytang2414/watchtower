"""HTTP/HTTPS endpoint probe."""
import httpx
import json
from typing import Optional


async def run_http_probe(
    target: str,
    timeout_seconds: int = 10,
    content_check: Optional[str] = None,
) -> dict:
    """
    Probe an HTTP endpoint and return a result dict.

    Returns:
        {
            "up": bool,
            "response_time_ms": float,
            "status_code": int,
            "stale": bool | None,
            "rates_count": int | None,
            "content_ok": bool | None,
            "error_message": str | None,
        }
    """
    result = {
        "up": False,
        "response_time_ms": None,
        "status_code": None,
        "stale": None,
        "rates_count": None,
        "content_ok": None,
        "error_message": None,
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(target, timeout=timeout_seconds)
            result["response_time_ms"] = response.elapsed.total_seconds() * 1000
            result["status_code"] = response.status_code

            if response.status_code == 200:
                result["up"] = True

                # Content check
                if content_check:
                    text = response.text
                    result["content_ok"] = content_check in text

                # Special handling for /api/rates
                if "/api/rates" in target:
                    try:
                        data = response.json()
                        rates = data.get("rates", [])
                        result["rates_count"] = len(rates)
                        result["stale"] = bool(data.get("stale", False))
                    except json.JSONDecodeError:
                        result["error_message"] = "Non-JSON response from rates API"
                        result["up"] = False
            else:
                result["error_message"] = f"HTTP {response.status_code}"
                result["up"] = False

    except httpx.TimeoutException:
        result["error_message"] = f"Timeout after {timeout_seconds}s"
        result["up"] = False
    except httpx.RequestError as e:
        result["error_message"] = str(e)
        result["up"] = False

    return result
