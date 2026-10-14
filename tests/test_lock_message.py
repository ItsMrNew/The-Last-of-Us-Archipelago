import unittest
from tlou_ap.catalog import PROGRESSIVE_CHAPTER
from tlou_ap.notifications import mission_lock_toast


class LockMessageTests(unittest.TestCase):
    def test_locked_chapter_identifies_unlock_and_uses_progression_colour(self):
        toast = mission_lock_toast('The Slums')
        self.assertIn(PROGRESSIVE_CHAPTER, toast.detail)
        self.assertEqual(toast.colour, '#AF99EF')
        self.assertIn('pause menu', toast.location)

    def test_existing_chapter_access_does_not_request_another_unlock(self):
        toast = mission_lock_toast('The Slums', chapter_unlocked=True)
        self.assertIn('previous mission', toast.detail)
        self.assertNotIn(PROGRESSIVE_CHAPTER, toast.detail)

    def test_connection_and_save_errors_do_not_request_an_unlock_item(self):
        for kwargs in ({'connected':False}, {'compatible':False}):
            with self.subTest(kwargs=kwargs):
                self.assertNotIn(PROGRESSIVE_CHAPTER, mission_lock_toast('The Slums', **kwargs).detail)
