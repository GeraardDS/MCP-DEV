"""
TMDL Domain Models

Typed dataclasses representing all TMDL object types.
These provide the canonical schema for parsed TMDL data.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TmdlAnnotation:
    """An annotation (key-value metadata) on any TMDL object."""
    name: str
    value: str


@dataclass
class TmdlColumn:
    """A column in a table."""
    name: str
    is_calculated: bool = False
    data_type: Optional[str] = None
    source_column: Optional[str] = None
    expression: Optional[str] = None
    description: Optional[str] = None
    display_folder: Optional[str] = None
    format_string: Optional[str] = None
    data_category: Optional[str] = None
    summarize_by: Optional[str] = None
    sort_by_column: Optional[str] = None
    is_key: bool = False
    is_hidden: bool = False
    lineage_tag: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlMeasure:
    """A measure with a DAX expression."""
    name: str
    expression: Optional[str] = None
    format_string: Optional[str] = None
    format_string_definition: Optional[str] = None
    display_folder: Optional[str] = None
    description: Optional[str] = None
    is_hidden: bool = False
    data_category: Optional[str] = None
    lineage_tag: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlHierarchyLevel:
    """A level within a hierarchy."""
    name: str
    column: Optional[str] = None
    ordinal: Optional[int] = None
    lineage_tag: Optional[str] = None


@dataclass
class TmdlHierarchy:
    """A hierarchy on a table."""
    name: str
    levels: List[TmdlHierarchyLevel] = field(default_factory=list)
    is_hidden: bool = False
    lineage_tag: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlPartition:
    """A partition (data source) for a table."""
    name: str
    type: Optional[str] = None  # 'm', 'entity', 'calculated', etc.
    mode: Optional[str] = None  # 'import', 'directQuery', 'dual'
    source: Optional[str] = None  # M expression or DAX expression
    query_group: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlCalculationItem:
    """A calculation item in a calculation group."""
    name: str
    expression: Optional[str] = None
    ordinal: Optional[int] = None
    format_string_definition: Optional[str] = None
    description: Optional[str] = None
    lineage_tag: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlTable:
    """A table in the model."""
    name: str
    columns: List[TmdlColumn] = field(default_factory=list)
    measures: List[TmdlMeasure] = field(default_factory=list)
    hierarchies: List[TmdlHierarchy] = field(default_factory=list)
    partitions: List[TmdlPartition] = field(default_factory=list)
    calculation_items: List[TmdlCalculationItem] = field(default_factory=list)
    is_calculation_group: bool = False
    is_hidden: bool = False
    description: Optional[str] = None
    lineage_tag: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    _source_file: Optional[str] = None


@dataclass
class TmdlRelationship:
    """A relationship between two tables."""
    id: str
    from_column: Optional[str] = None
    from_cardinality: Optional[str] = None
    to_column: Optional[str] = None
    to_cardinality: Optional[str] = None
    is_active: bool = True
    cross_filtering_behavior: Optional[str] = None
    security_filtering_behavior: Optional[str] = None
    rely_on_referential_integrity: bool = False
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)

    @property
    def from_table(self) -> str:
        """Extract table name from from_column reference."""
        return _extract_table_from_ref(self.from_column)

    @property
    def from_column_name(self) -> str:
        """Extract column name from from_column reference."""
        return _extract_column_from_ref(self.from_column)

    @property
    def to_table(self) -> str:
        """Extract table name from to_column reference."""
        return _extract_table_from_ref(self.to_column)

    @property
    def to_column_name(self) -> str:
        """Extract column name from to_column reference."""
        return _extract_column_from_ref(self.to_column)


@dataclass
class TmdlExpression:
    """A shared M expression or parameter."""
    name: str
    expression: Optional[str] = None
    kind: str = "m"
    lineage_tag: Optional[str] = None
    query_group: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlDatasource:
    """A data source definition."""
    name: str
    type: Optional[str] = None  # 'structured', 'provider', etc.
    connection_string: Optional[str] = None
    provider: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlTablePermission:
    """A table permission within a role (RLS filter)."""
    table: str
    filter_expression: Optional[str] = None


@dataclass
class TmdlRole:
    """A security role with RLS definitions."""
    name: str
    model_permission: Optional[str] = None  # 'read', 'administrator', etc.
    table_permissions: List[TmdlTablePermission] = field(default_factory=list)
    description: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    _source_file: Optional[str] = None


@dataclass
class TmdlPerspectiveItem:
    """An item (table/column/measure) visible in a perspective."""
    object_type: str  # 'table', 'column', 'measure', 'hierarchy'
    table: str
    name: Optional[str] = None  # None for table-level visibility


@dataclass
class TmdlPerspective:
    """A perspective definition."""
    name: str
    items: List[TmdlPerspectiveItem] = field(default_factory=list)
    description: Optional[str] = None
    annotations: List[TmdlAnnotation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    _source_file: Optional[str] = None


@dataclass
class TmdlTranslation:
    """A translation for a model object."""
    object_type: str  # 'table', 'column', 'measure', 'hierarchy'
    table: str
    name: Optional[str] = None
    translated_caption: Optional[str] = None
    translated_description: Optional[str] = None
    translated_display_folder: Optional[str] = None


@dataclass
class TmdlCulture:
    """A culture/language definition with translations."""
    name: str  # e.g., 'en-US', 'nl-BE'
    translations: List[TmdlTranslation] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    _source_file: Optional[str] = None


@dataclass
class TmdlDatabase:
    """Database-level metadata."""
    name: Optional[str] = None
    compatibility_level: Optional[int] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlModelProperties:
    """Model-level properties."""
    name: Optional[str] = None
    culture: Optional[str] = None
    default_power_bi_data_source_version: Optional[str] = None
    discourage_implicit_measures: Optional[bool] = None
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TmdlModel:
    """Complete parsed TMDL model."""
    database: Optional[TmdlDatabase] = None
    model: Optional[TmdlModelProperties] = None
    tables: List[TmdlTable] = field(default_factory=list)
    relationships: List[TmdlRelationship] = field(default_factory=list)
    roles: List[TmdlRole] = field(default_factory=list)
    perspectives: List[TmdlPerspective] = field(default_factory=list)
    expressions: List[TmdlExpression] = field(default_factory=list)
    datasources: List[TmdlDatasource] = field(default_factory=list)
    cultures: List[TmdlCulture] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for backward compatibility with existing consumers."""
        return {
            "database": _database_to_dict(self.database),
            "model": _model_props_to_dict(self.model),
            "tables": [_table_to_dict(t) for t in self.tables],
            "relationships": [_relationship_to_dict(r) for r in self.relationships],
            "roles": [_role_to_dict(r) for r in self.roles],
            "perspectives": [_perspective_to_dict(p) for p in self.perspectives],
            "expressions": [_expression_to_dict(e) for e in self.expressions],
            "datasources": [_datasource_to_dict(d) for d in self.datasources],
            "cultures": [_culture_to_dict(c) for c in self.cultures],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TmdlModel":
        """Reconstruct a TmdlModel from a dictionary (inverse of to_dict).

        Enables any consumer with dict-based model data to get typed access.
        """
        return cls(
            database=_database_from_dict(data.get("database")),
            model=_model_props_from_dict(data.get("model")),
            tables=[_table_from_dict(t) for t in data.get("tables", [])],
            relationships=[_relationship_from_dict(r) for r in data.get("relationships", [])],
            roles=[_role_from_dict(r) for r in data.get("roles", [])],
            perspectives=[_perspective_from_dict(p) for p in data.get("perspectives", [])],
            expressions=[_expression_from_dict(e) for e in data.get("expressions", [])],
            datasources=[_datasource_from_dict(d) for d in data.get("datasources", [])],
            cultures=[_culture_from_dict(c) for c in data.get("cultures", [])],
        )


# --- Helper functions for column reference parsing ---

def _extract_table_from_ref(ref: Optional[str]) -> str:
    """Extract table name from 'TableName'.'ColumnName' reference."""
    if not ref:
        return ""
    import re
    match = re.match(r"'([^']+)'\.(?:'([^']+)'|(\w+))", ref)
    if match:
        return match.group(1)
    return ""


def _extract_column_from_ref(ref: Optional[str]) -> str:
    """Extract column name from 'TableName'.'ColumnName' reference."""
    if not ref:
        return ""
    import re
    match = re.match(r"'([^']+)'\.(?:'([^']+)'|(\w+))", ref)
    if match:
        return match.group(2) or match.group(3) or ""
    return ref


# --- to_dict converters for backward compatibility ---

def _annotation_to_dict(a: TmdlAnnotation) -> Dict[str, str]:
    return {"name": a.name, "value": a.value}


def _column_to_dict(c: TmdlColumn) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": c.name,
        "is_calculated": c.is_calculated,
        "data_type": c.data_type,
        "source_column": c.source_column,
        "expression": c.expression,
        "description": c.description,
        "display_folder": c.display_folder,
        "format_string": c.format_string,
        "data_category": c.data_category,
        "summarize_by": c.summarize_by,
        "sort_by_column": c.sort_by_column,
        "is_key": c.is_key,
        "is_hidden": c.is_hidden,
        "annotations": [_annotation_to_dict(a) for a in c.annotations],
        "properties": c.properties,
    }
    if c.lineage_tag:
        d["lineage_tag"] = c.lineage_tag
    return d


