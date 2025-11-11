# app/tool_executor.py
import asyncio
import json
from urllib.parse import urlparse
from datetime import datetime

from app.search import call_google_search
from app.ranker import get_rank_from_url, _extract_date
from app.weather import get_openweather_data, format_openweather_snippet


# --- SEARCH TOOL (Gemini Web Search với fallback CSE) ---

async def _execute_search_tool(parameters: dict, site_query_string: str, flash_mode: bool = False) -> dict:
	"""Thực thi mô-đun "search" bằng DuckDuckGo (thông qua call_google_search)."""
	queries = parameters.get("queries", [])
	if not queries:
		return {"tool_name": "search", "status": "no_queries", "layer_2": [], "layer_3": [], "layer_4": []}

	if not flash_mode:
		queries = queries[:3]
	
	all_items = []
	seen_urls = set()

	for query in queries:
		try:
			if flash_mode:
				search_items = await asyncio.to_thread(call_google_search, query, site_query_string)
			else:
				search_items = await asyncio.wait_for(
					asyncio.to_thread(call_google_search, query, site_query_string),
					timeout=15.0
				)
			for item in search_items or []:
				link = item.get('link')
				if link and link not in seen_urls:
					all_items.append(item)
					seen_urls.add(link)
		except asyncio.TimeoutError:
			print(f"Timeout khi thực thi DuckDuckGo query '{query}'")
			continue
		except Exception as e:
			print(f"Lỗi khi thực thi DuckDuckGo query '{query}': {e}")
			continue

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
		if rank_score >= 0.85:
			layer_2.append(evidence_item)
		elif rank_score >= 0.4:
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


# --- WEATHER TOOL (OpenWeather API) ---

async def _execute_weather_tool(parameters: dict, flash_mode: bool = False) -> dict:
	"""
	Thực thi mô-đun "weather" bằng OpenWeather API.
	
	Parameters:
		- city: Tên thành phố (bắt buộc)
		- days_ahead: Số ngày sau hôm nay (0 = hôm nay, 1 = ngày mai, ...)
		- date: Ngày cụ thể (YYYY-MM-DD, optional)
	"""
	city = parameters.get("city")
	if not city:
		print("ERROR: Weather tool - thiếu parameter 'city'")
		return {"tool_name": "weather", "status": "no_city", "layer_1_tools": []}
	
	days_ahead = parameters.get("days_ahead", 0)
	explicit_date = parameters.get("date")
	part_of_day = parameters.get("part_of_day")  # "sáng", "chiều", "tối"
	
	print(f"Weather Tool: Bắt đầu gọi OpenWeather API cho '{city}' (days_ahead={days_ahead}, date={explicit_date}, part_of_day={part_of_day})")
	
	# Nếu có explicit_date, tính days_ahead
	if explicit_date:
		try:
			target_date = datetime.strptime(explicit_date, '%Y-%m-%d')
			today = datetime.now().date()
			days_ahead = (target_date.date() - today).days
			print(f"Weather Tool: Chuyển đổi explicit_date '{explicit_date}' thành days_ahead={days_ahead}")
		except Exception as e:
			print(f"WARNING: Không thể parse explicit_date '{explicit_date}': {e}")
			pass
	
	try:
		# Gọi OpenWeather API với part_of_day
		if flash_mode:
			print(f"Weather Tool: Flash mode - gọi OpenWeather API không timeout")
			weather_data = await asyncio.to_thread(get_openweather_data, city, days_ahead, part_of_day)
		else:
			print(f"Weather Tool: Normal mode - gọi OpenWeather API với timeout 10s")
			weather_data = await asyncio.wait_for(
				asyncio.to_thread(get_openweather_data, city, days_ahead, part_of_day),
				timeout=10.0
			)
		
		if not weather_data:
			print(f"ERROR: Weather Tool - OpenWeather API không trả về dữ liệu cho '{city}'")
			print(f"Nguyên nhân có thể:")
			print(f"  1. API key không hợp lệ hoặc chưa được cấu hình")
			print(f"  2. Tên thành phố '{city}' không được OpenWeather nhận diện")
			print(f"  3. Lỗi kết nối mạng hoặc API không phản hồi")
			print(f"  4. Rate limit đã vượt quá")
			return {"tool_name": "weather", "status": "no_data", "layer_1_tools": []}
		
		print(f"Weather Tool: Thành công - nhận được dữ liệu từ OpenWeather cho '{city}'")
		
		# Format thành evidence item
		snippet = format_openweather_snippet(weather_data)
		evidence_item = {
			"source": "openweathermap.org",
			"url": f"https://openweathermap.org/city/{city}",
			"snippet": snippet,
			"rank_score": 0.95,  # OpenWeather là nguồn uy tín
			"date": weather_data.get("date", datetime.now().strftime('%Y-%m-%d')),
			"weather_data": weather_data  # Giữ nguyên dữ liệu gốc
		}
		
		print(f"Weather Tool: Đã format snippet: {snippet[:100]}...")
		
		return {
			"tool_name": "weather",
			"status": "success",
			"layer_1_tools": [evidence_item]
		}
		
	except asyncio.TimeoutError:
		print(f"ERROR: Weather Tool - Timeout khi gọi OpenWeather API cho '{city}' (quá 10 giây)")
		print(f"Nguyên nhân có thể: API chậm, mạng không ổn định, hoặc API không phản hồi")
		return {"tool_name": "weather", "status": "timeout", "layer_1_tools": []}
	except Exception as e:
		print(f"ERROR: Weather Tool - Exception khi gọi OpenWeather API cho '{city}': {type(e).__name__}: {e}")
		import traceback
		print(f"Traceback: {traceback.format_exc()[:300]}")
		return {"tool_name": "weather", "status": "error", "layer_1_tools": []}


