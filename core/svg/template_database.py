"""
SVG Template Database - Load and manage SVG templates

This module provides template loading, caching, and retrieval for SVG visuals.
Templates are stored as JSON files organized by category.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)


@dataclass
class SVGParameter:
    """Template parameter definition"""
    name: str
    type: str  # 'measure', 'column', 'scalar', 'color', 'string'
    required: bool
    default: Optional[Any] = None
    description: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SVGParameter':
        """Create parameter from dictionary"""
        return cls(
            name=data.get('name', ''),
            type=data.get('type', 'string'),
            required=data.get('required', False),
            default=data.get('default'),
            description=data.get('description', '')
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        result = {
            'name': self.name,
            'type': self.type,
            'required': self.required,
            'description': self.description
        }
        if self.default is not None:
            result['default'] = self.default
        return result


@dataclass
class SVGTemplate:
    """Complete SVG template definition"""
    template_id: str
    name: str
    category: str
    subcategory: str
    description: str
    complexity: str  # 'basic', 'intermediate', 'advanced', 'complex'
    preview_svg: str
    dax_template: str
    parameters: List[SVGParameter] = field(default_factory=list)
    supported_visuals: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source: str = ""
    version: str = "1.0.0"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SVGTemplate':
        """Create template from dictionary"""
        parameters = [
            SVGParameter.from_dict(p)
            for p in data.get('parameters', [])
        ]
        return cls(
            template_id=data.get('template_id', ''),
            name=data.get('name', ''),
            category=data.get('category', ''),
            subcategory=data.get('subcategory', ''),
            description=data.get('description', ''),
            complexity=data.get('complexity', 'basic'),
            preview_svg=data.get('preview_svg', ''),
            dax_template=data.get('dax_template', ''),
            parameters=parameters,
            supported_visuals=data.get('supported_visuals', ['table', 'matrix']),
            tags=data.get('tags', []),
            source=data.get('source', ''),
            version=data.get('version', '1.0.0')
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'template_id': self.template_id,
            'name': self.name,
            'category': self.category,
            'subcategory': self.subcategory,
            'description': self.description,
            'complexity': self.complexity,
            'preview_svg': self.preview_svg,
            'dax_template': self.dax_template,
            'parameters': [p.to_dict() for p in self.parameters],
            'supported_visuals': self.supported_visuals,
            'tags': self.tags,
            'source': self.source,
            'version': self.version
        }

    def to_summary(self) -> Dict[str, Any]:
        """Convert to summary dictionary (without full template content)"""
        return {
            'template_id': self.template_id,
            'name': self.name,
            'category': self.category,
            'subcategory': self.subcategory,
            'description': self.description,
            'complexity': self.complexity,
            'supported_visuals': self.supported_visuals,
            'tags': self.tags
        }


class TemplateDatabase:
    """Manages SVG template loading and retrieval"""

    # Category display names and descriptions
    CATEGORIES = {
        'kpi': {
            'name': 'KPI Indicators',
            'description': 'Traffic lights, status dots, arrows, stars, checkmarks'
        },
        'sparklines': {
            'name': 'Sparklines',
            'description': 'Line, area, bar, and win/loss mini charts'
        },
        'gauges': {
            'name': 'Gauges & Progress',
            'description': 'Progress bars, radial gauges, donuts, battery indicators'
        },
        'databars': {
            'name': 'Data Bars',
            'description': 'Simple bars, variance bars, bullet charts, lollipops'
        },
        'advanced': {
            'name': 'Advanced',
            'description': 'Waffle charts, timelines, composite KPIs'
        }
    }

    def __init__(self, templates_dir: Optional[Path] = None):
        """
        Initialize template database.

        Args:
            templates_dir: Path to templates directory. If None, uses default location.
        """
        if templates_dir is None:
            templates_dir = Path(__file__).parent / "templates"
        self.templates_dir = templates_dir
        self._templates: Dict[str, SVGTemplate] = {}
        self._categories: Dict[str, List[str]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Ensure templates are loaded (lazy loading)"""
        if not self._loaded:
            self._load_all_templates()
            self._loaded = True

    def _load_all_templates(self) -> None:
        """Load templates from all category directories"""
        self._templates = {}
        self._categories = {}

        if not self.templates_dir.exists():
            logger.warning(f"Templates directory not found: {self.templates_dir}")
            return

        # Load from category subdirectories
        for category in self.CATEGORIES.keys():
            category_dir = self.templates_dir / category
            if category_dir.exists() and category_dir.is_dir():
                self._load_category(category, category_dir)

        logger.info(f"Loaded {len(self._templates)} SVG templates from {len(self._categories)} categories")

    def _load_category(self, category: str, category_dir: Path) -> None:
        """Load all templates from a category directory"""
        template_ids = []

        for json_file in category_dir.glob("*.json"):
            try:
                templates = self._load_template_file(json_file)
                for template in templates:
                    self._templates[template.template_id] = template
                    template_ids.append(template.template_id)
                    logger.debug(f"Loaded template: {template.template_id}")
            except Exception as e:
                logger.error(f"Error loading template file {json_file}: {e}")

        if template_ids:
            self._categories[category] = template_ids

    def _load_template_file(self, file_path: Path) -> List[SVGTemplate]:
        """Load templates from a single JSON file"""
        data = load_json(file_path)

        # Support both single template and array of templates
        if 'templates' in data:
            return [SVGTemplate.from_dict(t) for t in data['templates']]
        elif 'template_id' in data:
            return [SVGTemplate.from_dict(data)]
        else:
            return []

    def list_templates(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List templates, optionally filtered by category.

        Args:
            category: Filter by category (kpi, sparklines, gauges, databars, advanced)

        Returns:
            List of template summaries
        """
        self._ensure_loaded()

        if category:
            # Filter by category
            category_lower = category.lower()
            if category_lower not in self._categories:
                return []
            template_ids = self._categories.get(category_lower, [])
            return [
                self._templates[tid].to_summary()
                for tid in template_ids
                if tid in self._templates
            ]
        else:
            # Return all templates
            return [t.to_summary() for t in self._templates.values()]

    def get_template(self, template_id: str) -> Optional[SVGTemplate]:
        """
        Get specific template by ID.

        Args:
            template_id: The template identifier

        Returns:
            SVGTemplate or None if not found
        """
        self._ensure_loaded()
        return self._templates.get(template_id)

    def search_templates(self, query: str) -> List[Dict[str, Any]]:
        """
        Search templates by name, description, or tags.

        Args:
            query: Search query string

        Returns:
            List of matching template summaries
        """
        self._ensure_loaded()

        query_lower = query.lower()
        results = []

        for template in self._templates.values():
            # Search in name, description, and tags
            if (query_lower in template.name.lower() or
                query_lower in template.description.lower() or
                any(query_lower in tag.lower() for tag in template.tags)):
                results.append(template.to_summary())

        return results

    def list_categories(self) -> List[Dict[str, Any]]:
        """
        List all available categories with template counts.

        Returns:
            List of category info dictionaries
        """
        self._ensure_loaded()

        categories = []
        for cat_id, cat_info in self.CATEGORIES.items():
            template_count = len(self._categories.get(cat_id, []))
            categories.append({
                'id': cat_id,
                'name': cat_info['name'],
                'description': cat_info['description'],
                'template_count': template_count
            })

        return categories

    def get_templates_by_complexity(self, complexity: str) -> List[Dict[str, Any]]:
        """
        Get templates filtered by complexity level.

        Args:
            complexity: One of 'basic', 'intermediate', 'advanced', 'complex'

        Returns:
            List of matching template summaries
        """
        self._ensure_loaded()

        return [
            t.to_summary()
            for t in self._templates.values()
            if t.complexity == complexity
        ]

    def get_template_count(self) -> int:
        """Get total number of templates"""
        self._ensure_loaded()
        return len(self._templates)

    def reload_templates(self) -> None:
        """Force reload all templates from disk"""
        self._loaded = False
        self._ensure_loaded()
