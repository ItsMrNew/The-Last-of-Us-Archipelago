"""Read-only snapshots for the launcher; no check or item mutations."""
from dataclasses import dataclass, replace

from .catalog import CHAPTERS, MISSIONS, CHECKS, PROGRESSIVE_CHAPTER
from .collectible_order import check_order


def death_status(enabled, state):
    if not enabled:
        return 'DeathLink: off' + (' — saved death retained' if state != 'idle' else '')
    return 'DeathLink: ' + {
        'idle': 'enabled', 'queued': 'queued until control returns', 'dispatching': 'delivery in progress',
        'awaiting_death': 'waiting for death confirmation',
        'held': 'confirmation uncertain; next confirmed death clears the hold',
    }[state]


@dataclass(frozen=True)
class CheckRow:
    id: int
    chapter: int
    name: str
    category: str
    status: str
    in_logic: bool | None
    available: bool | None
    access: str
    requirement: str


@dataclass(frozen=True)
class MissionRow:
    index: int
    chapter: str
    name: str
    status: str
    current: bool


@dataclass(frozen=True)
class ChapterRow:
    index: int
    name: str
    unlocked: bool | None
    confirmed: int
    total: int
    available: int | None
    remaining: int


@dataclass(frozen=True)
class Snapshot:
    identity: tuple
    connected: bool
    synchronized: bool
    checks: tuple[CheckRow, ...]
    missions: tuple[MissionRow, ...]
    chapters: tuple[ChapterRow, ...]
    confirmed: int
    awaiting: int
    remaining: int
    unlocked: int
    logic_confirmed: int
    logic_total: int
    available: int
    next_unlock: str
    death: str


def snapshot(session, checked, *, connected, synchronized, current=None, death_enabled=False, death_state='idle'):
    """Copy state on the network thread before passing it to Tk's UI thread."""
    earned = session.earned_checks
    ready = connected and synchronized
    rows = []
    for check in sorted(session.config.active_checks, key=lambda c: (_CHECK_MISSION[c.id], check_order(c))):
        mission = check.mission
        if mission is None:
            mission = max(m['index'] for m in MISSIONS if m['chapter'] == check.chapter)
        status = 'Confirmed' if check.id in checked else 'Awaiting server' if check.id in earned else 'Remaining'
        in_logic = check.chapter in session.unlocked if ready else None
        available = status == 'Remaining' and session.can_start(mission) if ready else None
        if not ready:
            access, requirement = 'Unknown', 'Connect and synchronize items to refresh chapter and mission access.'
        elif not in_logic:
            access = 'Locked'
            needed = check.chapter + 1 - len(session.unlocked)
            requirement = f"Receive {needed} more {PROGRESSIVE_CHAPTER} item(s) to open {CHAPTERS[check.chapter]['name']}."
        elif not session.can_start(mission):
            access = 'In logic'
            requirement = f"Chapter unlocked. Complete earlier missions through {MISSIONS[mission - 1]['name']} first."
        else:
            access = 'Available' if available else 'In logic'
            requirement = ('This mission can be attempted with your current unlocks and story progress. '
                           'Reach the check during gameplay; earlier collectibles may require replaying a matching run save.')
        if status == 'Confirmed':
            requirement = 'The server has acknowledged this check. ' + requirement
        elif status == 'Awaiting server':
            requirement = 'Earned locally; waiting for the server to acknowledge it. ' + requirement
        rows.append(CheckRow(check.id, check.chapter, check.name, check.category, status,
                             in_logic, available, access, requirement))
    rows = tuple(rows)
    completed = set(session.data['missions'])
    missions = tuple(MissionRow(m['index'], CHAPTERS[m['chapter']]['name'], m['name'],
        'Complete' if m['index'] in completed else
        'Waiting for connection' if not connected else 'Waiting for item sync' if not synchronized else
        'Chapter locked' if m['chapter'] not in session.unlocked else
        'Previous mission incomplete' if not session.can_start(m['index']) else 'Available',
        m['index'] == current) for m in MISSIONS)
    unlocked = len(session.unlocked)
    chapters = tuple(ChapterRow(c['index'], c['name'], c['index'] in session.unlocked if ready else None,
                     sum(r.status == 'Confirmed' for r in rows if r.chapter == c['index']),
                     sum(r.chapter == c['index'] for r in rows),
                     sum(r.available is True for r in rows if r.chapter == c['index']) if ready else None,
                     sum(r.status == 'Remaining' for r in rows if r.chapter == c['index'])) for c in CHAPTERS)
    if not connected:
        next_unlock = 'Reconnect to refresh chapter unlocks and mission access.'
    elif not synchronized:
        next_unlock = 'Waiting for the server to synchronize chapter unlocks.'
    elif unlocked == len(CHAPTERS):
        next_unlock = 'All chapters unlocked. Missions still follow story order.'
    else:
        next_unlock = f"Next {PROGRESSIVE_CHAPTER}: {CHAPTERS[unlocked]['name']}"
    return Snapshot(tuple(sorted(session.identity.items())), connected, synchronized, rows, missions, chapters,
                    sum(r.status == 'Confirmed' for r in rows), sum(r.status == 'Awaiting server' for r in rows),
                    sum(r.status == 'Remaining' for r in rows), unlocked,
                    sum(r.in_logic is True and r.status == 'Confirmed' for r in rows),
                    sum(r.in_logic is True for r in rows), sum(r.available is True for r in rows), next_unlock,
                    death_status(death_enabled, death_state))


