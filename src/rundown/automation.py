"""Bounded jobs for external schedulers and local agent context."""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from threading import Event
from typing import Any

from . import db, research_workflow
from .agent_catalog import catalog_repositories
from .agent_io import AgentError, read_catalog, validate_limit
from .catalog import is_research_stale
from .config import AppConfig
from .inspection import inspect_repository
from .processes import OperationCancelled


def _validate_days(stale_days: int) -> None:
    if isinstance(stale_days, bool) or not isinstance(stale_days, int) or not 1 <= stale_days <= 3650:
        raise AgentError('invalid_input', 'stale_days must be between 1 and 3650', 2)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row['name']) for row in conn.execute(f'PRAGMA table_info({table})')}
    except sqlite3.Error:
        return set()


def _invalid_nonempty_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return True
    return False


def _refresh_rows(conn: sqlite3.Connection, project: str | None):
    repo_columns = _columns(conn, 'repos')
    if not {'id', 'full_name'}.issubset(repo_columns):
        return iter(())
    research_columns = _columns(conn, 'research_logs')
    has_research = {'id', 'repo_id'}.issubset(research_columns)
    selected = [
        'repos.id AS repo_id',
        'repos.full_name AS full_name',
        'repos.last_pushed AS last_pushed' if 'last_pushed' in repo_columns else 'NULL AS last_pushed',
        'research.id AS research_id' if has_research else 'NULL AS research_id',
        'research.timestamp AS research_timestamp'
        if has_research and 'timestamp' in research_columns
        else 'NULL AS research_timestamp',
    ]
    joins: list[str] = []
    params: list[Any] = []
    if has_research:
        filters = []
        if 'status' in research_columns:
            filters.append("status = 'success'")
        if 'pass_type' in research_columns:
            filters.append("pass_type = 'Repository Understanding'")
        research_where = f"WHERE {' AND '.join(filters)}" if filters else ''
        saved_timestamp = 'saved.timestamp' if 'timestamp' in research_columns else 'NULL'
        joins.append(
            'LEFT JOIN ('
            f'SELECT saved.id, saved.repo_id, {saved_timestamp} AS timestamp '
            'FROM research_logs saved JOIN ('
            'SELECT repo_id, MAX(id) AS latest_id FROM research_logs '
            f'{research_where} GROUP BY repo_id'
            ') latest ON latest.latest_id = saved.id'
            ') research ON research.repo_id = repos.id'
        )
    where: list[str] = []
    if 'archived' in repo_columns:
        where.append('COALESCE(repos.archived, 0) = 0')
    if 'status' in repo_columns:
        where.append("COALESCE(repos.status, '') != 'archived'")
    if project is not None:
        mapping_columns = _columns(conn, 'project_mappings')
        if not {'repo_id', 'project_name'}.issubset(mapping_columns):
            return iter(())
        where.append(
            'EXISTS (SELECT 1 FROM project_mappings mapping '
            'WHERE mapping.repo_id = repos.id AND mapping.project_name = ?)'
        )
        params.append(project)
    clause = f"WHERE {' AND '.join(where)}" if where else ''
    research_missing = 'research.id IS NULL' if has_research else '1'
    research_timestamp = 'research.timestamp' if has_research and 'timestamp' in research_columns else 'NULL'
    return iter(
        conn.execute(
            f"SELECT {', '.join(selected)} FROM repos {' '.join(joins)} {clause} "
            f'ORDER BY CASE WHEN {research_missing} THEN 0 ELSE 1 END, '
            f'CASE WHEN datetime({research_timestamp}) IS NULL THEN 0 ELSE 1 END, '
            f'datetime({research_timestamp}), repos.full_name COLLATE NOCASE, repos.id',
            params,
        )
    )


