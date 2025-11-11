# app/tool_executor.py
import asyncio
import json
import os
import sys
import subprocess
from urllib.parse import urlparse
from datetime import datetime

# Import các tool thực thi
from app.retriever import gemini_web_search
from app.search import call_google_search  # CSE fallback
from app.weather import (
	get_current_weather,
	get_forecast_for_date,
	get_historical_weather,
	resolve_time_parameters,
	extract_weather_info,
	geocode_city,
)
from app.ranker import get_rank_from_url, _extract_date


# --- SEARCH TOOL (Gemini Web Search với fallback CSE) ---

async def _execute_search_tool(parameters: dict, site_query_string: str) -> dict:
	"""
	Thực thi mô-đun "search" bằng Gemini Flash web browsing; nếu rỗng → fallback Google CSE.
	Phân loại kết quả vào các Lớp 2, 3, 4 theo ranker.
	"""
	queries = parameters.get("queries", [])
	if not queries:
		return {"tool_name": "search", "status": "no_queries", "layer_2": [], "layer_3": [], "layer_4": []}

	all_items = []
	seen_urls = set()

	# Pass 1: Gemini web search
	try:
		results = await asyncio.to_thread(gemini_web_search, queries)
		for r in results:
			url = r.get("url")
			if url and url not in seen_urls:
				item = {
					"link": url,
					"snippet": (r.get("snippet") or "").replace("\n", " "),
					"pagemap": {"metatags": [{"article:published_time": r.get("date")}]}
				}
				all_items.append(item)
				seen_urls.add(url)
	except Exception as e:
		print(f"Lỗi Gemini web search: {e}")

	# Pass 2: Fallback CSE nếu không có kết quả
	if not all_items:
		for query in queries:
			try:
				search_items = await asyncio.to_thread(call_google_search, query, site_query_string)
				for item in search_items or []:
					link = item.get('link')
					if link and link not in seen_urls:
						all_items.append(item)
						seen_urls.add(link)
			except Exception as e:
				print(f"Lỗi khi thực thi CSE query '{query}': {e}")

	# Phân loại kết quả vào các Lớp
	layer_2 = []
	layer_3 = []
	layer_4 = []

	for item in all_items:
		link = item.get('link', '')
		rank_score = get_rank_from_url(link)
		evidence_item = {
			"source": urlparse(link).netloc.replace('www.', ''),
			"url": link,
			"snippet": (item.get('snippet', '') or ''),
			"rank_score": rank_score,
			"date": _extract_date(item)
		}
		if rank_score > 0.9:
			layer_2.append(evidence_item)
		elif rank_score > 0.5:
			layer_3.append(evidence_item)
		else:
			layer_4.append(evidence_item)

	layer_2.sort(key=lambda x: x.get('date') or '1970-01-01', reverse=True)
	layer_3.sort(key=lambda x: x.get('date') or '1970-01-01', reverse=True)

	return {
		"tool_name": "search", "status": "success",
		"layer_2_high_trust": layer_2,
		"layer_3_general": layer_3,
		"layer_4_social_low": layer_4
	}


# --- WEATHER TOOL (Refactored: OpenWeather API with CLI fallback) ---

def _run_ow_cli(city: str, mode: str, relative_time: str | None, explicit_date: str | None) -> dict | None:
	"""Chạy script scripts/ow_cli.py để lấy JSON thời tiết khi API nội bộ thất bại."""
	try:
		script_path = os.path.join(os.getcwd(), 'scripts', 'ow_cli.py')
		if not os.path.exists(script_path):
			return None
		cmd = [sys.executable, script_path, '--city', city, '--mode', mode]
		if relative_time:
			cmd += ['--relative', relative_time]
		if explicit_date:
			cmd += ['--date', explicit_date]
		out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=20)
		return json.loads(out)
	except subprocess.TimeoutExpired:
		print("OW CLI fallback timeout after 20s")
		return {"tool_name": "weather", "status": "error", "reason": "CLI fallback timeout"}
	except Exception as e:
		print(f"OW CLI fallback error: {e}")
		return None


def _canonicalize(city_like: str | None) -> str | None:
	if not city_like:
		return None
	geo = geocode_city(city_like)
	if geo and geo.get("name"):
		cc = geo.get("country")
		return f"{geo.get('name')}, {cc}" if cc else geo.get('name')
	return None


