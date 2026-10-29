"""A bounded shadow evaluation window; never activates routing or executes trades.

Configuration, timezone and clock are explicit. Imports perform no IO. Trial
reporting includes native live rows after its initial input watermark, keeping
saved-cycle probes separate. New callers can reserve a single request atomically;
legacy already-running callers are reported honestly as unreserved native work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import text

DDL_TRIALS = """CREATE TABLE IF NOT EXISTS policy_router_shadow_trials (
 id TEXT PRIMARY KEY, config_hash VARCHAR(50) NOT NULL,
 starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, stopped_at TEXT,
 status TEXT NOT NULL, after_input_id INTEGER NOT NULL,
 source_timezone TEXT NOT NULL, max_call_usd DOUBLE PRECISION NOT NULL,
 budget_usd DOUBLE PRECISION NOT NULL,
 collection_mode TEXT NOT NULL DEFAULT 'native_shadow')"""
DDL_CLAIMS = """CREATE TABLE IF NOT EXISTS policy_router_shadow_claims (
 trial_id TEXT NOT NULL, source_input_id INTEGER NOT NULL,
 status TEXT NOT NULL, reserved_usd DOUBLE PRECISION NOT NULL,
 cost_usd DOUBLE PRECISION, comparison_id INTEGER, diagnostic TEXT,
 claimed_at TEXT NOT NULL, completed_at TEXT,
 PRIMARY KEY (trial_id,source_input_id))"""


class TrialError(ValueError):
    """Fixed local diagnostic, never a raw database or provider error."""


def _utc(now=None):
    value = now or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TrialError('timezone_aware_clock_required')
    return value.astimezone(timezone.utc)


def _parse(value):
    return datetime.fromisoformat(str(value)).astimezone(timezone.utc)


def _cfg(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', value):
        raise TrialError('invalid_configuration')
    return value


def ensure_schema(engine):
    from .decisions_log import ensure_schema as ensure_comparisons
    ensure_comparisons(engine)
    with engine.begin() as conn:
        conn.execute(text(DDL_TRIALS)); conn.execute(text(DDL_CLAIMS))
        conn.execute(text('CREATE INDEX IF NOT EXISTS ix_shadow_trials_config ON policy_router_shadow_trials(config_hash,starts_at)'))


def _latest(conn, config_hash, *, lock=False):
    sql = 'SELECT * FROM policy_router_shadow_trials WHERE config_hash=:h ORDER BY starts_at DESC,id DESC LIMIT 1'
    if lock and conn.dialect.name == 'postgresql':
        sql += ' FOR UPDATE'
    return conn.execute(text(sql), {'h': config_hash}).mappings().first()


def _money(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def start_trial(engine, config_hash, *, days=7, max_call_usd=.05, budget_usd=2.0,
                source_timezone='America/Los_Angeles', now=None, restart=False):
    """Start once at the latest saved input; rerunning does not extend the week.

    ``restart=True`` is an explicit new evaluation, allowed only after the prior
    window completed or was stopped. No historic input can be claimed.
    """
    _cfg(config_hash); clock = _utc(now)
    if days != 7 or isinstance(days, bool):
        raise TrialError('trial_requires_seven_calendar_days')
    if not _money(max_call_usd) or not _money(budget_usd) or max_call_usd > budget_usd or budget_usd > 25:
        raise TrialError('invalid_trial_budget')
    try:
        ZoneInfo(source_timezone)
    except Exception:
        raise TrialError('invalid_source_timezone') from None
    ensure_schema(engine)
    with engine.begin() as conn:
        # Lock the configuration even before its first row exists. Locking only
        # _latest cannot serialize two first-ever starts.
        if conn.dialect.name == 'postgresql':
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'),
                         {'scope':'policy-router-shadow-start:'+config_hash})
        elif conn.dialect.name == 'sqlite':
            conn.exec_driver_sql('BEGIN IMMEDIATE')
        previous = _latest(conn, config_hash, lock=True)
        if previous and (not restart or previous['status'] == 'running' and clock < _parse(previous['ends_at'])):
            pass
        else:
            watermark = int(conn.execute(text("SELECT COALESCE(MAX(id),0) FROM decider_inputs WHERE config_hash=:h AND call_kind='decide'"),
                                         {'h':config_hash}).scalar_one())
            conn.execute(text('''INSERT INTO policy_router_shadow_trials
                (id,config_hash,starts_at,ends_at,status,after_input_id,source_timezone,max_call_usd,budget_usd)
                VALUES (:i,:h,:s,:e,'running',:w,:z,:m,:b)'''),
                {'i':uuid.uuid4().hex,'h':config_hash,'s':clock.isoformat(),'e':(clock+timedelta(days=7)).isoformat(),
                 'w':watermark,'z':source_timezone,'m':float(max_call_usd),'b':float(budget_usd)})
    return trial_status(engine, config_hash, now=clock)


def _public(row, clock):
    status = 'completed' if row['status'] == 'running' and clock >= _parse(row['ends_at']) else row['status']
    return {**dict(row), 'status':status, 'mode':'shadow', 'active':status=='running',
            'auto_promote':False, 'realized_input_savings_usd':0.0,
            'remaining_seconds':max(0,int((_parse(row['ends_at'])-clock).total_seconds())) if status=='running' else 0,
            'note':'Seven-calendar-day shadow evaluation. No selection changes the trading prompt; completion requires review, never automatic promotion.'}


def _in_window_rows(conn, row):
    zone = ZoneInfo(row['source_timezone'])
    start = _parse(row['starts_at']).astimezone(zone).replace(tzinfo=None)
    end = _parse(row['stopped_at'] or row['ends_at']).astimezone(zone).replace(tzinfo=None)
    try:
        # Native comparison timestamps are naive local wall time. The timezone
        # is declared above rather than silently comparing them with UTC.
        return conn.execute(text('''SELECT id,source_kind,source_input_id,status,request_attempted,cost_usd,latency_ms
            FROM policy_router_comparisons WHERE config_hash=:h AND source_kind IN ('live','observer')
            AND source_input_id>:w AND decided_at>=:s AND decided_at<:e ORDER BY id'''),
            {'h':row['config_hash'],'w':row['after_input_id'],'s':start,'e':end}).mappings().all()
    except Exception:
        return []


def trial_status(engine, config_hash, *, now=None):
    """Read-only report. Missing tables remain an explicit not-started state."""
    _cfg(config_hash); clock = _utc(now)
    empty = {'status':'not_started','active':False,'mode':'shadow','auto_promote':False,
             'realized_input_savings_usd':0.0,'note':'No one-week evaluation has started for this configuration.'}
    try:
        with engine.connect() as conn:
            row = _latest(conn, config_hash)
            if not row:
                return empty
            result = _public(row, clock)
            claims = conn.execute(text('SELECT * FROM policy_router_shadow_claims WHERE trial_id=:i'), {'i':row['id']}).mappings().all()
            runs = _in_window_rows(conn, row)
    except Exception:
        return empty
    known = sum(float(r['cost_usd']) for r in runs if r['cost_usd'] is not None)
    unknown = sum(bool(r['request_attempted']) and r['cost_usd'] is None for r in runs)
    reserved = sum(float(c['reserved_usd']) for c in claims if c['cost_usd'] is None and c['status'] != 'skipped')
    claimed_cost = sum(float(c['cost_usd'] or 0) for c in claims)
    # Native legacy rows may have no claim; count those dollars exactly once.
    claimed_ids = {c['comparison_id'] for c in claims if c['comparison_id'] is not None}
    unreserved_cost = sum(float(r['cost_usd']) if r['cost_usd'] is not None
                          else float(row['max_call_usd']) if r['request_attempted'] else 0
                          for r in runs if r['id'] not in claimed_ids)
    committed = claimed_cost + reserved + unreserved_cost
    result.update(cycles=len(runs), native_cycles=sum(r['source_kind']=='live' for r in runs),
                  observer_cycles=sum(r['source_kind']=='observer' for r in runs),
                  successful_cycles=sum(r['status']=='ok' for r in runs),
                  fallback_cycles=sum(r['status']!='ok' for r in runs),
                  request_attempts=sum(bool(r['request_attempted']) for r in runs),
                  known_cost_usd=known, cost_usd=None if unknown else known, unknown_cost_calls=unknown,
                  reserved_cost_usd=reserved, committed_budget_usd=committed,
                  remaining_budget_usd=max(0,float(row['budget_usd'])-committed),
                  unreserved_native_calls=sum(r['source_kind']=='live' and r['id'] not in claimed_ids for r in runs),
                  budget_enforcement='Atomic reservations apply to integrated callers. Already-running legacy native callers are counted but cannot be retroactively budget-gated.',
                  quality_status='unmeasured', required_review=['matched full-versus-routed decisions','later independent outcomes','net cost including router overhead'])
    return result


def stop_trial(engine, config_hash, *, now=None):
    clock = _utc(now); _cfg(config_hash)
    with engine.begin() as conn:
        row = _latest(conn, config_hash, lock=True)
        if row and row['status']=='running' and clock < _parse(row['ends_at']):
            conn.execute(text("UPDATE policy_router_shadow_trials SET status='stopped',stopped_at=:s WHERE id=:i"),
                         {'i':row['id'],'s':clock.isoformat()})
    return trial_status(engine, config_hash, now=clock)


def reserve_cycle(engine, config_hash, source_input_id, *, cost_bound_usd, now=None):
    """Atomically reserve one finite-fee request; a crash never permits a retry.

    The caller must calculate a conservative bound before sending the request.
    ``None`` means no permission to send: wrong scope, duplicate, expired or
    exhausted trial. A reservation alone is not a model/API request.
    """
    _cfg(config_hash); clock = _utc(now)
    if not isinstance(source_input_id,int) or isinstance(source_input_id,bool) or not _money(cost_bound_usd):
        raise TrialError('invalid_cycle_reservation')
    with engine.begin() as conn:
        row = _latest(conn, config_hash, lock=True)
        if not row or row['status']!='running' or clock >= _parse(row['ends_at']) or clock < _parse(row['starts_at']):
            return None
        if cost_bound_usd > row['max_call_usd'] or source_input_id <= row['after_input_id']:
            return None
        source = conn.execute(text("SELECT id FROM decider_inputs WHERE id=:i AND config_hash=:h AND call_kind='decide'"),
                              {'i':source_input_id,'h':config_hash}).first()
        if not source:
            return None
        exists = conn.execute(text('SELECT 1 FROM policy_router_shadow_claims WHERE trial_id=:t AND source_input_id=:i'),
                              {'t':row['id'],'i':source_input_id}).first()
        if exists:
            return None
        try:
            recorded = conn.execute(text("SELECT 1 FROM policy_router_comparisons WHERE config_hash=:h AND source_input_id=:i AND source_kind IN ('live','observer') LIMIT 1"),
                                    {'h':config_hash,'i':source_input_id}).first()
        except Exception:
            recorded = None
        if recorded:
            return None
        claims = conn.execute(text('SELECT reserved_usd,cost_usd,status,comparison_id FROM policy_router_shadow_claims WHERE trial_id=:i'), {'i':row['id']}).mappings().all()
        committed = sum(float(c['cost_usd']) if c['cost_usd'] is not None else float(c['reserved_usd']) if c['status']!='skipped' else 0 for c in claims)
        claimed_ids={c['comparison_id'] for c in claims if c['comparison_id'] is not None}
        native = _in_window_rows(conn,row)
        committed += sum(float(r['cost_usd'] or row['max_call_usd']) for r in native if r['id'] not in claimed_ids and r['request_attempted'])
        if committed + cost_bound_usd > row['budget_usd'] + 1e-12:
            return None
        conn.execute(text("""INSERT INTO policy_router_shadow_claims
            (trial_id,source_input_id,status,reserved_usd,claimed_at)
            VALUES (:t,:i,'claimed',:r,:s)"""),
            {'t':row['id'],'i':source_input_id,'r':float(cost_bound_usd),'s':clock.isoformat()})
    return {'trial_id':row['id'],'source_input_id':source_input_id,'reserved_usd':float(cost_bound_usd)}


def complete_cycle(engine, config_hash, reservation, *, comparison_id=None, cost_usd=None,
                   request_attempted=True, diagnostic=None, now=None):
    """Settle once; unknown billed cost keeps the reservation instead of free retries."""
    _cfg(config_hash); clock=_utc(now)
    if cost_usd is not None and (not isinstance(cost_usd,(int,float)) or isinstance(cost_usd,bool) or not math.isfinite(cost_usd) or cost_usd<0):
        raise TrialError('invalid_settlement_cost')
    if diagnostic not in (None,'request_failed','request_not_sent','record_unavailable'):
        raise TrialError('invalid_settlement_diagnostic')
    with engine.begin() as conn:
        row=conn.execute(text('SELECT c.* FROM policy_router_shadow_claims c JOIN policy_router_shadow_trials t ON t.id=c.trial_id WHERE t.config_hash=:h AND c.trial_id=:t AND c.source_input_id=:i'),
                         {'h':config_hash,'t':reservation['trial_id'],'i':reservation['source_input_id']}).mappings().first()
        if not row or row['status']!='claimed':
            return False
        if comparison_id is not None:
            linked=conn.execute(text('SELECT id FROM policy_router_comparisons WHERE config_hash=:h AND id=:c AND source_input_id=:i'),
                                {'h':config_hash,'c':int(comparison_id),'i':reservation['source_input_id']}).first()
            if not linked:
                raise TrialError('comparison_scope_mismatch')
        conn.execute(text('''UPDATE policy_router_shadow_claims SET status=:s,cost_usd=:c,comparison_id=:r,
            diagnostic=:d,completed_at=:at WHERE trial_id=:t AND source_input_id=:i AND status='claimed' '''),
            {'s':'completed' if request_attempted else 'skipped','c':cost_usd if request_attempted else 0.0,
             'r':comparison_id,'d':diagnostic,'at':clock.isoformat(),'t':reservation['trial_id'],'i':reservation['source_input_id']})
    return True


def cycle_list(engine, config_hash, *, limit=100, now=None):
    from .decisions_log import comparison_panel
    out=comparison_panel(engine, config_hash, last_n=max(1,min(int(limit),200)))
    out['trial']=trial_status(engine,config_hash,now=now)
    return out


__all__=['TrialError','ensure_schema','start_trial','trial_status','stop_trial','reserve_cycle','complete_cycle','cycle_list']
