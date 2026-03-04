from __future__ import annotations

import json
import re
import time
from itertools import combinations
from typing import Any, Optional
from urllib import error, parse, request


class DrugInteractionService:
    FDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
    SOURCE_NAME = "FDA openFDA Drug Label API"
    SOURCE_URL = "https://open.fda.gov/apis/drug/label/"
    CACHE_TTL_SECONDS = 60 * 30

    INFORMATIONAL_DISCLAIMER = (
        "Informational only. This app does not provide medical advice, diagnosis, or treatment. "
        "Interaction and diet/nutrient signals are sourced from FDA labeling text and may be incomplete."
    )
    CLINICIAN_HANDOFF = (
        "Discuss potential medication or supplement interactions with a licensed physician or pharmacist "
        "before making changes."
    )

    _STOPWORDS = {"and", "with", "for", "the", "tablet", "capsule", "drug", "solution"}
    _SUPPLEMENT_HINTS = {
        "supplement",
        "vitamin",
        "mineral",
        "omega",
        "fish oil",
        "st john",
        "st. john",
        "ashwagandha",
        "ginkgo",
        "ginseng",
        "turmeric",
        "probiotic",
    }
    _DIET_SIGNAL_RULES = [
        {
            "type": "food_timing",
            "topic": "meal timing",
            "keywords": [
                "with food",
                "with meals",
                "without food",
                "empty stomach",
                "after meals",
                "before meals",
                "food effect",
                "administer with meals",
                "administer without regard to meals",
            ],
            "summary": "Label text includes food timing or meal administration guidance.",
        },
        {
            "type": "dietary_restriction",
            "topic": "alcohol",
            "keywords": ["alcohol", "ethanol"],
            "summary": "Label text includes alcohol-related dietary caution.",
        },
        {
            "type": "dietary_restriction",
            "topic": "grapefruit",
            "keywords": ["grapefruit"],
            "summary": "Label text includes grapefruit-related dietary caution.",
        },
        {
            "type": "nutrient_consideration",
            "topic": "vitamins",
            "keywords": [
                "vitamin",
                "folate",
                "folic acid",
                "vitamin b12",
                "vitamin k",
                "vitamin d",
            ],
            "summary": "Label text mentions vitamin-related nutrition considerations.",
        },
        {
            "type": "nutrient_consideration",
            "topic": "minerals and electrolytes",
            "keywords": [
                "calcium",
                "iron",
                "magnesium",
                "potassium",
                "sodium",
                "zinc",
                "phosphate",
            ],
            "summary": "Label text mentions mineral or electrolyte nutrition considerations.",
        },
        {
            "type": "metabolic_effect",
            "topic": "glucose and carbohydrates",
            "keywords": ["blood glucose", "hyperglycemia", "hypoglycemia", "carbohydrate"],
            "summary": "Label text mentions glucose or carbohydrate-related metabolic effects.",
        },
    ]

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self.source_status = "ok"
        self.source_error = ""
        self._search_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}

    def check_interactions(self, items: list[str] | str | None) -> dict[str, Any]:
        normalized_items = self._normalize_items(items)
        if len(normalized_items) < 2:
            raise ValueError("Provide at least two medications or supplements.")
        if len(normalized_items) > 8:
            raise ValueError("Provide at most eight items per check.")

        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []
        source_last_updated = ""

        for item in normalized_items:
            row = self._resolve_item(item)
            if not row:
                unresolved.append(item)
                continue
            resolved.append(row)
            if row.get("source_last_updated"):
                source_last_updated = row["source_last_updated"]

        pair_signals = self._build_pair_signals(resolved)
        diet_effects = self._build_diet_effects(resolved)
        notes: list[str] = []

        if unresolved:
            notes.append(f"No FDA label record was found for: {', '.join(unresolved)}.")
        if any(self._looks_like_supplement(name) for name in normalized_items):
            notes.append(
                "Supplement evidence can be limited in FDA labeling; absence of a mention does not rule out risk."
            )
        if not pair_signals and resolved:
            notes.append(
                "No explicit pair mention was found in the sampled FDA interaction sections. "
                "This is not a safety determination."
            )
        if not diet_effects and resolved:
            notes.append(
                "No explicit diet or nutrient keywords were found in the sampled FDA label sections. "
                "This is not a nutrition clearance."
            )
        else:
            notes.append(
                "Diet and nutrient effects are keyword-derived from FDA label text and may not capture all clinical context."
            )
        if self.source_status != "ok":
            notes.append(self._source_status_message())

        return {
            "disclaimer": self.INFORMATIONAL_DISCLAIMER,
            "clinician_handoff": self.CLINICIAN_HANDOFF,
            "source": {
                "name": self.SOURCE_NAME,
                "url": self.SOURCE_URL,
                "last_updated": source_last_updated or None,
                "status": self.source_status,
            },
            "items": [
                {
                    "input_name": row["input_name"],
                    "resolved_name": row["resolved_name"],
                    "matched_generic_name": row["matched_generic_name"],
                    "matched_brand_name": row["matched_brand_name"],
                    "effective_time": row["effective_time"],
                    "set_id": row["set_id"],
                    "source_url": row["source_url"],
                    "has_interaction_section": row["has_interaction_section"],
                    "has_diet_text": row["has_diet_text"],
                }
                for row in resolved
            ],
            "unresolved_items": unresolved,
            "pair_signals": pair_signals,
            "diet_effects": diet_effects,
            "notes": notes,
        }

    def _resolve_item(self, item_name: str) -> Optional[dict[str, Any]]:
        best: Optional[dict[str, Any]] = None
        for query in self._candidate_queries(item_name):
            payload = self._search_openfda(query=query, limit=20)
            if not payload:
                continue

            source_last_updated = payload.get("meta", {}).get("last_updated") or ""
            results = payload.get("results", [])
            if not results:
                continue

            candidate = self._pick_best_result(item_name, results)
            if not candidate:
                continue
            candidate["source_last_updated"] = source_last_updated
            if not best or candidate["score"] > best["score"]:
                best = candidate

        return best

    @staticmethod
    def _normalize_items(items: list[str] | str | None) -> list[str]:
        if items is None:
            return []
        if isinstance(items, str):
            raw = re.split(r"[\n,]", items)
        else:
            raw = [str(part) for part in items]

        normalized: list[str] = []
        seen: set[str] = set()
        for value in raw:
            item = re.sub(r"\s+", " ", value.strip().lower())
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        return normalized

    def _candidate_queries(self, item_name: str) -> list[str]:
        safe_item = item_name.replace('"', "")
        tokens = safe_item.split()
        queries: list[str] = []
        fields = ["openfda.generic_name", "openfda.brand_name", "openfda.substance_name"]

        for field in fields:
            queries.append(f'{field}:"{safe_item}"')

        if len(tokens) > 1:
            primary = tokens[0]
            for field in fields:
                queries.append(f'{field}:"{primary}"')

        seen: set[str] = set()
        deduped: list[str] = []
        for query in queries:
            if query not in seen:
                seen.add(query)
                deduped.append(query)
        return deduped

    def _search_openfda(self, query: str, limit: int = 20) -> dict[str, Any]:
        cache_key = (query, limit)
        cached = self._search_cache.get(cache_key)
        now = time.time()
        if cached and (now - cached[0]) < self.CACHE_TTL_SECONDS:
            return cached[1]

        url = f"{self.FDA_LABEL_URL}?{parse.urlencode({'search': query, 'limit': limit})}"
        try:
            with request.urlopen(url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code == 404:
                payload = {"meta": {}, "results": []}
            elif exc.code == 429:
                self._flag_source_issue("rate_limited", "FDA API rate-limited.")
                payload = {"meta": {}, "results": []}
            else:
                self._flag_source_issue("unavailable", f"FDA API HTTP error {exc.code}.")
                payload = {"meta": {}, "results": []}
        except (error.URLError, TimeoutError, ValueError):
            self._flag_source_issue("unavailable", "FDA API unavailable or returned invalid data.")
            payload = {"meta": {}, "results": []}

        self._search_cache[cache_key] = (now, payload)
        return payload

    @staticmethod
    def _normalized_names_from_openfda(result: dict[str, Any]) -> dict[str, list[str]]:
        openfda = result.get("openfda", {})

        def to_list(value: Any) -> list[str]:
            if value is None:
                return []
            if isinstance(value, list):
                rows = value
            else:
                rows = [value]
            output = []
            for item in rows:
                cleaned = re.sub(r"\s+", " ", str(item).strip().lower())
                if cleaned:
                    output.append(cleaned)
            return output

        return {
            "generic": to_list(openfda.get("generic_name")),
            "brand": to_list(openfda.get("brand_name")),
            "substance": to_list(openfda.get("substance_name")),
        }

    def _pick_best_result(self, item_name: str, results: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        best: Optional[dict[str, Any]] = None
        for result in results:
            names = self._normalized_names_from_openfda(result)
            all_names = names["generic"] + names["brand"] + names["substance"]
            score = self._name_match_score(item_name, all_names)
            if score <= 0:
                continue

            interaction_text = self._interaction_text_from_result(result)
            diet_text = self._diet_text_from_result(result)
            if interaction_text:
                score += 25.0
            if diet_text:
                score += 8.0
            product_types = [part.lower() for part in (result.get("openfda", {}).get("product_type") or [])]
            if any("prescription" in part for part in product_types):
                score += 5.0

            resolved_name = names["generic"][0] if names["generic"] else (names["brand"][0] if names["brand"] else item_name)
            set_id = str(result.get("set_id") or "")
            row = {
                "input_name": item_name,
                "resolved_name": resolved_name,
                "matched_generic_name": names["generic"][0] if names["generic"] else "",
                "matched_brand_name": names["brand"][0] if names["brand"] else "",
                "aliases": self._build_aliases(item_name, names),
                "interaction_text": interaction_text,
                "diet_text": diet_text,
                "has_interaction_section": bool(interaction_text.strip()),
                "has_diet_text": bool(diet_text.strip()),
                "effective_time": str(result.get("effective_time") or ""),
                "set_id": set_id,
                "source_url": self._dailymed_url(set_id),
                "score": score,
            }
            if not best or row["score"] > best["score"]:
                best = row

        return best

    @staticmethod
    def _name_match_score(item_name: str, candidates: list[str]) -> float:
        query = item_name.strip().lower()
        if not query:
            return 0.0
        query_tokens = [token for token in re.split(r"[^a-z0-9]+", query) if token]

        best = 0.0
        for candidate in candidates:
            value = 0.0
            if candidate == query:
                value += 120.0
            if candidate.startswith(query):
                value += 45.0
            if query in candidate:
                value += 25.0

            candidate_tokens = set(token for token in re.split(r"[^a-z0-9]+", candidate) if token)
            token_hits = sum(1 for token in query_tokens if token in candidate_tokens)
            value += token_hits * 9.0
            value -= abs(len(candidate) - len(query)) * 0.04
            if value > best:
                best = value
        return best

    @staticmethod
    def _interaction_text_from_result(result: dict[str, Any]) -> str:
        rows = result.get("drug_interactions") or []
        if not rows:
            rows = result.get("drug_and_or_laboratory_test_interactions") or []
        return DrugInteractionService._normalize_label_blob(rows)

    @staticmethod
    def _diet_text_from_result(result: dict[str, Any]) -> str:
        fields = [
            "drug_interactions",
            "drug_and_or_laboratory_test_interactions",
            "dosage_and_administration",
            "warnings",
            "warnings_and_precautions",
            "precautions",
            "adverse_reactions",
            "patient_medication_information",
            "information_for_patients",
            "patient_information",
            "boxed_warning",
            "contraindications",
        ]
        parts: list[str] = []
        for field in fields:
            value = result.get(field)
            normalized = DrugInteractionService._normalize_label_blob(value)
            if normalized:
                parts.append(normalized)
        return " ".join(parts).strip()

    @staticmethod
    def _normalize_label_blob(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            text = " ".join(str(part) for part in value)
        else:
            text = str(value)
        return re.sub(r"\s+", " ", text).strip()

    def _build_aliases(self, input_name: str, names: dict[str, list[str]]) -> list[str]:
        variants = {input_name.strip().lower()}
        for row in names["generic"] + names["brand"] + names["substance"]:
            variants.add(row.lower())
            for part in re.split(r"[/;,()]+", row.lower()):
                part = part.strip()
                if part:
                    variants.add(part)

        expanded: set[str] = set()
        for value in variants:
            value = re.sub(r"\s+", " ", value.strip().lower())
            if not value:
                continue
            expanded.add(value)
            tokens = [token for token in value.split() if token]
            if len(tokens) > 1 and len(tokens[0]) >= 4:
                expanded.add(tokens[0])

        cleaned = [
            item
            for item in expanded
            if len(item) >= 4 and item not in self._STOPWORDS and not item.isdigit()
        ]
        return sorted(cleaned, key=len, reverse=True)

    def _build_pair_signals(self, resolved_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for left, right in combinations(resolved_rows, 2):
            evidence: list[dict[str, Any]] = []

            mention_from_left = self._first_mention(left.get("interaction_text", ""), right.get("aliases", []))
            if mention_from_left:
                evidence.append(
                    {
                        "from_item": left["resolved_name"],
                        "mentions": right["resolved_name"],
                        "excerpt": mention_from_left,
                        "label_set_id": left["set_id"] or None,
                        "label_effective_time": left["effective_time"] or None,
                        "source_url": left["source_url"] or None,
                    }
                )

            mention_from_right = self._first_mention(right.get("interaction_text", ""), left.get("aliases", []))
            if mention_from_right:
                evidence.append(
                    {
                        "from_item": right["resolved_name"],
                        "mentions": left["resolved_name"],
                        "excerpt": mention_from_right,
                        "label_set_id": right["set_id"] or None,
                        "label_effective_time": right["effective_time"] or None,
                        "source_url": right["source_url"] or None,
                    }
                )

            if evidence:
                signals.append(
                    {
                        "pair": [left["resolved_name"], right["resolved_name"]],
                        "summary": "Reported interaction mention found in FDA drug labeling text.",
                        "confidence": "label_mention",
                        "evidence": evidence,
                    }
                )

        signals.sort(key=lambda row: len(row.get("evidence", [])), reverse=True)
        return signals

    def _build_diet_effects(self, resolved_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for row in resolved_rows:
            text = row.get("diet_text", "")
            if not text:
                continue

            signals: list[dict[str, Any]] = []
            for rule in self._DIET_SIGNAL_RULES:
                keyword, excerpt = self._first_keyword_mention(text, rule["keywords"])
                if not keyword:
                    continue
                signals.append(
                    {
                        "type": rule["type"],
                        "topic": rule["topic"],
                        "summary": rule["summary"],
                        "matched_keyword": keyword,
                        "excerpt": excerpt,
                        "label_effective_time": row.get("effective_time") or None,
                        "source_url": row.get("source_url") or None,
                    }
                )

            if signals:
                output.append(
                    {
                        "item": row.get("resolved_name") or row.get("input_name"),
                        "signals": signals,
                    }
                )

        return output

    @staticmethod
    def _first_keyword_mention(text: str, keywords: list[str]) -> tuple[str, str]:
        if not text:
            return "", ""
        lowered = text.lower()
        for keyword in keywords:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(keyword.lower())}(?![a-z0-9])", re.IGNORECASE)
            match = pattern.search(lowered)
            if not match:
                continue

            start = max(0, match.start() - 115)
            end = min(len(text), match.end() + 115)
            excerpt = text[start:end].strip()
            if start > 0:
                excerpt = f"...{excerpt}"
            if end < len(text):
                excerpt = f"{excerpt}..."
            return keyword, excerpt
        return "", ""

    @staticmethod
    def _first_mention(text: str, aliases: list[str]) -> str:
        if not text:
            return ""
        lowered = text.lower()
        for alias in aliases:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.IGNORECASE)
            match = pattern.search(lowered)
            if not match:
                continue

            start = max(0, match.start() - 110)
            end = min(len(text), match.end() + 110)
            excerpt = text[start:end].strip()
            if start > 0:
                excerpt = f"...{excerpt}"
            if end < len(text):
                excerpt = f"{excerpt}..."
            return excerpt
        return ""

    @staticmethod
    def _dailymed_url(set_id: str) -> str:
        if not set_id:
            return ""
        return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"

    def _flag_source_issue(self, status: str, message: str) -> None:
        if self.source_status == "ok":
            self.source_status = status
            self.source_error = message

    def _source_status_message(self) -> str:
        if self.source_status == "rate_limited":
            return "FDA source is currently rate-limited; results may be incomplete."
        if self.source_error:
            return self.source_error
        return "Source data is partially unavailable."

    def _looks_like_supplement(self, item_name: str) -> bool:
        lowered = item_name.lower()
        return any(hint in lowered for hint in self._SUPPLEMENT_HINTS)
