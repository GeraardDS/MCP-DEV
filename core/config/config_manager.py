"""
Configuration management for PBIXRay MCP Server
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from core.utilities.json_utils import load_json

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    Manages server configuration with support for default and local overrides.
    """
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Directory containing configuration files
        """
        if config_dir is None:
            # Default to config directory relative to this file
            # This file is in core/config/, so go up two levels to root, then into config/
            script_dir = os.path.dirname(os.path.abspath(__file__))
            core_dir = os.path.dirname(script_dir)  # core/
            root_dir = os.path.dirname(core_dir)    # project root
            config_dir = os.path.join(root_dir, "config")
        
        self.config_dir = config_dir
        self.config = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from default and local files."""
        try:
            # Load default configuration
            default_config_path = os.path.join(self.config_dir, "default_config.json")
            if os.path.exists(default_config_path):
                self.config = load_json(default_config_path)
                logger.info("Loaded default configuration")
            else:
                logger.warning(f"Default config not found at {default_config_path}")
                self.config = self._get_fallback_config()

            # Load local overrides if they exist
            local_config_path = os.path.join(self.config_dir, "local_config.json")
            if os.path.exists(local_config_path):
                local_config = load_json(local_config_path)
                self._merge_config(self.config, local_config)
                logger.info("Applied local configuration overrides")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            self.config = self._get_fallback_config()
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            self.config = self._get_fallback_config()
    
    def _merge_config(self, base: Dict[str, Any], override: Dict[str, Any]):
        """Recursively merge override config into base config."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value
    
    def _get_fallback_config(self) -> Dict[str, Any]:
        """Return minimal fallback configuration."""
        return {
            "server": {
                "name": "pbixray-v2.3",
                "log_level": "INFO",
                "timeout_seconds": 60
            },
            "performance": {
                "cache_ttl_seconds": 300,
                "max_query_timeout": 60,
                "default_top_n": 1000,
                "enable_trace_logging": False,
                "trace_mode": "full",
                "trace_init_retries": 2,
                "trace_init_backoff_ms": 150
            },
            "detection": {
                "cache_instances_seconds": 60,
                "detection_timeout": 10,
                "max_instances": 10
            },
            "query": {
                "max_rows_preview": 1000,
                "max_dax_query_length": 50000,
                "enable_query_validation": True
            },
            "logging": {
                "structured_logging": False,
                "log_queries": False,
                "log_performance": True
            },
            "features": {
                "enable_bpa": True,
                "enable_performance_analysis": True,
                "enable_bulk_operations": True,
                "enable_calculation_groups": True
            }
        }
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key_path: Dot-separated path to config value (e.g., 'server.timeout_seconds')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get entire configuration section.
        
        Args:
            section: Section name (e.g., 'server', 'performance')
            
        Returns:
            Configuration section dictionary
        """
        return self.config.get(section, {})
    
    def is_feature_enabled(self, feature: str) -> bool:
        """
        Check if a feature is enabled.
        
        Args:
            feature: Feature name
            
        Returns:
            True if feature is enabled
        """
        return self.get(f'features.{feature}', False)
    
    def reload(self):
        """Reload configuration from files."""
        self._load_config()
        logger.info("Configuration reloaded")
    
    def get_all(self) -> Dict[str, Any]:
        """Get complete configuration dictionary."""
        return self.config.copy()


# Global configuration instance
config = ConfigManager()