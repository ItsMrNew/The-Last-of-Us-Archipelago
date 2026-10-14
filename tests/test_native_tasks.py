import unittest

from tlou_ap.catalog import MISSIONS
from tlou_ap.native.tasks import MOVIE_TASK, STORY_END, mission_difficulties


class TaskInterpretationTests(unittest.TestCase):
    def fixture(self):
        nodes = []
        for mission in MISSIONS:
            nodes.append({'sid': int(mission['task_sid'], 16), 'difficulty': 2, 'script': 1, 'type_sid': 7})
            nodes.append({'sid': mission['index'] + 1, 'difficulty': 2, 'script': 1, 'type_sid': 7})
        nodes.append({'sid': STORY_END, 'difficulty': -1, 'script': 1, 'type_sid': 7})
        return nodes

    def test_requires_all_relevant_tasks_and_excludes_end_sentinel(self):
        nodes = self.fixture()
        nodes[7]['difficulty'] = -1
        result = mission_difficulties(nodes)
        self.assertEqual(result[3], -1)
        self.assertEqual(result[4], 2)
        self.assertEqual(result[-1], 2)

    def test_later_movie_and_unscripted_tasks_do_not_block(self):
        nodes = self.fixture()
        nodes[1].update(difficulty=-1, type_sid=MOVIE_TASK)
        nodes[3].update(difficulty=-1, script=0)
        self.assertEqual(mission_difficulties(nodes)[:2], [2, 2])
        nodes[0].update(difficulty=-1, script=0)
        self.assertEqual(mission_difficulties(nodes)[0], -1)

    def test_invalid_cache_fails_closed(self):
        nodes = self.fixture()
        with self.assertRaises(ValueError):
            mission_difficulties(nodes[:-1])
        with self.assertRaises(ValueError):
            mission_difficulties(nodes + [nodes[0]])
        nodes[0]['difficulty'] = 900
        with self.assertRaises(ValueError):
            mission_difficulties(nodes)


if __name__ == '__main__':
    unittest.main()
