"""Culture CRUD Manager — manage cultures (translations) via TOM."""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class CultureCrudManager:
    """CRUD operations for model cultures and translations."""

    def __init__(self):
        self._connection_state = None

    @property
    def connection_state(self):
        if self._connection_state is None:
            from core.infrastructure.connection_state import connection_state
            self._connection_state = connection_state
        return self._connection_state

    def list_cultures(self) -> Dict[str, Any]:
        """List all cultures in the model."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        cultures = []
        for culture in model.Cultures:
            cultures.append({"name": culture.Name, "translation_count": culture.ObjectTranslations.Count})
        return {"success": True, "cultures": cultures, "count": len(cultures)}

    def describe_culture(self, culture_name: str) -> Dict[str, Any]:
        """Get detailed info about a culture including translations."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        culture = model.Cultures.Find(culture_name)
        if not culture:
            return {"success": False, "error": f"Culture '{culture_name}' not found"}
        translations = []
        for t in culture.ObjectTranslations:
            translations.append({
                "property": str(t.Property),
                "object_type": type(t.Object).__name__,
                "object_name": t.Object.Name if hasattr(t.Object, 'Name') else str(t.Object),
                "value": t.Value,
            })
        return {"success": True, "culture": {"name": culture.Name, "translations": translations, "translation_count": len(translations)}}

    def create_culture(self, culture_name: str) -> Dict[str, Any]:
        """Create a new culture (e.g., 'fr-FR', 'de-DE')."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            culture = TOM.Culture()
            culture.Name = culture_name
            model.Cultures.Add(culture)
            model.SaveChanges()
            return {"success": True, "message": f"Culture '{culture_name}' created"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_culture(self, culture_name: str) -> Dict[str, Any]:
        """Delete a culture."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        culture = model.Cultures.Find(culture_name)
        if not culture:
            return {"success": False, "error": f"Culture '{culture_name}' not found"}
        try:
            model.Cultures.Remove(culture)
            model.SaveChanges()
            return {"success": True, "message": f"Culture '{culture_name}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_translation(self, culture_name: str, object_type: str, object_name: str,
                        property_name: str, value: str, table_name: str = None) -> Dict[str, Any]:
        """Set a translation for an object property."""
        model = self.connection_state.model
        if not model:
            return {"success": False, "error": "Not connected"}
        culture = model.Cultures.Find(culture_name)
        if not culture:
            return {"success": False, "error": f"Culture '{culture_name}' not found"}
        try:
            import Microsoft.AnalysisServices.Tabular as TOM
            obj = None
            if object_type == "table":
                obj = model.Tables.Find(object_name)
            elif object_type == "column" and table_name:
                table = model.Tables.Find(table_name)
                if table:
                    obj = table.Columns.Find(object_name)
            elif object_type == "measure" and table_name:
                table = model.Tables.Find(table_name)
                if table:
                    obj = table.Measures.Find(object_name)
            elif object_type == "hierarchy" and table_name:
                table = model.Tables.Find(table_name)
                if table:
                    obj = table.Hierarchies.Find(object_name)
            if not obj:
                return {"success": False, "error": f"{object_type} '{object_name}' not found"}
            prop_map = {
                "caption": TOM.TranslatedProperty.Caption,
                "description": TOM.TranslatedProperty.Description,
                "display_folder": TOM.TranslatedProperty.DisplayFolder,
            }
            prop = prop_map.get(property_name)
            if not prop:
                return {"success": False, "error": f"Invalid property: {property_name}. Use: caption, description, display_folder"}
            culture.ObjectTranslations.SetTranslation(obj, prop, value)
            model.SaveChanges()
            return {"success": True, "message": f"Translation set for {object_type} '{object_name}'.{property_name} = '{value}'"}
        except Exception as e:
            return {"success": False, "error": str(e)}
