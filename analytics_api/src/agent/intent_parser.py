"""
intent_parser.py — IntentParser

Single LLM call that extracts a structured QueryIntent from a natural
language question. The LLM sees only the question plus a compact schema of
valid metric names, dimension names, and filter field names — NOT the full
BigQuery schema.

Total input budget: ~250 tokens (vs ~7,800 in the current s2s/ask pipeline).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from analytics_api.src.agent.config import AgentConfig
from analytics_api.src.agent.models import FilterCondition, QueryIntent, TimeRange
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    m = _JSON_FENCE.search(text)
    return m.group(1) if m else text.strip()


def _build_system_prompt(loader: SemanticLayerLoader) -> str:
    metric_names = [m.name for m in loader.list_metrics()]
    entity_attrs: List[str] = []
    for entity in loader.list_entities():
        for attr in entity.attributes:
            entity_attrs.append(f"{entity.name}.{attr}")

    return f"""You are a query intent extractor for a credit risk analytics platform.

Given a natural language question, extract structured intent as a JSON object.

Valid metric names: {json.dumps(metric_names)}

Common dimension/filter fields: product_type, state, fico_tier, dti_tier, channel,
loan_status, quarter, month, year, period_end_date, origination_date

JSON schema (all fields optional):
{{
  "metric": "<MetricName or null>",
  "dimensions": ["<dim1>", ...],
  "filters": [{{"field": "<f>", "operator": "<op>", "value": "<v>"}}],
  "time_range": {{"start": "<ISO date or null>", "end": "<ISO date or null>"}},
  "product_type": "<PERSONAL_LOAN|MORTGAGE|CREDIT_CARD|ALL|null>",
  "is_timeseries": <true|false>,
  "is_breakdown": <true|false>
}}

Rules:
- Return ONLY valid JSON. No explanation, no markdown.
- "over time" / "by month" / "trend" → is_timeseries: true
- "by X" where X is a dimension → is_breakdown: true, add X to dimensions
- If the metric is unclear, set metric to null (do not guess).
"""


class IntentParser:
    """Extract QueryIntent from a natural language question via a single LLM call.

    Example::

        parser = IntentParser(config)
        intent = await parser.parse("delinquency rate for personal loans in 2024")
        # QueryIntent(metric="DelinquencyRate",
        #             filters=[FilterCondition(field="year", op="=", value="2024")],
        #             product_type="PERSONAL_LOAN", is_timeseries=False)
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        loader: Optional[SemanticLayerLoader] = None,
    ) -> None:
        self._config = config or AgentConfig()
        self._loader = loader or get_loader()
        self._system_prompt: Optional[str] = None

    async def parse(self, question: str) -> QueryIntent:
        """Call the LLM and return a structured QueryIntent."""
        if not self._config.azure_endpoint or not self._config.azure_api_key:
            logger.warning("IntentParser: Azure OpenAI not configured — returning empty intent")
            return QueryIntent(raw_question=question)

        system = self._get_system_prompt()
        url = (
            f"{self._config.azure_endpoint.rstrip('/')}/openai/deployments/"
            f"{self._config.azure_deployment}/chat/completions"
            f"?api-version={self._config.azure_api_version}"
        )
        body = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "temperature": self._config.intent_temperature,
            "max_tokens": self._config.intent_max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url, json=body, headers={"api-key": self._config.azure_api_key}
                )
                resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectTimeout, Exception) as exc:
            logger.warning("IntentParser: Azure call failed (%s) — returning empty intent for keyword fallback", exc)
            return QueryIntent(raw_question=question)

        raw = resp.json()["choices"][0]["message"]["content"]
        return self._parse_response(raw, question)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _build_system_prompt(self._loader)
        return self._system_prompt

    def _parse_response(self, raw: str, question: str) -> QueryIntent:
        try:
            json_str = _extract_json(raw)
            data: Dict[str, Any] = json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("IntentParser: JSON parse failed (%s) — raw: %r", exc, raw[:200])
            return QueryIntent(raw_question=question)

        filters = [
            FilterCondition(
                field=f.get("field", ""),
                operator=f.get("operator", "="),
                value=f.get("value"),
            )
            for f in data.get("filters", [])
        ]

        time_range = None
        tr = data.get("time_range")
        if tr:
            time_range = TimeRange(
                start=tr.get("start"),
                end=tr.get("end"),
            )

        return QueryIntent(
            metric=data.get("metric"),
            dimensions=data.get("dimensions", []),
            filters=filters,
            time_range=time_range,
            product_type=data.get("product_type"),
            is_timeseries=bool(data.get("is_timeseries", False)),
            is_breakdown=bool(data.get("is_breakdown", False)),
            raw_question=question,
        )