def filter_checks(view, *, chapter=None, category='All', state='All', access='All', search=''):
    search = search.strip().casefold()
    return tuple(row for row in view.checks
                 if (chapter is None or row.chapter == chapter)
                 and (category == 'All' or row.category == category.lower())
                 and (state == 'All' or row.status == state)
                 and (access == 'All' or (view.connected and view.synchronized and
                      ((access == 'Available' and row.available is True) or
                       (access == 'In logic' and row.in_logic is True) or
                       (access == 'Locked' and row.in_logic is False))))
                 and (not search or search in row.name.casefold()))


def metrics(view):
    """Renegade-style counters; unknown access never looks like a fresh unlock."""
    if view is None:
        return tuple((key, title + ': —', 'Unknown') for key, title in (
            ('total', 'Total checks'), ('logic', 'Checks in logic'), ('chapters', 'Chapters unlocked')))
    ready = view.connected and view.synchronized
    return (
        ('total', f'Total checks: {view.confirmed}/{len(view.checks)}', 'Complete' if view.confirmed == len(view.checks) else 'Total'),
        ('logic', f'Checks in logic: {view.logic_confirmed}/{view.logic_total}' if ready else 'Checks in logic: —',
         'Unknown' if not ready else 'Complete' if view.logic_total and view.logic_confirmed == view.logic_total else 'Logic'),
        ('chapters', f'Chapters unlocked: {view.unlocked}/{len(CHAPTERS)}' if ready else 'Chapters unlocked: —',
         'Unknown' if not ready else 'Complete' if view.unlocked == len(CHAPTERS) else 'Logic'),
    )


@dataclass(frozen=True)
class CampaignMission:
    index: int
    name: str
    chapter: str
    current: bool
    status: str
    tag: str
    confirmed: int
    total: int
    checks: tuple[CheckRow, ...]


_LAST_MISSION = {c['index']: max(m['index'] for m in MISSIONS if m['chapter'] == c['index']) for c in CHAPTERS}
_CHECK_MISSION = {c.id: c.mission if c.mission is not None else _LAST_MISSION[c.chapter] for c in CHECKS}
CHECK_TYPES = ('mission', 'chapter', 'collectible')


def check_status(view, row):
    """Progress remains visible offline, but cached access must not imply permission."""
    if row.status == 'Confirmed':
        return 'Complete', 'confirmed'
    if row.status == 'Awaiting server':
        return 'Pending sync', 'waiting'
    if not (view.connected and view.synchronized):
        return 'Unknown', 'unknown'
    return row.access, row.access.lower().replace('in ', '')


def campaign_missions(view, *, search='', hide_completed=False, categories=CHECK_TYPES):
    """Group enabled checks by mission, preserving full totals when filtering children.

    A chapter check belongs to its final mission. A beaten mission with missing
    collectibles remains incomplete, just like the Renegade campaign tracker.
    """
    if view is None:
        return ()
    grouped = {m.index: [] for m in view.missions}
    for check in view.checks:
        grouped[_CHECK_MISSION[check.id]].append(check)
    ready = view.connected and view.synchronized
    search, categories = search.strip().casefold(), set(categories)
    result = []
    for mission in view.missions:
        checks = tuple(sorted(grouped[mission.index], key=check_order))
        confirmed = sum(c.status == 'Confirmed' for c in checks)
        if checks and confirmed == len(checks):
            status, tag = 'Complete', 'confirmed'
        elif any(c.status == 'Awaiting server' for c in checks):
            status, tag = 'Pending sync', 'waiting'
        elif not ready:
            status, tag = 'Unknown', 'unknown'
        elif mission.status == 'Chapter locked':
            status, tag = 'Locked', 'locked'
        elif mission.status == 'Previous mission incomplete':
            status, tag = 'In logic', 'logic'
        elif not checks and mission.status == 'Complete':
            status, tag = 'Complete', 'confirmed'
        else:
            status, tag = 'Available', 'available'
        full = CampaignMission(mission.index, mission.name, mission.chapter, mission.current,
                               status, tag, confirmed, len(checks), checks)
        mission_matches = search in f'{mission.name} {mission.chapter}'.casefold()
        visible = tuple(c for c in checks if c.category in categories
                        and not (hide_completed and c.status == 'Confirmed')
                        and (mission_matches or search in c.name.casefold()))
        # Missions without any enabled checks still communicate campaign access.
        empty_mission = (not checks and categories == set(CHECK_TYPES) and mission_matches
                         and not (hide_completed and status == 'Complete'))
        if visible or empty_mission:
            result.append(replace(full, checks=visible))
    return tuple(result)
