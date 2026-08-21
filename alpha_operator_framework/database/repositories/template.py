"""模板类库与自进化淘汰规则仓储 (Template Library & Evolution Rules Repository).

管理表:
  - template_library (4族骨架模板与衍生子模板)
  - template_prune_rules (负向自进化淘汰规则)
"""

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..base import BaseRepository
from ..models import Template


class TemplateRepository(BaseRepository):
    """模板类库与自进化淘汰规则仓储."""

    def upsert_templates(self, templates: Sequence[Template], *, overwrite: bool = False) -> int:
        """批量 upsert template_library."""
        now = self._timestamp()
        conn = self._get_connection()
        count = 0
        for tpl in templates:
            conflict = "DO UPDATE SET " + ", ".join(
                f"{c}=excluded.{c}" for c in (
                    "title", "family", "template_type", "expression_template", "template_index",
                    "fields_per_alpha", "expression_origin", "field_types_json", "categories_json",
                    "dataset_families_json", "placeholders_json", "group_slots_json", "slot_count",
                    "description", "rationale", "example_expression", "settings_hint_json",
                    "field_candidates_json", "operators_used_json", "source_json",
                    "parent_template_id", "signal_constraints_json", "updated_at"))
            if not overwrite:
                conflict = "DO NOTHING"
            conn.execute(f"""
                INSERT INTO template_library (
                    name, title, family, template_type, expression_template, template_index,
                    fields_per_alpha, expression_origin, field_types_json, categories_json,
                    dataset_families_json, placeholders_json, group_slots_json, slot_count,
                    description, rationale, example_expression, settings_hint_json,
                    field_candidates_json, operators_used_json, source_json,
                    parent_template_id, signal_constraints_json, active,
                    created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) {conflict}
            """, (
                tpl.name, tpl.title, tpl.family, tpl.template_type, tpl.expression_template,
                tpl.template_index, tpl.fields_per_alpha, tpl.expression_origin,
                self._json(tpl.field_types), self._json(tpl.categories), self._json(tpl.dataset_families),
                self._json(tpl.placeholders), self._json(tpl.group_slots), tpl.slot_count,
                tpl.description, tpl.rationale, tpl.example_expression, self._json(tpl.settings_hint),
                self._json(tpl.field_candidates), self._json(tpl.operators_used), self._json(tpl.source),
                tpl.parent_template_id, self._json(tpl.signal_constraints), tpl.active, now, now))
            count += 1
        conn.commit()
        return count

    @staticmethod
    def _row_to_template(row: sqlite3.Row) -> Template:
        return Template(
            id=row["id"], name=row["name"], title=row["title"], family=row["family"],
            template_type=row["template_type"], expression_template=row["expression_template"],
            template_index=row["template_index"], fields_per_alpha=row["fields_per_alpha"],
            expression_origin=row["expression_origin"],
            field_types=json.loads(row["field_types_json"] or "[]"),
            categories=json.loads(row["categories_json"] or "[]"),
            dataset_families=json.loads(row["dataset_families_json"] or "[]"),
            placeholders=json.loads(row["placeholders_json"] or "{}"),
            group_slots=json.loads(row["group_slots_json"] or "[]"),
            slot_count=row["slot_count"], description=row["description"], rationale=row["rationale"],
            example_expression=row["example_expression"],
            settings_hint=json.loads(row["settings_hint_json"] or "{}"),
            field_candidates=json.loads(row["field_candidates_json"] or "{}"),
            operators_used=json.loads(row["operators_used_json"] or "[]"),
            source=json.loads(row["source_json"] or "{}"),
            parent_template_id=row["parent_template_id"],
            signal_constraints=json.loads(row["signal_constraints_json"] or "[]"),
            active=row["active"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def list_templates(self, *, active_only: bool = True,
                       families: Optional[Sequence[str]] = None,
                       categories: Optional[Sequence[str]] = None,
                       template_type: Optional[str] = None,
                       names: Optional[Sequence[str]] = None) -> List[Template]:
        """查询模板库."""
        sql = "SELECT * FROM template_library WHERE 1=1"
        params: List[Any] = []
        if active_only:
            sql += " AND active=1"
        if families:
            sql += " AND family IN ({})".format(",".join("?" * len(families)))
            params.extend(families)
        if template_type:
            sql += " AND template_type=?"
            params.append(template_type)
        if names:
            sql += " AND name IN ({})".format(",".join("?" * len(names)))
            params.extend(names)
        rows = self._get_connection().execute(sql + " ORDER BY family, template_index, name", params).fetchall()
        out = [self._row_to_template(r) for r in rows]
        if categories:
            want = set(categories)
            out = [t for t in out if not t.categories or (want & set(t.categories))]
        return out

    def deactivate_templates(self, *, template_ids: Optional[Sequence[int]] = None,
                             names: Optional[Sequence[str]] = None,
                             family: Optional[str] = None,
                             expression_like: Optional[str] = None) -> int:
        """标记模板 inactive (active=0)."""
        sql = "UPDATE template_library SET active=0 WHERE active=1"
        params: List[Any] = []
        if template_ids:
            sql += " AND id IN ({})".format(",".join("?" * len(template_ids)))
            params.extend(template_ids)
        if names:
            sql += " AND name IN ({})".format(",".join("?" * len(names)))
            params.extend(names)
        if family:
            sql += " AND family=?"
            params.append(family)
        if expression_like:
            sql += " AND expression_template LIKE ?"
            params.append(expression_like)
        conn = self._get_connection()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount

    def get_prune_rules(self, *, active_only: bool = True,
                        family: Optional[str] = None,
                        source: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询模板淘汰规则库."""
        sql = "SELECT * FROM template_prune_rules WHERE 1=1"
        params: List[Any] = []
        if active_only:
            sql += " AND active=1"
        if family:
            sql += " AND (family='' OR family=?)"
            params.append(family)
        if source:
            sql += " AND source=?"
            params.append(source)
        rows = self._get_connection().execute(sql + " ORDER BY id", params).fetchall()
        return [dict(r) for r in rows]

    def upsert_prune_rule(self, pattern: str, *, pattern_type: str = "prefix",
                          family: str = "", reason: str = "",
                          source: str = "static", active: int = 1) -> int:
        """写入一条淘汰规则."""
        now = datetime.now().isoformat()
        conn = self._get_connection()
        conn.execute("""
            INSERT INTO template_prune_rules
                (pattern, pattern_type, family, reason, source, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pattern, pattern_type) DO UPDATE SET
                family=excluded.family, reason=excluded.reason,
                source=excluded.source, active=excluded.active, updated_at=excluded.updated_at
        """, (pattern, pattern_type, family, reason, source, active, now, now))
        conn.commit()
        row = conn.execute(
            "SELECT id FROM template_prune_rules WHERE pattern=? AND pattern_type=?",
            (pattern, pattern_type),
        ).fetchone()
        return int(row["id"]) if row else -1

    def seed_template_library(self, *, force: bool = False,
                              include_knowledge_base: bool = False,
                              knowledge_base_dir: Optional[str | Path] = None) -> int:
        """幂等写入 4 族模板种子."""
        from alpha_operator_framework.generation.template_library import seed_template_library as _seed
        return _seed(self, force=force, include_knowledge_base=include_knowledge_base,
                     knowledge_base_dir=knowledge_base_dir)

    def save_abstracted_template(
        self,
        expression_template: str,
        *,
        family: str = "evolved_distillation",
        title: str = "自主进化蒸馏模板",
        description: str = "",
        support_count: int = 1,
        source: str = "autonomous_distillation",
        example_expression: str = "",
        overwrite: bool = False,
    ) -> bool:
        """从回测胜出因子反向抽象出的模板骨架持久化至 template_library."""
        tpl_clean = expression_template.strip()
        if not tpl_clean:
            return False

        # 提取槽位数 ({a}, {b}, {c})
        slots = sorted(list(set(re.findall(r"\{([a-z])\}", tpl_clean))))
        slot_count = max(len(slots), 1)

        # 生成确定性模板名
        tpl_hash = hashlib.sha256(tpl_clean.encode("utf-8")).hexdigest()[:12]
        tpl_name = f"evolved_{tpl_hash}"

        tpl_model = Template(
            name=tpl_name,
            title=title,
            family=family,
            template_type="expression",
            expression_template=tpl_clean,
            template_index=999,
            fields_per_alpha=slot_count,
            expression_origin=source,
            slot_count=slot_count,
            placeholders={s: "scalar" for s in slots},
            description=description or f"由平台回测胜出因子自主蒸馏沉淀的高阶骨架 (Support: {support_count})",
            example_expression=example_expression,
            source={"type": source, "support": support_count, "hash": tpl_hash},
            active=1,
        )

        inserted = self.upsert_templates([tpl_model], overwrite=overwrite)
        return inserted > 0