def project_digest(conn: sqlite3.Connection, *, project: str | None = None,
                   limit: int = 5, stale_days: int = 30) -> dict[str, Any]:
    """Summarize saved project-fit rankings, not newly inferred recommendations."""
    _validate_days(stale_days)
    catalog = catalog_repositories(conn, project=project, limit=limit)
    items = []
    for repo in catalog['results']:
        packet = inspect_repository(conn, repo['full_name'], stale_days=stale_days)
        generated = packet['generated_research']
        record = generated.get('record') or {}
        sections = record.get('sections') or {}
        summary = sections.get('what_it_is') or record.get('text') or repo.get('description') or ''
        items.append({
            'full_name': repo['full_name'], 'description': repo.get('description'),
            'summary': summary[:800], 'summary_truncated': len(summary) > 800,
            'summary_source': 'generated_research_unverified' if sections or record.get('text') else 'github_metadata',
            'projects': repo['projects'], 'relevance_score': repo['relevance_score'],
            'staleness': packet['staleness'], 'missing_information': packet['missing_information'],
            'next_action': 'research' if packet['staleness']['state'] in {'missing', 'stale'} else 'inspect',
        })
    return {'project': project, 'results': items, 'count': len(items),
            'total_count': catalog['total_count'], 'truncated': catalog['truncated'],
            'ranking': 'saved project fit, then saved relevance score, then repository name',
            'generated_at': db.now_utc(), 'network_used': False}


def refresh_candidates(conn: sqlite3.Connection, *, limit: int = 10,
                       stale_days: int = 30, project: str | None = None) -> list[dict[str, Any]]:
    validate_limit(limit, 50)
    _validate_days(stale_days)
    if project is not None and (not project.strip() or len(project) > 200):
        raise AgentError('invalid_input', 'project must contain 1–200 characters', 2)
    now = datetime.now(timezone.utc)
    candidates = []
    for raw in _refresh_rows(conn, project):
        row = dict(raw)
        if row['research_id'] is None:
            reason = 'missing'
        elif (
            is_research_stale(
                row,
                {'timestamp': row['research_timestamp']},
                stale_days=stale_days,
                now=now,
            )
            or _invalid_nonempty_timestamp(row.get('last_pushed'))
        ):
            reason = 'stale'
        else:
            continue
        candidates.append({'full_name': row['full_name'], 'reason': reason,
                           'research_timestamp': row['research_timestamp']})
        if len(candidates) == limit:
            break
    return candidates


def refresh_repositories(config: AppConfig, *, limit: int = 10, stale_days: int = 30,
                         project: str | None = None, dry_run: bool = False,
                         cancel_event: Event | None = None) -> dict[str, Any]:
    with read_catalog(config) as conn:
        selected = refresh_candidates(conn, limit=limit, stale_days=stale_days, project=project)
    report: dict[str, Any] = {'status': 'dry_run' if dry_run else 'success', 'selected': selected,
                             'results': [], 'succeeded': 0, 'failed': 0, 'cancelled': False,
                             'limit': limit, 'stale_days': stale_days, 'project': project,
                             'remaining': len(selected)}
    if dry_run or not selected:
        return report
    event = cancel_event if cancel_event is not None else Event()
    config.ensure_directories()
    for item in selected:
        name = item['full_name']
        try:
            if event.is_set():
                raise OperationCancelled('Cancelled by user.')
            with db.session(config.database_path) as conn:
                db.init_db(conn)
                status, summary = research_workflow.research_repository(
                    config, conn, name, force=item['reason'] == 'stale', cancel_event=event,
                )
            if status == 'cancelled':
                raise OperationCancelled(summary)
        except (KeyboardInterrupt, OperationCancelled):
            event.set()
            report['cancelled'] = True
            report['status'] = 'cancelled'
            report['results'].append({'full_name': name, 'status': 'cancelled'})
            break
        except Exception as exc:
            status, summary = 'failed', str(exc)
        report['results'].append({'full_name': name, 'status': status, 'summary': summary[:1200],
                                  'summary_truncated': len(summary) > 1200})
        if status in {'success', 'cached'}:
            report['succeeded'] += 1
        else:
            report['failed'] += 1
        report['remaining'] -= 1
    if report['failed'] and not report['cancelled']:
        report['status'] = 'partial_failure'
    return report
