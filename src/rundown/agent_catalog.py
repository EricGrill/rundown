"""Small metadata listings shared by machine CLI and local agent tools."""
from __future__ import annotations

import sqlite3
from typing import Any

from .agent_io import AgentError, validate_limit


def catalog_repositories(
    conn: sqlite3.Connection, *, project: str | None = None,
    include_archived: bool = False, limit: int = 100,
) -> dict[str, Any]:
    validate_limit(limit)
    if project is not None and (not isinstance(project, str) or not project.strip() or len(project) > 200):
        raise AgentError('invalid_input', 'project must contain 1–200 characters', 2)
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(repos)')}
    mapping_columns = {row['name'] for row in conn.execute('PRAGMA table_info(project_mappings)')}
    has_mappings = {'repo_id', 'project_name'}.issubset(mapping_columns)
    conditions = []
    params: list[Any] = []
    if not include_archived:
        if 'archived' in columns:
            conditions.append('COALESCE(r.archived, 0) = 0')
        if 'status' in columns:
            conditions.append("COALESCE(r.status, '') != 'archived'")
    if project is not None:
        if has_mappings:
            conditions.append('EXISTS (SELECT 1 FROM project_mappings p WHERE p.repo_id=r.id AND p.project_name=?)')
            params.append(project)
        else:
            conditions.append('0')
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    count = conn.execute('SELECT COUNT(*) FROM repos r' + where, params).fetchone()[0]
    fields = ('id', 'full_name', 'url', 'description', 'language', 'stars', 'starred',
              'starred_at', 'last_pushed', 'status', 'decision', 'relevance_score')
    numeric = {'id', 'stars', 'starred', 'relevance_score'}
    selection = [f'r.{key} AS {key}' if key in numeric else f'substr(r.{key},1,1200) AS {key}'
                 for key in fields if key in columns]
    ordering = []
    order_params: list[Any] = []
    if project is not None and has_mappings and 'fit_score' in mapping_columns:
        ordering.append('COALESCE((SELECT MAX(p.fit_score) FROM project_mappings p WHERE p.repo_id=r.id AND p.project_name=?),0) DESC')
        order_params.append(project)
    if 'relevance_score' in columns:
        ordering.append('COALESCE(r.relevance_score,0) DESC')
    ordering.extend(['r.full_name COLLATE NOCASE', 'r.id'])
    rows = conn.execute('SELECT '+','.join(selection)+' FROM repos r'+where+
                        ' ORDER BY '+','.join(ordering)+' LIMIT ?', (*params, *order_params, limit)).fetchall()
    results = []
    for raw in rows:
        row = dict(raw)
        projects = []
        if has_mappings:
            fit = 'fit_score' if 'fit_score' in mapping_columns else 'NULL'
            reason = 'substr(reason,1,1200)' if 'reason' in mapping_columns else 'NULL'
            projects = [dict(p) for p in conn.execute(
                f'SELECT substr(project_name,1,200) AS project_name,{fit} AS fit_score,{reason} AS reason '
                'FROM project_mappings WHERE repo_id=? ORDER BY project_name LIMIT 100', (row['id'],)
            )]
        result = {key: row.get(key) for key in fields}
        result['projects'] = projects
        results.append(result)
    return {'results': results, 'count': len(results), 'total_count': count,
            'limit': limit, 'truncated': count > limit, 'project': project,
            'text_limit_per_field': 1200, 'project_limit_per_repository': 100}
