"""
Skill Registry — auto-discovers and manages trading skills per segment.

Usage:
    registry = SkillRegistry("options_index")
    registry.discover()   # loads all skills from skills/options_index/*.py
    signals = registry.scan_all(df, "NIFTY", {"vix": 18, "pcr": 1.2})
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from mcp_server.agents.skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)

_DISABLED = set(
    s.strip().lower()
    for s in os.environ.get("DISABLED_SKILLS", "").split(",")
    if s.strip()
)


class SkillRegistry:
    """Discovers and manages skills for one segment."""

    def __init__(self, segment: str):
        self.segment = segment
        self.skills: list[BaseSkill] = []

    def discover(self) -> None:
        """Auto-discover skill modules from skills/{segment}/ directory."""
        skill_dir = Path(__file__).parent / self.segment
        if not skill_dir.is_dir():
            logger.warning("Skill directory not found: %s", skill_dir)
            return

        for py_file in sorted(skill_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"mcp_server.agents.skills.{self.segment}.{py_file.stem}"
            try:
                mod = importlib.import_module(module_name)
                for _, cls in inspect.getmembers(mod, inspect.isclass):
                    if issubclass(cls, BaseSkill) and cls is not BaseSkill:
                        instance = cls()
                        if instance.name.lower() in _DISABLED:
                            logger.info("Skill disabled: %s", instance.name)
                            continue
                        self.skills.append(instance)
                        logger.debug(
                            "Skill loaded: %s (%s)", instance.name, py_file.name
                        )
            except Exception as e:
                logger.warning("Skill load failed: %s — %s", py_file.name, e)

        logger.info(
            "SkillRegistry[%s]: %d skills loaded", self.segment, len(self.skills)
        )

    def scan_all(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Run all skills against the given data. Returns non-None signal dicts."""
        results: list[dict[str, Any]] = []
        for skill in self.skills:
            if df is not None and len(df) < skill.min_bars:
                continue
            try:
                signal = skill.scan(df, symbol, context)
                if signal:
                    signal.setdefault("skill_name", skill.name)
                    signal.setdefault("scanner_list", [skill.name])
                    signal.setdefault("timeframe", skill.timeframe)
                    results.append(signal)
            except Exception as e:
                logger.debug("Skill %s failed on %s: %s", skill.name, symbol, e)
        return results

    def list_skills(self) -> list[dict[str, Any]]:
        return [s.metadata for s in self.skills]