def _measure_to_dict(m: TmdlMeasure) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": m.name,
        "expression": m.expression,
        "format_string": m.format_string,
        "display_folder": m.display_folder,
        "description": m.description,
        "is_hidden": m.is_hidden,
        "data_category": m.data_category,
        "annotations": [_annotation_to_dict(a) for a in m.annotations],
        "properties": m.properties,
    }
    if m.format_string_definition:
        d["format_string_definition"] = m.format_string_definition
    if m.lineage_tag:
        d["lineage_tag"] = m.lineage_tag
    return d


def _hierarchy_to_dict(h: TmdlHierarchy) -> Dict[str, Any]:
    return {
        "name": h.name,
        "levels": [
            {"name": lv.name, "column": lv.column, "ordinal": lv.ordinal}
            for lv in h.levels
        ],
        "is_hidden": h.is_hidden,
        "properties": h.properties,
    }


def _partition_to_dict(p: TmdlPartition) -> Dict[str, Any]:
    return {
        "name": p.name,
        "type": p.type,
        "mode": p.mode,
        "source": p.source,
        "query_group": p.query_group,
        "properties": p.properties,
    }


def _calc_item_to_dict(ci: TmdlCalculationItem) -> Dict[str, Any]:
    return {
        "name": ci.name,
        "expression": ci.expression,
        "ordinal": ci.ordinal,
        "format_string_definition": ci.format_string_definition,
        "description": ci.description,
        "annotations": [_annotation_to_dict(a) for a in ci.annotations],
        "properties": ci.properties,
    }


