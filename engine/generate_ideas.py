"""Deterministic literature search.

Idea generation is performed by the external AI harness through
``paperassist.agent_packs.build_ideation_pack``. What remains here is the part
that never needed a model: querying Semantic Scholar or OpenAlex and returning
structured paper metadata.
"""

from __future__ import annotations

import os
import time

import requests

S2_API_KEY = os.getenv("S2_API_KEY")
HTTP_CONNECT_TIMEOUT = 5
HTTP_READ_TIMEOUT = 20


def _is_truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def search_for_papers(query, result_limit=10, engine="semanticscholar") -> None | list[dict]:
    """Search a public literature index. Returns ``None`` when nothing matches."""

    if not query:
        return None
    if engine == "semanticscholar":
        debug_http = _is_truthy_env("PAPERASSIST_DEBUG_HTTP", "0")
        rsp = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            headers={"X-API-KEY": S2_API_KEY} if S2_API_KEY else {},
            params={
                "query": query,
                "limit": result_limit,
                "fields": "title,authors,venue,year,abstract,citationStyles,citationCount",
            },
            timeout=(HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT),
        )
        if debug_http:
            print(f"Response Status Code: {rsp.status_code}")
            print(f"Response Content: {rsp.text[:500]}")
        rsp.raise_for_status()
        results = rsp.json()
        total = results["total"]
        time.sleep(1.0)
        if not total:
            return None
        return results["data"]
    if engine == "openalex":
        import pyalex
        from pyalex import Work, Works

        mail = os.environ.get("OPENALEX_MAIL_ADDRESS", None)
        if mail is None:
            print("[WARNING] Please set OPENALEX_MAIL_ADDRESS for better access to OpenAlex API!")
        else:
            pyalex.config.email = mail

        def extract_info_from_work(work: Work, max_abstract_length: int = 1000) -> dict[str, str]:
            venue = "Unknown"
            for _i, location in enumerate(work["locations"]):
                if location["source"] is not None:
                    venue = location["source"]["display_name"]
                    break
            authors = []
            for authorship in work["authorships"]:
                if authorship and authorship["author"] and authorship["author"]["display_name"]:
                    authors.append(authorship["author"]["display_name"])
            abstract = work["abstract"] or ""
            if len(abstract) > max_abstract_length:
                abstract = abstract[:max_abstract_length] + "..."
            return {
                "title": work["title"] or "Unknown",
                "authors": authors,
                "venue": venue,
                "year": work["publication_year"],
                "abstract": abstract,
                "citationCount": work["cited_by_count"],
            }

        pager = Works().search(query).paginate(per_page=result_limit, n_max=result_limit)
        results = []
        for work in pager:
            if work is not None:
                results.append(extract_info_from_work(work))
        time.sleep(1.0)
        return results or None
    raise ValueError(f"Unknown literature engine: {engine}")


__all__ = ["search_for_papers"]
