"""
DAX Research Module - Retrieves optimization articles based on query patterns.
Integrates with existing analysis infrastructure and can fetch online resources.
"""
import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

class DaxResearchProvider:
    """
    Provides DAX optimization research and guidance.
    Integrates with existing analysis workflows.

    Features:
    - Pattern-based anti-pattern detection
    - Online article fetching (when enabled)
    - Context-aware improvement suggestions
    - Integration with DAX Intelligence tool
    """

    def __init__(self, enable_online_research: bool = False):
        """
        Initialize DAX Research Provider

        Args:
            enable_online_research: If True, will fetch content from URLs when available
        """
        self.article_patterns = self._load_article_patterns()
        self.enable_online_research = enable_online_research
        self._article_cache = {}  # Cache fetched articles

    def get_optimization_guidance(
        self, query: str, performance_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get optimization guidance for a DAX query.

        Args:
            query: DAX query to analyze
            performance_data: Optional performance metrics from profiling

        Returns:
            Research results with matched articles and recommendations
        """
        # Analyze query patterns
        matched_articles, pattern_matches = self._analyze_query_patterns(query)

        # Build article summaries (without web fetching for now)
        articles = self._build_article_summaries(matched_articles, pattern_matches)

        # Generate recommendations based on patterns and performance
        recommendations = self._generate_recommendations(
            pattern_matches, performance_data
        )

        return {
            "status": "success",
            "total_articles": len(articles),
            "articles": articles,
            "pattern_matches": pattern_matches,
            "recommendations": recommendations
        }

    def _analyze_query_patterns(self, query: str) -> Tuple[List[str], Dict[str, List[Dict]]]:
        """Analyze query for optimization patterns"""
        matched_articles = []
        pattern_matches = {}

        for article_id, config in self.article_patterns.items():
            patterns = config.get("patterns", [])

            if not patterns:
                # Skip general framework articles — only include articles that match actual patterns
                continue

            article_matches = []
            for pattern in patterns:
                try:
                    for match in re.finditer(pattern, query, re.IGNORECASE | re.DOTALL):
                        context_start = max(0, match.start() - 50)
                        context_end = min(len(query), match.end() + 50)

                        article_matches.append({
                            "matched_text": match.group(0).strip(),
                            "context": query[context_start:context_end].strip()
                        })
                except re.error:
                    logger.warning(f"Invalid regex pattern in article {article_id}")
                    continue

            if article_matches:
                matched_articles.append(article_id)
                pattern_matches[article_id] = article_matches

        return matched_articles, pattern_matches

    def _build_article_summaries(
        self, article_ids: List[str], pattern_matches: Dict[str, List]
    ) -> List[Dict[str, Any]]:
        """Build article summaries from patterns"""
        articles = []

        for article_id in article_ids:
            config = self.article_patterns.get(article_id, {})

            article = {
                "id": article_id,
                "title": config.get("title", article_id),
                "url": config.get("url", ""),
                "content": config.get("content", ""),
                "matched_patterns": pattern_matches.get(article_id, []),
                "source": "embedded"  # Default to embedded content
            }

            # If online research is enabled and URL exists, try to fetch
            if self.enable_online_research and config.get("url"):
                online_content = self._fetch_article_content(config["url"], article_id)
                if online_content:
                    article["content"] = online_content
                    article["source"] = "online"
                    article["content_note"] = "Fetched from online source"

            articles.append(article)

        return articles

    def _fetch_article_content(self, url: str, article_id: str) -> Optional[str]:
        """
        Fetch article content from URL with proper HTML parsing

        Args:
            url: Article URL
            article_id: Article identifier for caching

        Returns:
            Article content or None if fetch fails
        """
        # Check cache first
        if article_id in self._article_cache:
            logger.debug(f"Using cached content for {article_id}")
            return self._article_cache[article_id]

        try:
            # Try importing requests (optional dependency)
            try:
                import requests
            except ImportError:
                logger.warning("⚠️ requests library not available - online research disabled. Install: pip install requests")
                return None

            # Try importing HTML parser
            try:
                from bs4 import BeautifulSoup
                has_bs4 = True
            except ImportError:
                logger.info("BeautifulSoup not available - using basic text extraction")
                has_bs4 = False

            # Fetch with timeout
            logger.info(f"🌐 Fetching online content from {url}")
            response = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            })

            if response.status_code == 200:
                # Extract text content with proper HTML parsing
                if has_bs4:
                    soup = BeautifulSoup(response.content, 'html.parser')

                    # Remove script and style elements
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.decompose()

                    # Get text from main content areas
                    main_content = None
                    for selector in ['article', '.article-content', '.post-content', '.entry-content', 'main']:
                        main_content = soup.select_one(selector)
                        if main_content:
                            break

                    text = main_content.get_text(separator=' ', strip=True) if main_content else soup.get_text(separator=' ', strip=True)
                    text = ' '.join(text.split())
                    content = text[:10000] if len(text) > 10000 else text
                else:
                    # Basic text extraction
                    import re
                    text = response.text
                    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = ' '.join(text.split())
                    content = text[:5000]

                self._article_cache[article_id] = content
                logger.info(f"✅ Successfully fetched {len(content)} chars for {article_id}")
                return content
            else:
                logger.warning(f"❌ Failed to fetch {url}: HTTP {response.status_code}")
                return None

        except requests.Timeout:
            logger.warning(f"⏱️ Timeout fetching {article_id} from {url}")
            return None
        except requests.RequestException as e:
            logger.warning(f"🌐 Network error fetching {article_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"💥 Unexpected error fetching {article_id}: {e}", exc_info=True)
            return None

    def _generate_recommendations(
        self,
        pattern_matches: Dict[str, List],
        performance_data: Optional[Dict[str, Any]]
    ) -> List[str]:
        """Generate specific recommendations based on detected patterns"""
        recommendations = []

        # Priority-ordered recommendations (most impactful first)
        pattern_recommendations = {
            "sumx_filter": {
                "priority": 1,
                "message": "🔴 HIGH IMPACT: Replace SUMX(FILTER(...)) with CALCULATE(SUM(...), filters) for 5-10x performance improvement"
            },
            "countrows_filter": {
                "priority": 1,
                "message": "🔴 HIGH IMPACT: Replace COUNTROWS(FILTER(...)) with CALCULATE(COUNTROWS(...), filters) for 5-10x improvement"
            },
            "filter_all": {
                "priority": 1,
                "message": "🔴 HIGH IMPACT: FILTER(ALL(...)) forces Formula Engine evaluation - use CALCULATE with filter arguments"
            },
            "nested_calculate": {
                "priority": 2,
                "message": "🟡 MEDIUM IMPACT: Consolidate nested CALCULATE functions into single CALCULATE or use variables"
            },
            "divide_zero_check": {
                "priority": 2,
                "message": "🟡 MEDIUM IMPACT: Replace manual IF zero-checks with DIVIDE function for 2-3x improvement"
            },
            "related_in_iterator": {
                "priority": 2,
                "message": "🟡 MEDIUM IMPACT: RELATED in iterators causes row-by-row lookups - consider TREATAS or table expansion"
            },
            "measure_in_filter": {
                "priority": 2,
                "message": "🟡 MEDIUM IMPACT: Measures in FILTER predicates cause row-by-row context transitions - pre-calculate or use columns"
            },
            "unnecessary_iterators": {
                "priority": 3,
                "message": "🔵 LOW IMPACT: Replace unnecessary iterator functions (SUMX(Table, Table[Column])) with direct aggregation (SUM)"
            },
            "values_in_calculate": {
                "priority": 3,
                "message": "🔵 LOW IMPACT: VALUES in CALCULATE filter arguments can be replaced with direct column references"
            },
            "multiple_context_transitions": {
                "priority": 3,
                "message": "🔵 LOW IMPACT: Multiple measure references create implicit CALCULATEs - cache results in variables"
            },
        }

        # Build prioritized recommendation list
        matched_patterns = []
        for pattern_id in pattern_matches.keys():
            if pattern_id in pattern_recommendations:
                rec = pattern_recommendations[pattern_id]
                matched_patterns.append((rec["priority"], rec["message"]))

        # Sort by priority and add to recommendations
        matched_patterns.sort(key=lambda x: x[0])
        recommendations.extend([msg for _, msg in matched_patterns])

        # Add general best practice if no specific issues found
        if not recommendations:
            recommendations.append(
                "✅ No major anti-patterns detected. Continue following DAX best practices."
            )

        return recommendations

    def _load_article_patterns(self) -> Dict[str, Dict]:
        """Load article patterns from configuration"""
        from .article_patterns import ARTICLE_PATTERNS
        return ARTICLE_PATTERNS
