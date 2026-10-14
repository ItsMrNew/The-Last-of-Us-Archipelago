"""Copied, read-only delivery/history rows shared by UI and diagnostics."""
from .catalog import TIMED_TRAPS, AIRHORN, ITEM_IDS, PROGRESSIVE_CHAPTER, DELIVERABLES


def display_rows(status):
    """Do not present an old active/confirming snapshot as live after disconnect."""
    status = status or {}
    result = []
    for row in status.get('deliveries', []):
        row = dict(row)
        if not status.get('connected') and row['state'] not in ('Delivered', 'Completed', 'Applied', 'Retired', 'Held'):
            row.update(state='Waiting', reason='Disconnected — awaiting fresh status. Last known: ' + row['reason'])
        result.append(row)
    return result


def pending_supply_summary(status):
    """Compact live details beneath the launcher's delivery counters."""
    groups = {}
    for row in display_rows(status):
        if row['item'] not in DELIVERABLES or row['state'] in ('Delivered', 'Retired'):
            continue
        reason = ('Disconnected; waiting to reconnect' if not status.get('connected')
                  and row['state'] != 'Held' else row['reason'])
        key = row['item'], reason
        groups[key] = groups.get(key, 0) + 1
    if not groups:
        return ''
    return 'Pending rewards: ' + '  •  '.join(
        f'{name} ×{count} — {reason}' for (name, reason), count in groups.items())


def delivery_snapshot(client, context=None):
    context = context or {}
    rows = []
    session = client.session
    if not session:
        return rows
    waiting = ('Disconnected; waiting to reconnect' if not client.connected else
               'Waiting for authoritative item synchronization' if not client.inventory.synchronized else '')
    names = {code: name for name, code in ITEM_IDS.items()}
    for index, item in enumerate(session.data['received']):
        key = str(index)
        name = names[item['item']]
        state, reason = 'Queued', waiting
        if name == PROGRESSIVE_CHAPTER:
            state, reason = ('Applied', 'Chapter access updated') if not waiting else ('Waiting', waiting)
        elif name in TIMED_TRAPS:
            entry = (client.timed_effects.data or {}).get('items', {}).get(key)
            if entry:
                remaining = max(0, 30000 - entry['elapsed'])
                state = 'Completed' if not remaining else 'Active' if client.timed_effects.ready else 'Paused'
                reason = 'Trap completed' if not remaining else (waiting or
                    f'{remaining / 1000:.1f}s remaining; same-kind traps stack; playable time only')
        elif name == AIRHORN:
            entry = (client.airhorn.data or {}).get('items', {}).get(key)
            if entry:
                state = {'queued': 'Queued', 'active': 'Active' if client.airhorn.playable else 'Paused',
                         'pending': 'Confirming', 'held': 'Held', 'done': 'Completed'}[entry['state']]
                detail = (f'{max(0, entry["duration"] - entry["elapsed"] / 1000):.1f}s remaining'
                          if entry['mode'] == 'timed' else 'Single blast')
                if entry['state'] == 'held':
                    reason = 'Outcome uncertain; recovery decision required'
                elif entry['state'] == 'done':
                    reason = entry.get('resolution', 'Trap completed')
                    if reason.startswith('Retired'):
                        state = 'Retired'
                else:
                    reason = f'{detail} · {waiting or context.get("airhorn_reason", context.get("reason")) or "Waiting / running on gameplay time"}'
        else:
            receipt = session.data['receipts'].get(key)
            if receipt == 'applied':
                native = getattr(client.adapter, 'ledger', None)
                record = native.data['deliveries'].get(f'{session.path.stem}:{index}', {}) if native else {}
                retired = isinstance(record, dict) and record.get('outcome') == 'retired'
                state, reason = ('Retired', 'Cleared without regranting') if retired else ('Delivered', 'Confirmed by game')
            elif receipt in ('reserved', 'uncertain'):
                native = getattr(client.adapter, 'ledger', None)
                record = native.data['deliveries'].get(f'{session.path.stem}:{index}', {}) if native else {}
                confirming = (isinstance(record, dict) and record.get('outcome') == 'pending'
                              and record.get('native_instance') == getattr(client.adapter, 'native_instance', None))
                state = 'Confirming' if confirming else 'Held'
                reason = 'Awaiting native receipt confirmation' if confirming else 'Outcome uncertain; recovery decision required'
            else:
                reason = waiting or context.get('supplies', {}).get(item['item'], 'Waiting for gameplay and inventory space')
        rows.append({'key': key, 'item': name, 'state': state, 'reason': reason,
                     'source': client.feed.name(item['player'])})
    death = client.deathlink
    if death.data['incoming']:
        incoming = death.data['incoming']
        reason = ('DeathLink disabled; waiting death preserved' if not death.enabled else waiting
                  or ('Outcome uncertain; waiting for a confirmed death' if death.state == 'held'
                      else context.get('death_reason', context.get('reason')) or 'Waiting for controllable gameplay / native confirmation'))
        rows.append({'key': 'deathlink', 'item': 'DeathLink', 'state': death.state.replace('_', ' ').title(),
                     'reason': reason, 'source': incoming['source']})
    return rows
