"""
PBIP Report Authoring Package

Provides tools for creating, cloning, and prototyping Power BI reports
in PBIP (Power BI Project) format.

Modules:
    id_generator        - Generate page/visual/bookmark IDs
    data_binding_builder - Build queryState projections from (table, field) tuples
    visual_templates    - Predefined JSON skeletons for each visual type
    visual_builder      - Fluent API for constructing visual.json dicts
    page_builder        - Create page folder structure with visuals
    report_builder      - Orchestrate full page generation from specs
    clone_engine        - Deep-clone pages/reports with ID regeneration
    html/               - Bidirectional PBIP <-> HTML prototyping
"""

from core.pbip.authoring.id_generator import generate_visual_id, generate_guid
from core.pbip.authoring.clone_engine import CloneEngine
from core.pbip.authoring.visual_builder import VisualBuilder
from core.pbip.authoring.page_builder import PageBuilder
from core.pbip.authoring.report_builder import ReportBuilder

__all__ = [
    "generate_visual_id",
    "generate_guid",
    "CloneEngine",
    "VisualBuilder",
    "PageBuilder",
    "ReportBuilder",
]
