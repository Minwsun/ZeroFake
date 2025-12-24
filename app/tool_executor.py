# app/tool_executor.py
import asyncio
import json
import os
from urllib.parse import urlparse
from datetime import datetime

from app.search import call_google_search
from app.ranker import get_rank_from_url, _extract_date
from app.weather import get_openweather_data, format_openweather_snippet
from app.article_scraper import scrape_multiple_articles, enrich_search_results_with_full_text
from app.fact_check import call_google_fact_check, interpret_fact_check_rating, format_fact_check_evidence


# --- SOURCE PRIORITIZATION HELPERS ---

# --- SEARCH TOOL (Gemini Web Search với fallback CSE) ---

async def _execute_search_tool(parameters: dict, site_query_string: str, flash_mode: bool = False) -> dict:
	"""Thực thi mô-đun "search" bằng DuckDuckGo (thông qua call_google_search)."""
	queries = parameters.get("queries", [])
	if not queries:
		return {"tool_name": "search", "status": "no_queries", "layer_2": [], "layer_3": [], "layer_4": []}

	# Mỗi query chỉ được tìm kiếm 1 lần (không giới hạn số lượng queries)
	all_items = []
	seen_urls = set()

	for query in queries:
		try:
			if flash_mode:
				search_items = await asyncio.to_thread(call_google_search, query, site_query_string)
			else:
				search_items = await asyncio.wait_for(
					asyncio.to_thread(call_google_search, query, site_query_string),
					timeout=25.0  # Tăng từ 15s để có thời gian thu thập nhiều evidence
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
		domain = urlparse(link).netloc.replace('www.', '')
		rank_score = get_rank_from_url(link)
		date_str = _extract_date(item)

		# Kiểm tra thông tin cũ (hơn 1 năm so với ngày hiện tại)
		is_old = False
		if date_str:
			try:
				from datetime import datetime, timedelta
				item_date = datetime.strptime(date_str, '%Y-%m-%d').date()
				today = datetime.now().date()
				days_diff = (today - item_date).days
				# Đánh dấu là thông tin cũ nếu hơn 365 ngày
				if days_diff > 365:
					is_old = True
			except Exception:
				pass

		evidence_item = {
			"source": domain,
			"url": link,
			"snippet": (item.get('snippet', '') or ''),
			"rank_score": rank_score,
			"date": date_str,
			"is_old": is_old,
		}
		if rank_score >= 0.5:  # BINARY: USABLE sources go to layer_2
			layer_2.append(evidence_item)
		else:  # BLOCKED sources (social, blog, tabloid) go to layer_4
			layer_4.append(evidence_item)

	# Sort by: date (newest first), rank_score (highest first)
	def sort_key(item):
		is_old = item.get('is_old', False)
		date_str = item.get('date') or '1970-01-01'
		rank_score = item.get('rank_score', 0.0)
		try:
			from datetime import datetime
			date_obj = datetime.strptime(date_str, '%Y-%m-%d')
			date_timestamp = date_obj.timestamp()
		except Exception:
			date_timestamp = 0
		return (is_old, -date_timestamp, -rank_score)
	
	layer_2.sort(key=sort_key)

	# Re-enabled article scraping for top 5 high-trust sources (accuracy > speed)
	top_evidence = layer_2[:5]  # Only scrape top 5 layer_2 for speed
	if top_evidence:
		urls_to_scrape = [item["url"] for item in top_evidence]
		try:
			scraped_articles = await scrape_multiple_articles(urls_to_scrape, max_articles=5)
			if scraped_articles:
				print(f"[SCRAPER] Scraped {len(scraped_articles)} articles for enrichment")
				# Enrich layer_2 snippets with full text
				for item in layer_2:
					for article in scraped_articles:
						if article.get("url") == item.get("url") and article.get("success"):
							full_text = article.get("text", "")
							if full_text and len(full_text) > 100:
								# Append first 800 chars of full text to snippet
								item["snippet"] = item.get("snippet", "") + "\n\n[FULL_TEXT]: " + full_text[:800]
							break
		except Exception as e:
			print(f"[SCRAPER] Warning (non-fatal): {e}")

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

	# =========================================================================
	# AUTO WEATHER: Check if planner detected weather claim
	# =========================================================================
	weather_query = plan.get("weather_query", {})
	if weather_query.get("is_weather_claim") and weather_query.get("location"):
		location = weather_query.get("location")
		days_ahead = weather_query.get("days_ahead", 0)
		time_ref = weather_query.get("time_reference", "today")
		
		# Convert time_reference to days_ahead if not set
		if time_ref == "tomorrow" and days_ahead == 0:
			days_ahead = 1
		
		print(f"\n[WEATHER] Auto-detected weather claim: {location}, days_ahead={days_ahead}")
		
		# Execute weather tool
		weather_result = await _execute_weather_tool({
			"city": location,
			"days_ahead": days_ahead
		}, flash_mode=flash_mode)
		
		if weather_result.get("status") == "success":
			evidence_bundle["layer_1_tools"].extend(weather_result.get("layer_1_tools", []))
			print(f"[WEATHER] OpenWeather data added to evidence")

	# FIX: Đảm bảo LUÔN có search tool nếu không có tool nào được lập kế hoạch
	has_search = any(m.get("tool_name") == "search" for m in required_tools)
	if not has_search:
		# Tạo search tool với main_claim hoặc text_input làm query
		main_claim = plan.get("main_claim", "")
		fallback_queries = [main_claim] if main_claim else []
		if fallback_queries:
			print(f"[TOOL_EXECUTOR] Không có search tool trong plan, tự động thêm với query: {main_claim[:50]}...")
			required_tools.append({
				"tool_name": "search",
				"parameters": {"queries": fallback_queries + [f"{main_claim} tin tức"]}
			})

	# =========================================================================
	# DATE-BASED ROUTING: Old info (>1 week) → Fact Check first
	# New info (≤1 week) → Skip fact check, search directly with priority news
	# =========================================================================
	from datetime import datetime, timedelta
	
	main_claim = plan.get("main_claim", "")
	
	# Check if claim mentions recent date (within 1 week)
	today = datetime.now().date()
	three_days_ago = today - timedelta(days=3)
	
	# Extract date hints from claim
	is_recent_news = False
	claim_lower = main_claim.lower() if main_claim else ""
	
	# Keywords indicating RECENT news (should skip fact check, search directly)
	recent_keywords = ["hôm nay", "today", "vừa", "mới đây", "just", "breaking", "nóng", 
	                   "vài giờ", "few hours", "sáng nay", "tối nay", "chiều nay"]
	for kw in recent_keywords:
		if kw in claim_lower:
			is_recent_news = True
			break
	
	# Also check for dates in claim (if within 1 week, it's recent)
	import re
	date_patterns = [
		r"(\d{1,2})/(\d{1,2})/(\d{4})",  # DD/MM/YYYY
		r"(\d{4})-(\d{1,2})-(\d{1,2})",  # YYYY-MM-DD
		r"tháng\s*(\d{1,2})/(\d{4})",     # tháng MM/YYYY
	]
	for pattern in date_patterns:
		match = re.search(pattern, main_claim)
		if match:
			try:
				# Parse and check if within 1 week
				groups = match.groups()
				if len(groups) == 3 and "/" in pattern:  # DD/MM/YYYY
					claim_date = datetime.strptime(f"{groups[0]}/{groups[1]}/{groups[2]}", "%d/%m/%Y").date()
				elif len(groups) == 3:  # YYYY-MM-DD
					claim_date = datetime.strptime(f"{groups[0]}-{groups[1]}-{groups[2]}", "%Y-%m-%d").date()
				if claim_date >= three_days_ago:
					is_recent_news = True
			except:
				pass
	
	# Route based on recency
	if is_recent_news:
		print(f"\n[RECENT NEWS] Skipping Fact Check, searching directly with priority news sources")
		# Search will use Google News + Bing priority (already configured in search.py)
	else:
		# OLD INFO: Try Fact Check API first
		if main_claim:
			print(f"\n[OLD INFO] Calling Fact Check API first for: {main_claim[:50]}...")
			try:
				fact_results = await call_google_fact_check(main_claim)
				
				if fact_results:
					# Get best verdict from fact check
					best_conclusion = ""
					best_confidence = 0
					best_source = ""
					best_url = ""
					
					for r in fact_results[:3]:
						conclusion, confidence = interpret_fact_check_rating(r.get("rating", ""))
						if confidence > best_confidence:
							best_conclusion = conclusion
							best_confidence = confidence
							best_source = r.get("publisher", "Unknown")
							best_url = r.get("url", "")
						
						# Add to evidence for reference
						evidence_bundle["layer_2_high_trust"].append({
							"source": f"[FACT-CHECK] {r.get('publisher', 'Unknown')}",
							"url": r.get("url", ""),
							"snippet": f"Claim: {r.get('claim', '')[:100]}... Rating: {r.get('rating', 'N/A')}",
							"rank_score": 0.95,
							"date": r.get("review_date", ""),
							"fact_check_conclusion": conclusion,
							"fact_check_confidence": confidence
						})
					
					# Store Fact Check verdict for JUDGE to consider
					if best_conclusion and best_confidence >= 70:
						print(f"[FACT-CHECK] ✓ Found verdict: {best_conclusion} ({best_confidence}%) from {best_source}")
						evidence_bundle["fact_check_verdict"] = {
							"conclusion": best_conclusion,
							"confidence": best_confidence,
							"source": best_source,
							"url": best_url
						}
						print(f"[FACT-CHECK] Verdict added to evidence → JUDGE will make final decision")
					else:
						print(f"[FACT-CHECK] Inconclusive rating, continuing with search")
				else:
					print(f"[OLD INFO] No Fact Check results → Continuing with search")
			except Exception as e:
				print(f"[OLD INFO] Fact check error (continuing with search): {e}")

	tasks = []

	for module in required_tools:
		tool_name = module.get("tool_name")
		parameters = module.get("parameters", {})
		if tool_name == "search":
			# Skip search if Fact Check has HIGH confidence verdict (≥70%)
			fact_verdict = evidence_bundle.get("fact_check_verdict")
			if fact_verdict and fact_verdict.get("confidence", 0) >= 70:
				print(f"[SEARCH] Skipping search - Fact Check has high confidence verdict ({fact_verdict.get('confidence')}%)")
			else:
				tasks.append(_execute_search_tool(parameters, site_query_string, flash_mode=flash_mode))
		elif tool_name == "weather":
			# Thêm tool weather với OpenWeather API
			tasks.append(_execute_weather_tool(parameters, flash_mode=flash_mode))

	if not tasks:
		print("Cảnh báo: Không có tool nào được lập kế hoạch.")
		# FIX: Vẫn chạy search fallback với main_claim
		main_claim = plan.get("main_claim", "")
		if main_claim:
			print(f"[TOOL_EXECUTOR] Chạy search fallback với main_claim...")
			fallback_result = await _execute_search_tool(
				{"queries": [main_claim, f"{main_claim} tin tức"]}, 
				site_query_string, 
				flash_mode
			)
			evidence_bundle["layer_2_high_trust"].extend(fallback_result.get("layer_2_high_trust", []))
			evidence_bundle["layer_3_general"].extend(fallback_result.get("layer_3_general", []))
			evidence_bundle["layer_4_social_low"].extend(fallback_result.get("layer_4_social_low", []))
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

	# IMPORTANT: Keep OpenWeather data in layer_1_tools for weather claims
	# Previously this was clearing layer_1_tools if web evidence existed - DON'T DO THAT
	# Weather data is essential for Judge to verify weather claims

	# (Fallback) nếu bundle trống, chạy CSE batch
	if not (evidence_bundle["layer_1_tools"] or evidence_bundle["layer_2_high_trust"] or evidence_bundle["layer_3_general"] or evidence_bundle["layer_4_social_low"]):
		print("[TOOL_EXECUTOR] Bundle trống sau khi chạy tools, chạy FALLBACK SEARCH...")
		
		# FIX: Lấy TẤT CẢ queries có thể
		all_queries = []
		for module in required_tools:
			if module.get("tool_name") == "search":
				all_queries.extend(module.get("parameters", {}).get("queries", []))
		
		# Nếu không có queries, dùng main_claim
		if not all_queries:
			main_claim = plan.get("main_claim", "")
			if main_claim:
				all_queries = [main_claim, f"{main_claim} tin tức"]
				
		seen_urls = set()
		layer_2, layer_3, layer_4 = [], [], []
		for q in all_queries:
			try:
				items = await asyncio.to_thread(call_google_search, q, site_query_string)
				for item in items or []:
					link = item.get('link')
					if link and link not in seen_urls:
						rank_score = get_rank_from_url(link)
						date_str = _extract_date(item)
						
						# Kiểm tra thông tin cũ (hơn 1 năm so với ngày hiện tại)
						is_old = False
						if date_str:
							try:
								from datetime import datetime
								item_date = datetime.strptime(date_str, '%Y-%m-%d').date()
								today = datetime.now().date()
								days_diff = (today - item_date).days
								# Đánh dấu là thông tin cũ nếu hơn 365 ngày
								if days_diff > 365:
									is_old = True
							except Exception:
								pass
						
						mapped = {
							"source": urlparse(link).netloc.replace('www.', ''),
							"url": link,
							"snippet": (item.get('snippet', '') or ''),
							"rank_score": rank_score,
							"date": date_str,
							"is_old": is_old  # Đánh dấu thông tin cũ
						}
						# BINARY CLASSIFICATION: usable vs blocked
						if rank_score >= 0.5:  # USABLE
							layer_2.append(mapped)
						else:  # BLOCKED
							layer_4.append(mapped)
						seen_urls.add(link)
			except Exception as e:
				print(f"Fallback CSE batch error: {e}")
		# Sắp xếp theo ngày (mới nhất trước) và ưu tiên thông tin không cũ
		def fallback_sort_key(item):
			is_old = item.get('is_old', False)
			date_str = item.get('date') or '1970-01-01'
			try:
				from datetime import datetime
				date_obj = datetime.strptime(date_str, '%Y-%m-%d')
				date_timestamp = date_obj.timestamp()
			except:
				date_timestamp = 0
			return (is_old, -date_timestamp)
		
		layer_2.sort(key=fallback_sort_key)
		layer_3.sort(key=fallback_sort_key)
		evidence_bundle["layer_2_high_trust"].extend(layer_2)
		evidence_bundle["layer_3_general"].extend(layer_3)
		evidence_bundle["layer_4_social_low"].extend(layer_4)
		
		print(f"[TOOL_EXECUTOR] Fallback search kết quả: L2={len(layer_2)}, L3={len(layer_3)}, L4={len(layer_4)}")

	return evidence_bundle
