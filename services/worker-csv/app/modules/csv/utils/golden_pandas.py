from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger("app.csv.golden_pandas")

class GoldenPandasManager:
    """Manages a library of known-correct Pandas analysis plans for few-shot prompting."""

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = Path(storage_path or ".cache/golden_pandas.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.examples: List[Dict[str, str]] = self._load_examples()

    def _load_examples(self) -> List[Dict[str, str]]:
        """Load examples from disk, or return defaults if empty."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("failed_to_load_golden_pandas", error=str(e))
        
        # Default "Golden" examples for CSV/Pandas analysis
        return [
            {
                "question": "Show the monthly trend of revenue for the last year.",
                "intent": "trend",
                "plan": {
                    "operation": "trend",
                    "date_column": "order_date",
                    "value_column": "revenue",
                    "group_by": "month"
                }
            },
            {
                "question": "What is the correlation between marketing spend and signups?",
                "intent": "correlation",
                "plan": {
                    "operation": "correlation",
                    "columns": ["marketing_spend", "signups"]
                }
            },
            {
                "question": "Rank the top 10 products by sales volume.",
                "intent": "ranking",
                "plan": {
                    "operation": "ranking",
                    "rank_column": "sales_volume",
                    "label_column": "product_name",
                    "top_n": 10
                }
            },
            {
                "question": "Forecast the sales for the next 30 days.",
                "intent": "forecast",
                "plan": {
                    "operation": "forecast",
                    "date_column": "date",
                    "value_column": "sales",
                    "periods": 30
                }
            }
        ]

    def get_similar_examples(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Retrieve examples most relevant to the user query."""
        scored_examples = []
        query_terms = set(query.lower().split())
        
        for ex in self.examples:
            ex_terms = set(ex["question"].lower().split())
            score = len(query_terms.intersection(ex_terms))
            scored_examples.append((score, ex))
            
        scored_examples.sort(key=lambda x: x[0], reverse=True)
        return [ex for score, ex in scored_examples[:limit]]

    def add_example(self, question: str, intent: str, plan: Dict[str, Any]):
        """Add a new golden example to the library."""
        self.examples.append({"question": question, "intent": intent, "plan": plan})
        try:
            with open(self.storage_path, "w") as f:
                json.dump(self.examples, f, indent=2)
        except Exception as e:
            logger.error("failed_to_save_golden_pandas", error=str(e))

# Singleton instance
golden_pandas_manager = GoldenPandasManager()
