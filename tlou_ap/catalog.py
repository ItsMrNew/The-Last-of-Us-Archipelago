"""Stable Archipelago IDs, separate from build-specific game identifiers."""
from dataclasses import dataclass
import json
from importlib.resources import files

GAME = 'The Last of Us Part I'
SCHEMA_VERSION = 1
BASE_ID = 19710000
PROGRESSIVE_CHAPTER = 'Progressive Chapter Unlock'
RESOURCE_SUPPLIES = ('Crafting Cache', 'Workbench Parts', 'Supplement Stash')
SUPPLIES = ('Ammo Supply', 'Health Kit', 'Shiv') + RESOURCE_SUPPLIES
TIMED_TRAPS = ('Shaky Hands', 'Faulty Flashlight')
PROGRESSIVE_TOOLS = 'Progressive Tools'
DELIVERABLES = (*SUPPLIES, PROGRESSIVE_TOOLS)
AIRHORN = 'Airhorn Trap'
ITEM_IDS = {PROGRESSIVE_CHAPTER: BASE_ID, 'Ammo Supply': BASE_ID + 1, 'Health Kit': BASE_ID + 2,
            'Shiv': BASE_ID + 3, AIRHORN: BASE_ID + 4,
            PROGRESSIVE_TOOLS: BASE_ID + 5,
            **{name: BASE_ID + 6 + i for i, name in enumerate(RESOURCE_SUPPLIES + TIMED_TRAPS)}}
DATA = json.loads(files(__package__).joinpath('data/catalog.json').read_text(encoding='utf-8'))
CHAPTERS = tuple(DATA['chapters'])
MISSIONS = tuple(DATA['missions'])
COLLECTIBLES = tuple(DATA['collectibles'])


@dataclass(frozen=True)
class Check:
    id: int
    name: str
    category: str
    chapter: int
    mission: int | None
    native_index: int


def mission_check(mission):
    return Check(BASE_ID + 1000 + mission['index'],
                 f"{CHAPTERS[mission['chapter']]['name']} - {mission['name']} - Mission Complete",
                 'mission', mission['chapter'], mission['index'], mission['index'])


def chapter_check(chapter):
    return Check(BASE_ID + 2000 + chapter['index'], f"{chapter['name']} - Chapter Complete",
                 'chapter', chapter['index'], None, chapter['index'])


def collectible_check(collectible):
    mission = MISSIONS[collectible['mission']]
    chapter = CHAPTERS[mission['chapter']]
    return Check(BASE_ID + 3000 + collectible['index'],
                 f"{chapter['name']} - {mission['name']} - {collectible['name']}",
                 'collectible', chapter['index'], mission['index'], collectible['index'])


CHECKS = tuple([*(mission_check(m) for m in MISSIONS),
                *(chapter_check(c) for c in CHAPTERS),
                *(collectible_check(c) for c in COLLECTIBLES)])
CHECK_BY_ID = {check.id: check for check in CHECKS}
LOCATION_IDS = {check.name: check.id for check in CHECKS}