def _pick_city(parameters: dict) -> str | None:
	"""Cố gắng suy ra city theo thứ tự: location -> fallback_locations -> extract từ original_text; canonicalize bằng geocoding."""
	# 1) location trực tiếp
	city = (parameters.get("location") or "").strip()
	if city:
		canon = _canonicalize(city)
		return canon or city
	# 2) fallback_locations
	for cand in (parameters.get("fallback_locations") or []):
		if cand and isinstance(cand, str) and cand.strip():
			canon = _canonicalize(cand.strip())
			return canon or cand.strip()
	# 3) extract từ original_text
	try:
		info = extract_weather_info(parameters.get("original_text") or "")
		if info and info.get("city"):
			city_like = f"{info.get('city')}, {info.get('country')}" if info.get('country') else info.get('city')
			canon = _canonicalize(city_like)
			return canon or city_like
	except Exception:
		pass
	return None


async def _execute_weather_tool(parameters: dict, site_query_string: str = "") -> dict:
	"""
	Thực thi mô-đun "weather" chỉ với OpenWeather API; nếu thất bại, fallback sang scripts/ow_cli.py.
	Loại bỏ đường CSE cho thời tiết để giải quyết triệt để vấn đề thiếu dữ liệu tool weather.
	"""
	tool_name = "weather"
	try:
		city = _pick_city(parameters)
		time_scope = parameters.get("time_scope", "present")
		relative_time = parameters.get("relative_time")
		explicit_date = parameters.get("explicit_date")
		if not city:
			return {"tool_name": tool_name, "status": "error", "reason": "Không thể xác định địa danh (hãy ghi rõ như 'Hanoi, VN' hoặc tên thành phố khác).", "diagnostics": {"weather_api_used": False, "fallback_cli": False}}

		# Giải quyết tham số thời gian
		target_date, part_of_day = resolve_time_parameters(relative_time, explicit_date)

		# API nội bộ
		data = None
		mode = "present"
		if time_scope == 'historical':
			mode = 'historical'
			if not (explicit_date or target_date):
				return {"tool_name": tool_name, "status": "historical_date_required", "reason": "Thiếu ngày cụ thể cho dữ liệu lịch sử.", "diagnostics": {"weather_api_used": False, "fallback_cli": False}}
			data = await asyncio.to_thread(get_historical_weather, city, (explicit_date or target_date))
		elif time_scope == 'future':
			mode = 'future'
			data = await asyncio.to_thread(get_forecast_for_date, city, target_date, part_of_day)
		else:
			mode = 'present'
			data = await asyncio.to_thread(get_current_weather, city)

		if data:
			return {"tool_name": tool_name, "status": "success", "mode": mode, "data": data, "diagnostics": {"weather_api_used": True, "fallback_cli": False}}

		# Fallback: CLI script
		cli_res = _run_ow_cli(city, mode, relative_time, explicit_date or target_date)
		if isinstance(cli_res, dict) and cli_res.get('status') == 'success':
			return {"tool_name": tool_name, "status": "success", "mode": cli_res.get('mode', mode), "data": cli_res.get('data'), "diagnostics": {"weather_api_used": True, "fallback_cli": True}}
		elif isinstance(cli_res, dict):
			return {"tool_name": tool_name, "status": cli_res.get('status', 'api_error'), "reason": cli_res.get('reason', 'CLI fallback failed'), "diagnostics": {"weather_api_used": True, "fallback_cli": True}}

		return {"tool_name": tool_name, "status": "api_error", "reason": f"OpenWeather và CLI fallback đều thất bại cho {city}.", "diagnostics": {"weather_api_used": True, "fallback_cli": True}}

	except Exception as e:
		return {"tool_name": tool_name, "status": "error", "reason": str(e)}


# --- ENRICHMENT ---

