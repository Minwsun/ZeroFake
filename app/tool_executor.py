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


# --- SOURCE PRIORITIZATION HELPERS ---

_TRUSTED_DOMAINS_CACHE: tuple[set[str], set[str]] | None = None


def _load_trusted_domains() -> tuple[set[str], set[str]]:
	"""
	Tải danh sách domain uy tín từ file JSON (app/trusted_domains.json) và merge với mặc định.
	Cho phép người dùng tự mở rộng lên hàng trăm / hàng ngàn domain mà không cần sửa code.
	"""
	global _TRUSTED_DOMAINS_CACHE
	if _TRUSTED_DOMAINS_CACHE is not None:
		return _TRUSTED_DOMAINS_CACHE

	# Mặc định tier 0 và tier 1 (giữ như trước)
	tier0_default = {
		# VN government & cơ quan nhà nước
		"chinhphu.vn",
		"moh.gov.vn",
		"moet.gov.vn",
		"mof.gov.vn",
		"sbv.gov.vn",
		"vncert.gov.vn",
		# International organizations
		"who.int",
		"un.org",
		"worldbank.org",
		"imf.org",
		"ec.europa.eu",
		# Major news wires & global press
		"reuters.com",
		"apnews.com",
		"afp.com",
		"bbc.com",
		"nytimes.com",
		"theguardian.com",
		"washingtonpost.com",
		"wsj.com",
		"ft.com",
		# Major Vietnamese press
		"vnexpress.net",
		"dantri.com.vn",
		"tuoitre.vn",
		"thanhnien.vn",
		"vietnamnet.vn",
		"vtv.vn",
		"vov.vn",
		"nhandan.vn",
		"qdnd.vn",
		"cand.com.vn",
		"laodong.vn",
		"tienphong.vn",
		"zingnews.vn",
	}

	tier1_default = {
		"bloomberg.com",
		"cnbc.com",
		"forbes.com",
		"yahoo.com",
		"marketwatch.com",
		"nature.com",
		"science.org",
		"sciencemag.org",
		"techcrunch.com",
		"wired.com",
		"theverge.com",
		"engadget.com",
		"pcmag.com",
		"cnet.com",
		"cointelegraph.com",
		"coindesk.com",
	}

	tier0 = {d.lower() for d in tier0_default}
	tier1 = {d.lower() for d in tier1_default}

	# Đọc mở rộng từ file JSON nếu có
	json_path = os.path.join(os.path.dirname(__file__), "trusted_domains.json")
	try:
		with open(json_path, "r", encoding="utf-8") as f:
			data = json.load(f)
		extra_tier0 = data.get("tier0") or []
		extra_tier1 = data.get("tier1") or []
		tier0.update(d.lower() for d in extra_tier0 if isinstance(d, str))
		tier1.update(d.lower() for d in extra_tier1 if isinstance(d, str))
		print(f"SourcePriorities: loaded {len(extra_tier0)} tier0 and {len(extra_tier1)} tier1 domains from trusted_domains.json")
	except FileNotFoundError:
		# Không sao, dùng mặc định
		pass
	except Exception as e:  # noqa: BLE001
		print(f"WARNING: Cannot load trusted_domains.json: {type(e).__name__}: {e}")

	_TRUSTED_DOMAINS_CACHE = (tier0, tier1)
	return _TRUSTED_DOMAINS_CACHE


