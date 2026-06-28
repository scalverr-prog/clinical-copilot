"""Web search for clinical references (PubMed, etc.)."""

import httpx
from typing import Optional
from pydantic import BaseModel


class SearchResult(BaseModel):
    """A search result."""
    title: str
    url: str
    snippet: str
    source: str


class PubMedArticle(BaseModel):
    """A PubMed article."""
    pmid: str
    title: str
    authors: list[str]
    journal: str
    year: int
    abstract: Optional[str] = None
    url: str


class WebSearch:
    """Web search for clinical references."""

    PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(self):
        self._client = httpx.Client(timeout=30)

    def search_pubmed(
        self,
        query: str,
        max_results: int = 5
    ) -> list[PubMedArticle]:
        """Search PubMed for articles."""
        try:
            # Search for IDs
            search_url = f"{self.PUBMED_BASE}/esearch.fcgi"
            search_params = {
                "db": "pubmed",
                "term": query,
                "retmax": max_results,
                "retmode": "json",
                "sort": "relevance",
            }
            response = self._client.get(search_url, params=search_params)
            response.raise_for_status()
            data = response.json()

            id_list = data.get("esearchresult", {}).get("idlist", [])
            if not id_list:
                return []

            # Fetch article details
            fetch_url = f"{self.PUBMED_BASE}/esummary.fcgi"
            fetch_params = {
                "db": "pubmed",
                "id": ",".join(id_list),
                "retmode": "json",
            }
            response = self._client.get(fetch_url, params=fetch_params)
            response.raise_for_status()
            data = response.json()

            articles = []
            result = data.get("result", {})
            for pmid in id_list:
                if pmid in result:
                    article_data = result[pmid]
                    authors = [
                        a.get("name", "")
                        for a in article_data.get("authors", [])[:3]
                    ]

                    articles.append(PubMedArticle(
                        pmid=pmid,
                        title=article_data.get("title", ""),
                        authors=authors,
                        journal=article_data.get("source", ""),
                        year=int(article_data.get("pubdate", "0")[:4] or 0),
                        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    ))

            return articles

        except httpx.RequestError as e:
            print(f"PubMed search error: {e}")
            return []

    def get_article_abstract(self, pmid: str) -> Optional[str]:
        """Fetch abstract for a PubMed article."""
        try:
            fetch_url = f"{self.PUBMED_BASE}/efetch.fcgi"
            params = {
                "db": "pubmed",
                "id": pmid,
                "retmode": "xml",
                "rettype": "abstract",
            }
            response = self._client.get(fetch_url, params=params)
            response.raise_for_status()

            # Simple XML parsing for abstract
            import re
            match = re.search(
                r"<AbstractText[^>]*>(.*?)</AbstractText>",
                response.text,
                re.DOTALL
            )
            if match:
                # Remove XML tags
                abstract = re.sub(r"<[^>]+>", "", match.group(1))
                return abstract.strip()

            return None

        except httpx.RequestError:
            return None

    def clinical_search(
        self,
        query: str,
        search_type: str = "all"
    ) -> list[SearchResult]:
        """Search for clinical information."""
        results = []

        if search_type in ["all", "pubmed"]:
            articles = self.search_pubmed(query, max_results=3)
            for article in articles:
                results.append(SearchResult(
                    title=article.title,
                    url=article.url,
                    snippet=f"{article.journal} ({article.year}) - {', '.join(article.authors)}",
                    source="PubMed",
                ))

        # Could add more sources: UpToDate, DynaMed, etc.
        # These typically require subscriptions/API keys

        return results

    def format_for_display(
        self,
        results: list[SearchResult]
    ) -> str:
        """Format search results for terminal display."""
        if not results:
            return "No results found."

        output = []
        for i, result in enumerate(results, 1):
            output.append(f"{i}. [{result.source}] {result.title}")
            output.append(f"   {result.snippet}")
            output.append(f"   {result.url}")
            output.append("")

        return "\n".join(output)

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