def enrich_plan_with_evidence(plan: dict, evidence_bundle: dict) -> dict:
	import re
	enriched = json.loads(json.dumps(plan))
	ev = enriched.get("entities_and_values") or {"locations": [], "persons": [], "organizations": [], "events": [], "data_points": []}

	# Ưu tiên Lớp 1: weather
	for item in evidence_bundle.get("layer_1_tools", []):
		if item.get("tool_name") == "weather" and item.get("status") == "success":
			data = item.get("data") or {}
			city = (data.get("city") or '').strip()
			if city and city not in ev.get("locations", []):
				ev.setdefault("locations", []).append(city)
			for key, suffix in [("temperature", "°C"), ("humidity", "%"), ("wind_speed", "m/s")]:
				val = data.get(key)
				if isinstance(val, (int, float)):
					ev.setdefault("data_points", []).append(f"{val}{suffix}")
			enriched["entities_and_values"] = ev
			break

	# Trích thêm data_points từ snippets L2 rồi L3
	def snippets(lvl: str):
		return [x.get("snippet") or "" for x in evidence_bundle.get(lvl, [])]
	pattern = re.compile(r"\b\d{1,3}\s?(?:°C|mm|%)\b")
	for lvl in ["layer_2_high_trust", "layer_3_general"]:
		for sn in snippets(lvl):
			for m in pattern.findall(sn):
				if m not in ev.setdefault("data_points", []):
					ev["data_points"].append(m)
	enriched["entities_and_values"] = ev

	return enriched


# --- ORCHESTRATOR ---

async def execute_tool_plan(plan: dict, site_query_string: str) -> dict:
	required_tools = plan.get("required_tools", [])
	evidence_bundle = {
		"layer_1_tools": [],
		"layer_2_high_trust": [],
		"layer_3_general": [],
		"layer_4_social_low": []
	}

	tasks = []

	for module in required_tools:
		tool_name = module.get("tool_name")
		parameters = module.get("parameters", {})
		if tool_name == "search":
			tasks.append(_execute_search_tool(parameters, site_query_string))
		elif tool_name == "weather":
			tasks.append(_execute_weather_tool(parameters, site_query_string))

	if not tasks:
		print("Cảnh báo: Không có tool nào được lập kế hoạch.")
		return evidence_bundle

	results = await asyncio.gather(*tasks)

	for res in results:
		if not res:
			continue
		tn = res.get("tool_name")
		if tn == "search":
			evidence_bundle["layer_2_high_trust"].extend(res.get("layer_2_high_trust", []))
			evidence_bundle["layer_3_general"].extend(res.get("layer_3_general", []))
			evidence_bundle["layer_4_social_low"].extend(res.get("layer_4_social_low", []))
		elif tn in ["weather", "econ_data", "sports_results"]:
			evidence_bundle["layer_1_tools"].append(res)

	# Fallback cuối: nếu toàn bộ bundle trống và có ít nhất một mô-đun search, chạy CSE một lượt với tất cả queries
	if not (evidence_bundle["layer_1_tools"] or evidence_bundle["layer_2_high_trust"] or evidence_bundle["layer_3_general"] or evidence_bundle["layer_4_social_low"]):
		all_queries = []
		for module in required_tools:
			if module.get("tool_name") == "search":
				all_queries.extend(module.get("parameters", {}).get("queries", []))
			break
		seen_urls = set()
		layer_2, layer_3, layer_4 = [], [], []
		for q in all_queries:
			try:
				items = await asyncio.to_thread(call_google_search, q, site_query_string)
				for item in items or []:
					link = item.get('link')
					if link and link not in seen_urls:
						rank_score = get_rank_from_url(link)
						mapped = {
							"source": urlparse(link).netloc.replace('www.', ''),
							"url": link,
							"snippet": (item.get('snippet', '') or ''),
							"rank_score": rank_score,
							"date": _extract_date(item)
						}
						if rank_score > 0.9:
							layer_2.append(mapped)
						elif rank_score > 0.5:
							layer_3.append(mapped)
						else:
							layer_4.append(mapped)
						seen_urls.add(link)
			except Exception as e:
				print(f"Fallback CSE batch error: {e}")
		layer_2.sort(key=lambda x: x.get('date') or '1970-01-01', reverse=True)
		layer_3.sort(key=lambda x: x.get('date') or '1970-01-01', reverse=True)
		evidence_bundle["layer_2_high_trust"].extend(layer_2)
		evidence_bundle["layer_3_general"].extend(layer_3)
		evidence_bundle["layer_4_social_low"].extend(layer_4)

	return evidence_bundle
