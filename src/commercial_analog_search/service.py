"""Reusable orchestration API."""

import logging
import time
from dataclasses import replace
from pathlib import Path

from .config import SearchConfig
from .export import export_log, export_query_summary, export_results
from .input import read_queries
from .models import QueryMolecule, SearchMatch
from .search import search_provider

LOG = logging.getLogger(__name__)


class CommercialAnalogSearch:
    """Search one or more indexed commercial catalogues."""

    def __init__(
        self,
        index_root: Path | str = "indices",
        config: SearchConfig | None = None,
        local_cache_root: Path | str | None = None,
    ):
        self.index_root = Path(index_root)
        self.config = config or SearchConfig()
        self.local_cache_root = Path(local_cache_root) if local_cache_root is not None else None

    def search(
        self, queries: list[QueryMolecule], providers: list[str]
    ) -> tuple[list[SearchMatch], list[dict]]:
        matches: list[SearchMatch] = []
        logs: list[dict] = []
        for query in queries:
            query_matches: list[SearchMatch] = []
            thresholds = (
                [self.config.threshold]
                if self.config.mode in {"fixed", "topk"}
                else [self.config.minimum_threshold]
                if self.config.all_above_minimum
                else [self.config.threshold, *self.config.fallback_thresholds]
            )
            provider_stats = {
                provider: {"elapsed": 0.0, "error": "", "matches": 0} for provider in providers
            }
            failed: set[str] = set()
            for threshold in thresholds:
                level_matches: list[SearchMatch] = []
                level_config = replace(
                    self.config,
                    threshold=threshold,
                    fallback_thresholds=(),
                    all_above_minimum=False,
                )
                for provider in providers:
                    if provider in failed:
                        continue
                    started = time.perf_counter()
                    try:
                        found = search_provider(
                            query,
                            provider,
                            self.index_root,
                            level_config,
                            self.local_cache_root,
                        )
                        level_matches.extend(found)
                        provider_stats[provider]["matches"] = len(found)
                    except Exception as exc:
                        failed.add(provider)
                        provider_stats[provider]["error"] = str(exc)
                        LOG.exception("Search failed for %s/%s", query.molecule_id, provider)
                    finally:
                        provider_stats[provider]["elapsed"] += time.perf_counter() - started
                if level_matches:
                    query_matches = level_matches
                    break
            for provider in providers:
                stats = provider_stats[provider]
                logs.append(
                    {
                        "molecule_id": query.molecule_id,
                        "provider": provider,
                        "status": "error" if provider in failed else "ok",
                        "matches": stats["matches"],
                        "elapsed_seconds": round(stats["elapsed"], 6),
                        "error": stats["error"],
                    }
                )
            query_matches.sort(key=lambda item: item.similarity, reverse=True)
            if self.config.mode == "topk":
                query_matches = query_matches[: self.config.top_k]
            if self.config.max_results is not None:
                query_matches = query_matches[: self.config.max_results]
            matches.extend(query_matches)
        return matches, logs

    def search_file(
        self, input_path: Path | str, providers: list[str], output: Path | str
    ) -> dict[str, int]:
        queries, input_errors = read_queries(Path(input_path))
        matches, logs = self.search(queries, providers)
        for error in input_errors:
            logs.append(
                {
                    "molecule_id": "",
                    "provider": "",
                    "status": "input_error",
                    "matches": 0,
                    "elapsed_seconds": 0,
                    "error": error,
                }
            )
        destination = Path(output)
        stats = export_results(queries, matches, destination)
        export_log(logs, destination)
        export_query_summary(queries, matches, logs, self.config, destination)
        return {
            **stats,
            "queries": len(queries),
            "errors": sum(row["status"] != "ok" for row in logs),
        }
