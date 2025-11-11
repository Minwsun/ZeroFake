#!/usr/bin/env python3
"""
OpenWeather CLI helper for ZeroFake
Usage:
  python scripts/ow_cli.py --city "Hanoi, VN" [--mode present|future|historical] [--relative "sáng ngày mai" | --date YYYY-MM-DD]

This prints a compact JSON payload that mirrors Layer 1 (weather) tool output so you can paste it into Agent 2 for debugging.
"""
import argparse
import json
import sys
from datetime import datetime

# Reuse project weather helpers
from app.weather import (
    resolve_time_parameters,
    get_current_weather,
    get_forecast_for_date,
    get_historical_weather,
)


def run(city: str, mode: str, relative: str | None, date: str | None) -> dict:
    target_date, part_of_day = resolve_time_parameters(relative, date)

    try:
        if mode == "historical":
            if not (date or target_date):
                return {
                    "tool_name": "weather",
                    "status": "historical_date_required",
                    "reason": "Thiếu ngày cụ thể cho dữ liệu lịch sử.",
                }
            data = get_historical_weather(city, target_date or date)
            if data:
                return {
                    "tool_name": "weather",
                    "status": "success",
                    "mode": "historical",
                    "data": {"city": city, **data},
                    "diagnostics": {"weather_api_used": True},
                }
            return {
                "tool_name": "weather",
                "status": "historical_not_available",
                "reason": "Không có dữ liệu lịch sử phù hợp.",
                "diagnostics": {"weather_api_used": True},
            }
        elif mode == "future":
            data = get_forecast_for_date(city, target_date, part_of_day)
            if data:
                return {
                    "tool_name": "weather",
                    "status": "success",
                    "mode": "future",
                    "data": data,
                    "diagnostics": {"weather_api_used": True},
                }
            return {
                "tool_name": "weather",
                "status": "api_error",
                "reason": f"Không gọi được forecast cho {city} ngày {target_date}.",
                "diagnostics": {"weather_api_used": True},
            }
        else:  # present
            data = get_current_weather(city)
            if data:
                return {
                    "tool_name": "weather",
                    "status": "success",
                    "mode": "present",
                    "data": data,
                    "diagnostics": {"weather_api_used": True},
                }
            return {
                "tool_name": "weather",
                "status": "api_error",
                "reason": f"Không gọi được current weather cho {city}.",
                "diagnostics": {"weather_api_used": True},
            }
    except Exception as e:
        return {"tool_name": "weather", "status": "error", "reason": str(e)}


def main():
    parser = argparse.ArgumentParser(description="OpenWeather CLI helper for ZeroFake")
    parser.add_argument("--city", required=True, help="Canonical city, e.g. 'Hanoi, VN' or 'Paris, FR'")
    parser.add_argument("--mode", choices=["present", "future", "historical"], default="present")
    parser.add_argument("--relative", help="Relative time, e.g. 'sáng ngày mai' or 'ngày mai'", default=None)
    parser.add_argument("--date", help="Explicit date YYYY-MM-DD (overrides relative)", default=None)
    args = parser.parse_args()

    result = run(args.city, args.mode, args.relative, args.date)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