def _get_source_tier(domain: str) -> int:
	"""
	Xếp hạng độ "chính thống" của nguồn (tự động + theo danh sách):
	- 0: Cực kỳ chính thống (chính phủ, tổ chức lớn, báo quốc gia lớn)
	- 1: Trung bình / báo chí, tạp chí uy tín, nguồn chuyên ngành lớn
	- 2: Còn lại (blog, forum, mạng xã hội, trang tổng hợp)
	"""
	d = (domain or "").lower()

	# Bỏ "www."
	if d.startswith("www."):
		d = d[4:]

	# .gov / .gov.vn luôn coi là tier 0
	official_suffixes = (".gov", ".gov.vn")
	if d.endswith(official_suffixes):
		return 0

	tier0, tier1 = _load_trusted_domains()

	# Ưu tiên domain có trong trusted_domains.json
	if d in tier0:
		return 0
	if d in tier1:
		return 1

	# Heuristic tự động theo lĩnh vực
	news_keywords = ("news", "press", "times", "post", "journal", "tribune", "herald")
	business_keywords = ("finance", "money", "market", "bloomberg", "stock", "economy", "business")
	weather_keywords = ("weather", "climate", "meteo", "forecast")
	sports_keywords = ("sport", "sports", "soccer", "football", "basketball", "tennis", "fifa", "uefa")
	tech_keywords = ("tech", "technology", "android", "apple", "pcmag", "gsmarena", "hardware")
	science_keywords = ("science", "nature", "sciencemag", "research", "journal", "academy")

	if any(kw in d for kw in news_keywords):
		return 1
	if any(kw in d for kw in business_keywords):
		return 1
	if any(kw in d for kw in weather_keywords):
		return 1
	if any(kw in d for kw in sports_keywords):
		return 1
	if any(kw in d for kw in tech_keywords):
		return 1
	if any(kw in d for kw in science_keywords):
		return 1

	return 2


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

		source_tier = _get_source_tier(domain)

		evidence_item = {
			"source": domain,
			"url": link,
			"snippet": (item.get('snippet', '') or ''),
			"rank_score": rank_score,
			"date": date_str,
			"is_old": is_old,  # Đánh dấu thông tin cũ
			"source_tier": source_tier,  # Độ chính thống của nguồn
		}
		if rank_score >= 0.85:
			layer_2.append(evidence_item)
		elif rank_score >= 0.4:
			layer_3.append(evidence_item)
		else:
			layer_4.append(evidence_item)

	# Sắp xếp theo:
	# 1) Nguồn chính thống hơn (source_tier thấp hơn)
	# 2) Không cũ (is_old = False)
	# 3) Ngày mới hơn
	# 4) rank_score cao hơn
	def sort_key(item):
		source_tier = item.get('source_tier', 2)
		is_old = item.get('is_old', False)
		date_str = item.get('date') or '1970-01-01'
		rank_score = item.get('rank_score', 0.0)
		try:
			from datetime import datetime
			date_obj = datetime.strptime(date_str, '%Y-%m-%d')
			date_timestamp = date_obj.timestamp()
		except Exception:
			date_timestamp = 0
		# tier: thấp hơn = tốt hơn; is_old False tốt hơn; date mới hơn tốt hơn; rank_score cao hơn tốt hơn
		return (source_tier, is_old, -date_timestamp, -rank_score)
	
	layer_2.sort(key=sort_key)
	layer_3.sort(key=sort_key)

	# Scrape full article content for top results using Crawl4ai
	all_evidence = layer_2 + layer_3
	if all_evidence:
		urls_to_scrape = [item["url"] for item in all_evidence[:15]]  # Top 15 URLs (tăng từ 8)
		try:
			scraped_articles = await scrape_multiple_articles(urls_to_scrape, max_articles=15)
			if scraped_articles:
				print(f"[CRAWL4AI] Ban đầu: Đã cào {len(scraped_articles)} bài viết")
				# Enrich results with full text
				for item in layer_2 + layer_3:
					for article in scraped_articles:
						if article.get("url") == item.get("url") and article.get("success"):
							full_text = article.get("text", "")
							if full_text:
								# Append full text to snippet for better context
								item["snippet"] = item.get("snippet", "") + "\n\n[NỘI DUNG ĐẦY ĐỦ]: " + full_text
							break
		except Exception as e:
			print(f"[CRAWL4AI] Lỗi khi cào: {e}")

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

	# Nếu đã có bất kỳ evidence nào từ web (L2/L3/L4),
	# thì layer_1_tools chỉ được sử dụng như fallback: xoá để Agent 2 không ưu tiên dùng.
	if evidence_bundle["layer_2_high_trust"] or evidence_bundle["layer_3_general"] or evidence_bundle["layer_4_social_low"]:
		if evidence_bundle["layer_1_tools"]:
			print("ToolExecutor: Đã có evidence từ web, bỏ qua layer_1_tools (tool) theo yêu cầu ưu tiên.")
			evidence_bundle["layer_1_tools"] = []

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
						if rank_score >= 0.85:
							layer_2.append(mapped)
						elif rank_score >= 0.4:
							layer_3.append(mapped)
						else:
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