@dataclass(frozen=True)
class Config:
    starting_chapters: int = 2
    mission_checks: bool = True
    chapter_checks: bool = True
    collectible_checks: bool = True
    death_link: bool = False
    airhorn_trap_percentage: int = 0
    airhorn_mode: str = 'single_blast'
    airhorn_duration: int = 60
    resource_supplies: bool = False
    shaky_hands_percentage: int = 0
    faulty_flashlight_percentage: int = 0
    progressive_tools: int = 0

    def __post_init__(self):
        if type(self.progressive_tools) is not int or not 0 <= self.progressive_tools <= 5:
            raise ValueError("progressive_tools must be from 0 to 5")
        if type(self.airhorn_trap_percentage) is not int or not 0 <= self.airhorn_trap_percentage <= 100:
            raise ValueError('airhorn_trap_percentage must be from 0 to 100')
        for name in ('shaky_hands_percentage', 'faulty_flashlight_percentage'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError(f'{name} must be from 0 to 100')
        if self.airhorn_trap_percentage + self.shaky_hands_percentage + self.faulty_flashlight_percentage > 100:
            raise ValueError('Combined trap percentages must not exceed 100')
        if type(self.resource_supplies) is not bool:
            raise ValueError('resource_supplies must be a boolean')
        if self.airhorn_mode not in ('single_blast', 'timed'):
            raise ValueError('Unsupported Airhorn mode')
        if type(self.airhorn_duration) is not int or not 30 <= self.airhorn_duration <= 120:
            raise ValueError('airhorn_duration must be from 30 to 120 seconds')
        if type(self.starting_chapters) is not int or not 1 <= self.starting_chapters <= 12:
            raise ValueError('starting_chapters must be from 1 to 12')
        for field in ('mission_checks', 'chapter_checks', 'collectible_checks', 'death_link'):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f'{field} must be a boolean')
        if not self.active_checks:
            raise ValueError('Enable at least one check category')
        if not any(check.chapter < self.starting_chapters for check in self.active_checks):
            raise ValueError('Starting chapters contain no checks; enable completion checks or start with at least two chapters')

    @property
    def active_checks(self):
        return tuple(check for check in CHECKS if getattr(self, f'{check.category}_checks'))

    def slot_data(self):
        data = {'schema_version': SCHEMA_VERSION, 'catalog_version': 1, 'goal': 'complete_story',
                'starting_chapters': self.starting_chapters, 'mission_checks': self.mission_checks,
                'chapter_checks': self.chapter_checks, 'collectible_checks': self.collectible_checks,
                'chapter_access': 'progressive_story_order', 'native_adapter_required': True}
        # Preserve existing seeds and their saved session identities exactly.
        if self.death_link:
            data.update(schema_version=2, death_link=True)
        if self.airhorn_trap_percentage:
            data.update(schema_version=3, airhorn_trap_percentage=self.airhorn_trap_percentage,
                        airhorn_mode=self.airhorn_mode, airhorn_duration=self.airhorn_duration)
        if self.resource_supplies or self.shaky_hands_percentage or self.faulty_flashlight_percentage:
            data.update(schema_version=4, resource_supplies=self.resource_supplies,
                        shaky_hands_percentage=self.shaky_hands_percentage,
                        faulty_flashlight_percentage=self.faulty_flashlight_percentage)
        if self.progressive_tools:
            data.update(schema_version=4, progressive_tools=self.progressive_tools)
        return data

    @classmethod
    def from_slot_data(cls, data, locations):
        if not isinstance(data, dict):
            raise ValueError('Missing TLOU slot data')
        config = cls(progressive_tools=data.get('progressive_tools', 0), resource_supplies=data.get('resource_supplies', False),
                     shaky_hands_percentage=data.get('shaky_hands_percentage', 0),
                     faulty_flashlight_percentage=data.get('faulty_flashlight_percentage', 0),
                     death_link=data.get('death_link', False),
                     airhorn_trap_percentage=data.get('airhorn_trap_percentage', 0),
                     airhorn_mode=data.get('airhorn_mode', 'single_blast'),
                     airhorn_duration=data.get('airhorn_duration', 60), **{field: data[field] for field in
                        ('starting_chapters', 'mission_checks', 'chapter_checks', 'collectible_checks')})
        if data != config.slot_data():
            raise ValueError('Unsupported TLOU slot schema or options')
        if set(locations) != {check.id for check in config.active_checks}:
            raise ValueError('Room location catalog does not match the client')
        return config


def unlocked_chapters(config, received_item_ids):
    count = config.starting_chapters + sum(item == ITEM_IDS[PROGRESSIVE_CHAPTER] for item in received_item_ids)
    return tuple(range(min(len(CHAPTERS), count)))


def completed_event(mission_index):
    return f"Completed: {MISSIONS[mission_index]['name']}"
