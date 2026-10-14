from dataclasses import FrozenInstanceError, replace
import tempfile
import unittest

from tlou_ap.catalog import Config, ITEM_IDS, PROGRESSIVE_CHAPTER, CHAPTERS, MISSIONS, COLLECTIBLES
from tlou_ap.collectible_order import MISSION_COLLECTIBLES
from tlou_ap.session import Session, ReceivedItem
from tlou_ap.tracker import snapshot, filter_checks, death_status, metrics, campaign_missions, check_status


class TrackerTests(unittest.TestCase):
    def test_pickup_order_covers_every_collectible_once_in_its_existing_mission(self):
        flattened = [i for row in MISSION_COLLECTIBLES for i in row]
        self.assertEqual(len(MISSION_COLLECTIBLES), len(MISSIONS))
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), {c['index'] for c in COLLECTIBLES})
        for mission, indexes in enumerate(MISSION_COLLECTIBLES):
            self.assertEqual(set(indexes), {c['index'] for c in COLLECTIBLES if c['mission'] == mission})

    def test_financial_district_route_survives_acknowledgements_and_filters(self):
        expected = [19713037, 19713036, 19713031, 19713039]
        for checked in ((), expected[:2], expected):
            view = self.view(checked)
            rows = campaign_missions(view, search='Financial District', categories=('collectible',))
            self.assertEqual([c.id for c in rows[0].checks], expected)
            flat = filter_checks(view, category='Collectible', search='Financial District')
            self.assertEqual([c.id for c in flat], expected)
            remaining = campaign_missions(view, search='Financial District', categories=('collectible',), hide_completed=True)
            self.assertEqual([c.id for m in remaining for c in m.checks], [i for i in expected if i not in checked])

    def test_route_interleaves_collectible_types_and_starts_with_automatic_items(self):
        missions = campaign_missions(self.view(), categories=('collectible',))
        by_mission = {m.index: [c.id - 19713000 for c in m.checks] for m in missions}
        self.assertEqual(by_mission[2], [5, 6, 84, 2, 85])
        self.assertEqual(by_mission[14], [42, 117, 43, 131, 96, 118])
        self.assertEqual(by_mission[13][:2], [27, 128])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.session = Session(self.folder.name, 'seed', 0, 1, 'run', Config())

    def view(self, checked=(), **options):
        return snapshot(self.session, checked, connected=True, synchronized=True, **options)

    def test_server_acknowledgements_are_distinct_from_local_progress(self):
        self.session.complete_mission(0)
        earned = self.session.earned_checks
        view = self.view({min(earned)})
        self.assertEqual((view.confirmed, view.awaiting, view.remaining), (1, 1, 179))
        self.assertEqual(view.confirmed + view.awaiting + view.remaining, len(view.checks))
        self.assertEqual(view.missions[0].status, 'Complete')
        # Acknowledged room checks can predate this local save/run's progress.
        other = self.view({19711002})
        self.assertEqual(other.confirmed, 1)
        self.assertEqual(other.awaiting, 2)

    def test_snapshots_are_immutable_and_do_not_mutate_session(self):
        view = self.view()
        self.assertFalse(self.session.path.exists())
        self.session.complete_mission(0)
        self.assertEqual(view.missions[0].status, 'Available')
        self.assertEqual(view.awaiting, 0)
        with self.assertRaises(FrozenInstanceError): view.confirmed = 10

    def test_story_order_and_next_unlock(self):
        view = self.view(current=1)
        self.assertEqual(view.missions[1].status, 'Previous mission incomplete')
        self.assertTrue(view.missions[1].current)
        self.assertIn(CHAPTERS[2]['name'], view.next_unlock)
        index = next(m['index'] for m in MISSIONS if m['chapter'] == 2)
        self.assertEqual(view.missions[index].status, 'Chapter locked')
        self.session.record_inventory([ReceivedItem(ITEM_IDS[PROGRESSIVE_CHAPTER], 1, 1, 1)])
        view = self.view()
        self.assertEqual(view.unlocked, 3)
        self.assertIn(CHAPTERS[3]['name'], view.next_unlock)
        self.assertEqual(view.missions[index].status, 'Previous mission incomplete')

    def test_cached_unlocks_not_presented_as_available_before_sync(self):
        view = snapshot(self.session, (), connected=True, synchronized=False)
        self.assertEqual(view.missions[0].status, 'Waiting for item sync')
        self.assertIn('synchronize', view.next_unlock)

    def test_disabled_categories_excluded_but_mission_access_remains(self):
        for config, count in [(Config(collectible_checks=False), 41),
                              (Config(chapter_checks=False, mission_checks=False), 140),
                              (Config(collectible_checks=False, chapter_checks=False), 29)]:
            self.session = Session(self.folder.name, 'seed', 0, 1, 'run', config)
            view = self.view()
            self.assertEqual(len(view.checks), count)
            self.assertEqual(len(view.missions), 29)

    def test_filters_find_drafting_notice_and_completed_check(self):
        self.session.complete_mission(0)
        view = self.view()
        results = filter_checks(view, chapter=1, category='Collectible', state='Remaining', search=' DRAFTING ')
        self.assertEqual(len(results), 1)
        self.assertIn('Drafting Notice', results[0].name)
        self.assertEqual(filter_checks(view, chapter=2, search='Drafting'), ())
        self.assertEqual(len(filter_checks(view, state='Awaiting server')), 2)

    def test_all_chapters_open_and_death_hold_are_explicit(self):
        self.session = Session(self.folder.name, 'seed', 0, 1, 'run', Config(starting_chapters=12))
        view = self.view(death_enabled=True, death_state='held')
        self.assertIn('All chapters unlocked', view.next_unlock)
        self.assertIn('uncertain', view.death)
        self.assertIn('saved death retained', death_status(False, 'queued'))

    def test_available_and_in_logic_have_distinct_meanings(self):
        view = self.view()
        self.assertEqual(view.logic_total, 17)  # Hometown + Quarantine Zone, including future missions.
        self.assertEqual(view.available, 2)  # Prologue mission and Hometown chapter completion.
        self.assertEqual({r.id for r in filter_checks(view, access='Available')}, {19711000, 19712000})
        notice = next(r for r in view.checks if 'Drafting Notice' in r.name)
        self.assertTrue(notice.in_logic); self.assertFalse(notice.available)
        self.assertEqual(notice.access, 'In logic')
        self.assertIn('Beyond The Wall', notice.requirement)
        locked = next(r for r in view.checks if r.chapter == 2)
        self.assertFalse(locked.in_logic)
        self.assertIn('1 more Progressive Chapter Unlock', locked.requirement)

    def test_story_progress_makes_checks_available_without_new_items(self):
        for mission in range(3): self.session.complete_mission(mission)
        view = self.view(self.session.earned_checks)
        self.assertEqual((view.logic_confirmed, view.logic_total, view.available), (4, 17, 10))
        self.assertTrue(next(r.available for r in view.checks if 'Drafting Notice' in r.name))
        self.assertFalse(next(r.available for r in view.checks if r.id == 19712001))  # Cargo still ahead.
        self.session.complete_mission(3)
        self.assertTrue(next(r.available for r in self.view().checks if r.id == 19712001))

    def test_earned_pending_checks_are_never_available_again(self):
        self.session.complete_mission(0)
        view = self.view()
        self.assertEqual(view.awaiting, 2)
        self.assertEqual(view.available, 1)  # 20 Years Later only.
        self.assertTrue(all(r.status == 'Remaining' for r in filter_checks(view, access='Available')))

    def test_unlock_expands_logic_but_does_not_skip_story_order(self):
        before = self.view()
        self.session.record_inventory([ReceivedItem(ITEM_IDS[PROGRESSIVE_CHAPTER], 1, 1, 1)])
        after = self.view()
        self.assertGreater(after.logic_total, before.logic_total)
        self.assertEqual(after.available, before.available)
        self.assertEqual(sum(c.unlocked for c in after.chapters), 3)
        self.assertFalse(any(r.available for r in after.checks if r.chapter == 2))

    def test_disconnected_and_unsynchronized_access_is_unknown(self):
        for connected, synced in ((False, True), (True, False)):
            view = snapshot(self.session, (), connected=connected, synchronized=synced)
            self.assertTrue(all(r.in_logic is None and r.available is None for r in view.checks))
            self.assertTrue(all(c.unlocked is None for c in view.chapters))
            self.assertEqual(filter_checks(view, access='Available'), ())
            self.assertTrue(all('—' in text for key, text, style in metrics(view) if key != 'total'))
        cached = replace(self.view(), connected=False)
        self.assertEqual(filter_checks(cached, access='Available'), ())
        self.assertEqual(filter_checks(cached, access='In logic'), ())
        self.assertIn('—', dict((key, text) for key, text, _ in metrics(cached))['chapters'])

    def test_access_filters_compose_with_search_and_category(self):
        for mission in range(3): self.session.complete_mission(mission)
        rows = filter_checks(self.view(), access='Available', category='Collectible', chapter=1, search='notice')
        self.assertEqual(len(rows), 1)
        self.assertIn('Drafting Notice', rows[0].name)
        self.assertEqual(filter_checks(self.view(), access='Locked', search='notice'), ())

    def test_disabled_categories_also_excluded_from_logic_and_chapter_totals(self):
        self.session = Session(self.folder.name, 'seed', 0, 1, 'run',
                               Config(mission_checks=False, chapter_checks=False))
        view = self.view()
        self.assertEqual(view.logic_total, 10)
        self.assertEqual(view.available, 0)
        self.assertEqual(view.chapters[0].total, 0)
        self.assertEqual(sum(c.total for c in view.chapters), 140)

    def test_completed_logic_counter_turns_green_using_only_server_acknowledgements(self):
        initial = self.view()
        checked = {r.id for r in initial.checks if r.in_logic}
        view = self.view(checked)
        labels = {key: (text, style) for key, text, style in metrics(view)}
        self.assertEqual(labels['logic'], ('Checks in logic: 17/17', 'Complete'))
        self.assertEqual(labels['total'][1], 'Total')
        self.assertEqual(view.available, 0)

    def test_campaign_contains_every_enabled_check_once_under_owning_mission(self):
        rows = campaign_missions(self.view())
        self.assertEqual(len(rows), 29)
        ids = [c.id for row in rows for c in row.checks]
        self.assertEqual(len(ids), 181)
        self.assertEqual(len(set(ids)), 181)
        self.assertIn(19712001, {c.id for c in rows[4].checks})  # Quarantine Zone ends in The Cargo.
        self.assertEqual({c.id for c in rows[3].checks if 'Drafting' in c.name}, {19713001})
        self.assertEqual([key for key, _, _ in metrics(self.view())], ['total', 'logic', 'chapters'])

    def test_beaten_mission_keeps_missing_collectibles_visible(self):
        for mission in range(4): self.session.complete_mission(mission)
        view = self.view(self.session.earned_checks)
        full = campaign_missions(view)[3]
        filtered = next(r for r in campaign_missions(view, hide_completed=True) if r.index == 3)
        self.assertEqual((full.status, full.confirmed, full.total), ('Available', 1, 5))
        self.assertEqual((filtered.confirmed, filtered.total), (1, 5))
        self.assertEqual(len(filtered.checks), 4)
        self.assertTrue(all(c.category == 'collectible' for c in filtered.checks))
        acknowledged = {c.id for c in full.checks} | self.session.earned_checks
        self.assertEqual(campaign_missions(self.view(acknowledged))[3].status, 'Complete')
        self.assertFalse(any(r.index == 3 for r in campaign_missions(self.view(acknowledged), hide_completed=True)))

    def test_campaign_filters_keep_parent_totals_and_pending_checks(self):
        self.session.complete_mission(0)
        view = self.view({19711000})
        rows = campaign_missions(view, hide_completed=True, categories=('chapter',))
        self.assertEqual((rows[0].status, rows[0].confirmed, rows[0].total), ('Pending sync', 1, 2))
        self.assertEqual(rows[0].checks[0].status, 'Awaiting server')
        found = campaign_missions(view, search=' DRAFTING ', categories=('collectible',))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].index, 3)
        self.assertEqual(len(found[0].checks), 1)
        self.assertEqual(found[0].total, 5)
        self.assertEqual(len(campaign_missions(view, search='quarantine zone')), 4)
        self.assertEqual(campaign_missions(view, categories=()), ())

    def test_campaign_cached_access_goes_unknown_but_confirmed_progress_remains(self):
        view = replace(self.view({19711000, 19712000}), connected=False)
        rows = campaign_missions(view)
        self.assertEqual(rows[0].status, 'Complete')
        self.assertTrue(all(r.status == 'Unknown' for r in rows[1:]))
        self.assertTrue(all(check_status(view, c)[0] == 'Unknown' for r in rows[1:] for c in r.checks))

    def test_campaign_without_mission_checks_still_shows_empty_mission_access(self):
        self.session = Session(self.folder.name, 'seed', 0, 1, 'run', Config(mission_checks=False, chapter_checks=False))
        rows = campaign_missions(self.view())
        self.assertEqual(len(rows), 29)
        self.assertEqual((rows[0].status, rows[0].total), ('Available', 0))
        self.assertEqual(sum(r.total for r in rows), 140)