def _table_to_dict(t: TmdlTable) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "name": t.name,
        "columns": [_column_to_dict(c) for c in t.columns],
        "measures": [_measure_to_dict(m) for m in t.measures],
        "hierarchies": [_hierarchy_to_dict(h) for h in t.hierarchies],
        "partitions": [_partition_to_dict(p) for p in t.partitions],
        "calculation_items": [_calc_item_to_dict(ci) for ci in t.calculation_items],
        "is_calculation_group": t.is_calculation_group,
        "is_hidden": t.is_hidden,
        "description": t.description,
        "annotations": [_annotation_to_dict(a) for a in t.annotations],
        "properties": t.properties,
    }
    if t.lineage_tag:
        d["lineage_tag"] = t.lineage_tag
    if t._source_file:
        d["_source_file"] = t._source_file
    return d


def _relationship_to_dict(r: TmdlRelationship) -> Dict[str, Any]:
    return {
        "id": r.id,
        "from_column": r.from_column,
        "from_cardinality": r.from_cardinality,
        "to_column": r.to_column,
        "to_cardinality": r.to_cardinality,
        "from_table": r.from_table,
        "from_column_name": r.from_column_name,
        "to_table": r.to_table,
        "to_column_name": r.to_column_name,
        "is_active": r.is_active,
        "cross_filtering_behavior": r.cross_filtering_behavior,
        "security_filtering_behavior": r.security_filtering_behavior,
        "rely_on_referential_integrity": r.rely_on_referential_integrity,
        "annotations": [_annotation_to_dict(a) for a in r.annotations],
        "properties": r.properties,
    }


def _expression_to_dict(e: TmdlExpression) -> Dict[str, Any]:
    return {
        "name": e.name,
        "expression": e.expression,
        "kind": e.kind,
    }


def _datasource_to_dict(d: TmdlDatasource) -> Dict[str, Any]:
    return {
        "name": d.name,
        "type": d.type,
        "connection_string": d.connection_string,
        "provider": d.provider,
        "properties": d.properties,
    }


def _role_to_dict(r: TmdlRole) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "name": r.name,
        "model_permission": r.model_permission,
        "table_permissions": [
            {"table": tp.table, "filter_expression": tp.filter_expression}
            for tp in r.table_permissions
        ],
        "description": r.description,
        "properties": r.properties,
    }
    if r._source_file:
        result["_source_file"] = r._source_file
    return result