# --- ENRICHMENT ---

def enrich_plan_with_evidence(plan: dict, evidence_bundle: dict) -> dict:
	import re
	enriched = json.loads(json.dumps(plan))
	ev = enriched.get("entities_and_values") or {"locations": [], "persons": [], "organizations": [], "events": [], "data_points": []}

	# Enrich từ Lớp 1 (OpenWeather API) - thêm data_points từ weather_data
	l1 = evidence_bundle.get("layer_1_tools", [])
	for item in l1:
		weather_data = item.get("weather_data", {})
		if weather_data:
			# Thêm nhiệt độ
			temp = weather_data.get("temperature")
			if temp:
				ev.setdefault("data_points", []).append(f"{temp}°C")
			# Thêm độ ẩm
			humidity = weather_data.get("humidity")
			if humidity:
				ev.setdefault("data_points", []).append(f"{humidity}%")
			# Thêm tốc độ gió
			wind = weather_data.get("wind_speed")
			if wind:
				ev.setdefault("data_points", []).append(f"{wind} m/s")

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

async def execute_tool_plan(plan: dict, site_query_string: str, flash_mode: bool = False) -> dict:
	required_tools = plan.get("required_tools", [])
	evidence_bundle = {
		"layer_1_tools": [], # Lớp 1 sẽ luôn rỗng
		"layer_2_high_trust": [],
		"layer_3_general": [],
		"layer_4_social_low": []
	}

	tasks = []

	for module in required_tools:
		tool_name = module.get("tool_name")
		parameters = module.get("parameters", {})
		if tool_name == "search":
			tasks.append(_execute_search_tool(parameters, site_query_string, flash_mode=flash_mode))
		elif tool_name == "weather":
			# Thêm tool weather với OpenWeather API
			tasks.append(_execute_weather_tool(parameters, flash_mode=flash_mode))

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
		elif tn == "weather":
			# Thêm dữ liệu OpenWeather vào layer_1_tools
			evidence_bundle["layer_1_tools"].extend(res.get("layer_1_tools", []))

	# (Fallback) nếu bundle trống, chạy CSE batch
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
						if rank_score >= 0.85:
							layer_2.append(mapped)
						elif rank_score >= 0.4:
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
