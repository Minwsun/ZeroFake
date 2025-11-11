# app/tool_executor.py
import asyncio
import json
from urllib.parse import urlparse

from app.search import call_google_search
from app.ranker import get_rank_from_url, _extract_date


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


# --- ENRICHMENT ---

def enrich_plan_with_evidence(plan: dict, evidence_bundle: dict) -> dict:
	import re
	enriched = json.loads(json.dumps(plan))
	ev = enriched.get("entities_and_values") or {"locations": [], "persons": [], "organizations": [], "events": [], "data_points": []}

	# (XÓA BỎ) Logic enrich từ Lớp 1 (weather)

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
			# (Sửa đổi) Chỉ còn tool search
				tasks.append(_execute_search_tool(parameters, site_query_string, flash_mode=flash_mode))
		# (XÓA BỎ) elif tool_name == "weather":

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
		# (XÓA BỎ) elif tn in ["weather", ...]:

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