def _perspective_to_dict(p: TmdlPerspective) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "name": p.name,
        "items": [
            {"object_type": i.object_type, "table": i.table, "name": i.name}
            for i in p.items
        ],
        "description": p.description,
        "properties": p.properties,
    }
    if p._source_file:
        result["_source_file"] = p._source_file
    return result


def _culture_to_dict(c: TmdlCulture) -> Dict[str, Any]:
    return {
        "name": c.name,
        "translations": [
            {
                "object_type": t.object_type,
                "table": t.table,
                "name": t.name,
                "translated_caption": t.translated_caption,
                "translated_description": t.translated_description,
                "translated_display_folder": t.translated_display_folder,
            }
            for t in c.translations
        ],
        "properties": c.properties,
    }


def _database_to_dict(db: Optional[TmdlDatabase]) -> Optional[Dict[str, Any]]:
    if not db:
        return None
    return {
        "name": db.name,
        "compatibility_level": db.compatibility_level,
        "properties": db.properties,
    }


def _model_props_to_dict(m: Optional[TmdlModelProperties]) -> Optional[Dict[str, Any]]:
    if not m:
        return None
    return {
        "name": m.name,
        "culture": m.culture,
        "default_power_bi_data_source_version": m.default_power_bi_data_source_version,
        "discourage_implicit_measures": m.discourage_implicit_measures,
        "properties": m.properties,
    }


# --- from_dict converters for reconstructing typed models from dicts ---

def _annotation_from_dict(d: Dict[str, str]) -> TmdlAnnotation:
    return TmdlAnnotation(name=d.get("name", ""), value=d.get("value", ""))


def _column_from_dict(d: Dict[str, Any]) -> TmdlColumn:
    return TmdlColumn(
        name=d.get("name", ""),
        is_calculated=d.get("is_calculated", False),
        data_type=d.get("data_type"),
        source_column=d.get("source_column"),
        expression=d.get("expression"),
        description=d.get("description"),
        display_folder=d.get("display_folder"),
        format_string=d.get("format_string"),
        data_category=d.get("data_category"),
        summarize_by=d.get("summarize_by"),
        sort_by_column=d.get("sort_by_column"),
        is_key=d.get("is_key", False),
        is_hidden=d.get("is_hidden", False),
        lineage_tag=d.get("lineage_tag"),
        annotations=[_annotation_from_dict(a) for a in d.get("annotations", [])],
        properties=d.get("properties", {}),
    )


def _measure_from_dict(d: Dict[str, Any]) -> TmdlMeasure:
    return TmdlMeasure(
        name=d.get("name", ""),
        expression=d.get("expression"),
        format_string=d.get("format_string"),
        format_string_definition=d.get("format_string_definition"),
        display_folder=d.get("display_folder"),
        description=d.get("description"),
        is_hidden=d.get("is_hidden", False),
        data_category=d.get("data_category"),
        lineage_tag=d.get("lineage_tag"),
        annotations=[_annotation_from_dict(a) for a in d.get("annotations", [])],
        properties=d.get("properties", {}),
    )


def _hierarchy_from_dict(d: Dict[str, Any]) -> TmdlHierarchy:
    return TmdlHierarchy(
        name=d.get("name", ""),
        levels=[
            TmdlHierarchyLevel(
                name=lv.get("name", ""),
                column=lv.get("column", ""),
                ordinal=lv.get("ordinal"),
            )
            for lv in d.get("levels", [])
        ],
        is_hidden=d.get("is_hidden", False),
        properties=d.get("properties", {}),
    )


def _partition_from_dict(d: Dict[str, Any]) -> TmdlPartition:
    return TmdlPartition(
        name=d.get("name", ""),
        type=d.get("type"),
        mode=d.get("mode"),
        source=d.get("source"),
        query_group=d.get("query_group"),
        properties=d.get("properties", {}),
    )


def _calc_item_from_dict(d: Dict[str, Any]) -> TmdlCalculationItem:
    return TmdlCalculationItem(
        name=d.get("name", ""),
        expression=d.get("expression"),
        ordinal=d.get("ordinal"),
        format_string_definition=d.get("format_string_definition"),
        description=d.get("description"),
        annotations=[_annotation_from_dict(a) for a in d.get("annotations", [])],
        properties=d.get("properties", {}),
    )


