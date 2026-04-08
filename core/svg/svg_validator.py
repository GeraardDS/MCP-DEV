"""
SVG Validator - Validates SVG for Power BI compatibility

This module validates SVG code to ensure it will render correctly
in Power BI visuals (Table, Matrix, Card, Slicer, Image).
"""
import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class SVGValidator:
    """Validates SVG code for Power BI compatibility"""

    # Character limits for Power BI measures
    MAX_SVG_LENGTH = 32000
    WARNING_THRESHOLD = 25000

    # Required SVG namespace
    SVG_NAMESPACE = "http://www.w3.org/2000/svg"

    # Patterns for validation
    HEX_COLOR_PATTERN = re.compile(r'(?<![%])#[0-9A-Fa-f]{3,8}')
    NAMESPACE_PATTERNS = [
        "xmlns='http://www.w3.org/2000/svg'",
        'xmlns="http://www.w3.org/2000/svg"'
    ]

    # Potentially problematic SVG elements/attributes for Power BI
    UNSUPPORTED_ELEMENTS = ['script', 'foreignObject', 'iframe', 'embed', 'object']
    UNSUPPORTED_ATTRIBUTES = ['onclick', 'onload', 'onerror', 'onmouseover']

    @classmethod
    def validate(cls, svg_code: str) -> Dict[str, Any]:
        """
        Validate SVG code for Power BI compatibility.

        Args:
            svg_code: The SVG markup to validate

        Returns:
            Dict with 'valid', 'issues', 'warnings', 'character_count' keys
        """
        issues: List[str] = []
        warnings: List[str] = []

        # Check for required namespace
        has_namespace = any(ns in svg_code for ns in cls.NAMESPACE_PATTERNS)
        if not has_namespace and '<svg' in svg_code:
            issues.append("Missing SVG namespace declaration (xmlns='http://www.w3.org/2000/svg')")

        # Check for Firefox-incompatible hex colors (# instead of %23)
        hex_matches = cls.HEX_COLOR_PATTERN.findall(svg_code)
        if hex_matches:
            warnings.append(
                f"Found {len(hex_matches)} hex color(s) using '#'. "
                "Use '%23' instead for Firefox compatibility (e.g., %23FF0000 instead of #FF0000)"
            )

        # Check character limit
        svg_length = len(svg_code)
        if svg_length > cls.MAX_SVG_LENGTH:
            issues.append(
                f"SVG exceeds 32K character limit ({svg_length:,} characters). "
                "Simplify the SVG or split into multiple measures."
            )
        elif svg_length > cls.WARNING_THRESHOLD:
            warnings.append(
                f"SVG length ({svg_length:,} characters) approaching 32K limit. "
                "Consider simplifying if you plan to add more complexity."
            )

        # Check for unsupported elements (match tag followed by whitespace, > or /)
        svg_lower = svg_code.lower()
        for element in cls.UNSUPPORTED_ELEMENTS:
            if re.search(rf'<{element}[\s>/]', svg_lower):
                issues.append(f"Unsupported element <{element}> found. Power BI will not render this.")

        # Check for unsupported event attributes
        for attr in cls.UNSUPPORTED_ATTRIBUTES:
            if attr in svg_code.lower():
                warnings.append(f"Event attribute '{attr}' found. This will be ignored in Power BI.")

        # Check for external references
        if 'xlink:href="http' in svg_code or "xlink:href='http" in svg_code:
            warnings.append("External URL references may not load in Power BI due to security restrictions.")

        # Check for embedded images with external URLs
        if re.search(r'<image[^>]+href=["\']http', svg_code, re.IGNORECASE):
            warnings.append("External image URLs may not load. Consider embedding images as base64 data URIs.")

        # Check basic SVG structure
        if '<svg' not in svg_code.lower():
            issues.append("Missing <svg> element")
        elif '</svg>' not in svg_code.lower():
            issues.append("Missing closing </svg> tag")

        # Check for viewBox (recommended for proper scaling)
        if '<svg' in svg_code.lower() and 'viewbox' not in svg_code.lower():
            warnings.append("Missing viewBox attribute. Adding viewBox ensures proper scaling in different visual sizes.")

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'character_count': svg_length
        }

    @classmethod
    def validate_dax_measure(cls, dax_code: str) -> Dict[str, Any]:
        """
        Validate complete DAX measure containing SVG.

        Args:
            dax_code: The complete DAX measure expression

        Returns:
            Dict with validation results
        """
        issues: List[str] = []
        warnings: List[str] = []

        # Check for data URI prefix
        if 'data:image/svg+xml;utf8,' not in dax_code:
            warnings.append(
                "Missing 'data:image/svg+xml;utf8,' prefix. "
                "The measure RETURN should include this prefix for Power BI to render the SVG."
            )

        # Extract SVG content from DAX
        svg_match = re.search(r'<svg[^>]*>.*?</svg>', dax_code, re.IGNORECASE | re.DOTALL)
        if svg_match:
            svg_content = svg_match.group()
            svg_validation = cls.validate(svg_content)
            issues.extend(svg_validation['issues'])
            warnings.extend(svg_validation['warnings'])
        else:
            # SVG might be built dynamically, which is fine
            warnings.append(
                "Could not extract static SVG content for validation. "
                "If SVG is built dynamically, ensure it includes proper namespace and encoding."
            )

        # Check for proper quote handling in DAX
        if '""' in dax_code and "'" not in dax_code:
            warnings.append(
                "Consider using single quotes inside SVG for cleaner DAX syntax. "
                "Example: <circle cx='50' cy='50'/> instead of escaped double quotes."
            )

        # Check total measure length
        measure_length = len(dax_code)
        if measure_length > cls.MAX_SVG_LENGTH:
            issues.append(
                f"Complete DAX measure exceeds 32K character limit ({measure_length:,} characters)"
            )
        elif measure_length > cls.WARNING_THRESHOLD:
            warnings.append(
                f"DAX measure length ({measure_length:,} characters) approaching 32K limit"
            )

        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'character_count': measure_length
        }

    @classmethod
    def fix_hex_colors(cls, svg_code: str) -> str:
        """
        Convert hex colors from # to %23 for Firefox compatibility.

        Args:
            svg_code: SVG code with potential # hex colors

        Returns:
            SVG code with %23 encoded hex colors
        """
        def replace_hex(match):
            # Replace # with %23
            color = match.group()
            return '%23' + color[1:]

        return cls.HEX_COLOR_PATTERN.sub(replace_hex, svg_code)

    @classmethod
    def wrap_for_dax(cls, svg_code: str, ensure_encoding: bool = True) -> str:
        """
        Wrap SVG code for use in DAX measure.

        Args:
            svg_code: The SVG markup
            ensure_encoding: Whether to convert hex colors to %23

        Returns:
            SVG code ready for DAX embedding
        """
        result = svg_code

        # Fix hex colors if needed
        if ensure_encoding:
            result = cls.fix_hex_colors(result)

        # Escape double quotes if present
        if '"' in result:
            # For DAX, we prefer single quotes in SVG, but escape if needed
            result = result.replace('"', '""')

        return result

    @classmethod
    def get_usage_instructions(cls) -> List[str]:
        """Get standard usage instructions for SVG measures"""
        return [
            "1. Copy the DAX code to Power BI Desktop",
            "2. Create a new measure with this code (Modeling > New Measure)",
            "3. Select the measure in the Fields pane",
            "4. In Measure tools, set Data Category to 'Image URL'",
            "5. Add the measure to a Table, Matrix, or Card visual",
            "6. Adjust column width/row height to display the SVG properly"
        ]