def _table_from_dict(d: Dict[str, Any]) -> TmdlTable:
    return TmdlTable(
        name=d.get("name", ""),
        columns=[_column_from_dict(c) for c in d.get("columns", [])],
        measures=[_measure_from_dict(m) for m in d.get("measures", [])],
        hierarchies=[_hierarchy_from_dict(h) for h in d.get("hierarchies", [])],
        partitions=[_partition_from_dict(p) for p in d.get("partitions", [])],
        calculation_items=[_calc_item_from_dict(ci) for ci in d.get("calculation_items", [])],
        is_calculation_group=d.get("is_calculation_group", False),
        is_hidden=d.get("is_hidden", False),
        description=d.get("description"),
        lineage_tag=d.get("lineage_tag"),
        annotations=[_annotation_from_dict(a) for a in d.get("annotations", [])],
        properties=d.get("properties", {}),
        _source_file=d.get("_source_file"),
    )


def _relationship_from_dict(d: Dict[str, Any]) -> TmdlRelationship:
    # Reconstruct from_column/to_column from the table+column name fields
    # from_column format: 'TableName'.'ColumnName'
    from_col = d.get("from_column")
    if not from_col:
        ft = d.get("from_table", "")
        fc = d.get("from_column_name", "")
        from_col = f"'{ft}'.'{fc}'" if ft and fc else None

    to_col = d.get("to_column")
    if not to_col:
        tt = d.get("to_table", "")
        tc = d.get("to_column_name", "")
        to_col = f"'{tt}'.'{tc}'" if tt and tc else None

    return TmdlRelationship(
        id=d.get("id", ""),
        from_column=from_col,
        from_cardinality=d.get("from_cardinality"),
        to_column=to_col,
        to_cardinality=d.get("to_cardinality"),
        is_active=d.get("is_active", True),
        cross_filtering_behavior=d.get("cross_filtering_behavior"),
        security_filtering_behavior=d.get("security_filtering_behavior"),
        rely_on_referential_integrity=d.get("rely_on_referential_integrity", False),
        annotations=[_annotation_from_dict(a) for a in d.get("annotations", [])],
        properties=d.get("properties", {}),
    )


def _expression_from_dict(d: Dict[str, Any]) -> TmdlExpression:
    return TmdlExpression(
        name=d.get("name", ""),
        expression=d.get("expression"),
        kind=d.get("kind"),
    )


def _datasource_from_dict(d: Dict[str, Any]) -> TmdlDatasource:
    return TmdlDatasource(
        name=d.get("name", ""),
        type=d.get("type"),
        connection_string=d.get("connection_string"),
        provider=d.get("provider"),
        properties=d.get("properties", {}),
    )


def _role_from_dict(d: Dict[str, Any]) -> TmdlRole:
    return TmdlRole(
        name=d.get("name", ""),
        model_permission=d.get("model_permission"),
        table_permissions=[
            TmdlTablePermission(
                table=tp.get("table", ""),
                filter_expression=tp.get("filter_expression"),
            )
            for tp in d.get("table_permissions", [])
        ],
        description=d.get("description"),
        properties=d.get("properties", {}),
        _source_file=d.get("_source_file"),
    )


def _perspective_from_dict(d: Dict[str, Any]) -> TmdlPerspective:
    return TmdlPerspective(
        name=d.get("name", ""),
        items=[
            TmdlPerspectiveItem(
                object_type=i.get("object_type", ""),
                table=i.get("table", ""),
                name=i.get("name", ""),
            )
            for i in d.get("items", [])
        ],
        description=d.get("description"),
        properties=d.get("properties", {}),
        _source_file=d.get("_source_file"),
    )


def _culture_from_dict(d: Dict[str, Any]) -> TmdlCulture:
    return TmdlCulture(
        name=d.get("name", ""),
        translations=[
            TmdlTranslation(
                object_type=t.get("object_type", ""),
                table=t.get("table", ""),
                name=t.get("name", ""),
                translated_caption=t.get("translated_caption"),
                translated_description=t.get("translated_description"),
                translated_display_folder=t.get("translated_display_folder"),
            )
            for t in d.get("translations", [])
        ],
        properties=d.get("properties", {}),
    )


def _database_from_dict(d: Optional[Dict[str, Any]]) -> Optional[TmdlDatabase]:
    if not d:
        return None
    return TmdlDatabase(
        name=d.get("name"),
        compatibility_level=d.get("compatibility_level"),
        properties=d.get("properties", {}),
    )


def _model_props_from_dict(d: Optional[Dict[str, Any]]) -> Optional[TmdlModelProperties]:
    if not d:
        return None
    return TmdlModelProperties(
        name=d.get("name"),
        culture=d.get("culture"),
        default_power_bi_data_source_version=d.get("default_power_bi_data_source_version"),
        discourage_implicit_measures=d.get("discourage_implicit_measures"),
        properties=d.get("properties", {}),
    )
