from BaseClasses import Item, ItemClassification, Location, Region, Tutorial
from worlds.AutoWorld import WebWorld, World

from .catalog import (GAME, CHAPTERS, MISSIONS, ITEM_IDS, LOCATION_IDS, PROGRESSIVE_CHAPTER,
                      AIRHORN, SUPPLIES, PROGRESSIVE_TOOLS, RESOURCE_SUPPLIES, TIMED_TRAPS, Config, completed_event)
from .options import TLOUOptions


class TLOUItem(Item):
    game = GAME


class TLOULocation(Location):
    game = GAME


class TLOUWeb(WebWorld):
    tutorials = [Tutorial('Setup guide', 'Windows client installation and alpha limitations.', 'English',
                          'setup_en.md', 'setup/en', [])]


class TLOUWorld(World):
    """Main-story progressive chapters for the experimental native Windows client."""
    game = GAME
    web = TLOUWeb()
    options_dataclass = TLOUOptions
    options: TLOUOptions
    required_client_version = (0, 6, 7)
    item_name_to_id = ITEM_IDS
    location_name_to_id = LOCATION_IDS
    item_name_groups = {'Supplies': set(SUPPLIES), 'Traps': {AIRHORN, *TIMED_TRAPS}, 'Tools': {PROGRESSIVE_TOOLS}}

    def generate_early(self):
        self.config = Config(self.options.starting_chapters.value, bool(self.options.mission_checks),
                             bool(self.options.chapter_checks), bool(self.options.collectible_checks),
                             bool(self.options.death_link), self.options.airhorn_trap_percentage.value,
                             self.options.airhorn_mode.current_key, self.options.airhorn_duration.value,
                             bool(self.options.resource_supplies), self.options.shaky_hands_percentage.value,
                             self.options.faulty_flashlight_percentage.value, self.options.progressive_tools.value)

    def create_regions(self):
        menu = Region('Menu', self.player, self.multiworld)
        self.multiworld.regions.append(menu)
        previous = menu
        regions = {}
        for mission in MISSIONS:
            index = mission['index']
            region = Region(f"Mission {index + 1}: {mission['name']}", self.player, self.multiworld)
            self.multiworld.regions.append(region)
            required = max(0, mission['chapter'] + 1 - self.config.starting_chapters)
            previous.connect(region, rule=lambda state, n=required, i=index:
                             state.has(PROGRESSIVE_CHAPTER, self.player, n)
                             and (i == 0 or state.has(completed_event(i - 1), self.player)))
            event = TLOULocation(self.player, completed_event(index), None, region)
            event.place_locked_item(TLOUItem(completed_event(index), ItemClassification.progression, None, self.player))
            region.locations.append(event)
            regions[index] = region
            previous = region
        for check in self.config.active_checks:
            mission = check.mission
            if mission is None:
                mission = max(m['index'] for m in MISSIONS if m['chapter'] == check.chapter)
            region = regions[mission]
            location = TLOULocation(self.player, check.name, check.id, region)
            if check.category in ('chapter', 'mission'):
                location.access_rule = lambda state, i=mission: state.has(completed_event(i), self.player)
            region.locations.append(location)
        self.multiworld.completion_condition[self.player] = lambda state: state.has(
            completed_event(len(MISSIONS) - 1), self.player)

    def create_items(self):
        # Common start_inventory_from_pool is handled by AP after pool creation.
        permits = len(CHAPTERS) - self.config.starting_chapters
        items = [self.create_item(PROGRESSIVE_CHAPTER) for _ in range(permits)]
        supplies = [name for name in SUPPLIES if self.config.resource_supplies or name not in RESOURCE_SUPPLIES]
        self.random.shuffle(supplies)
        tool_count = min(self.config.progressive_tools, len(self.config.active_checks) - permits)
        items.extend(self.create_item(PROGRESSIVE_TOOLS) for _ in range(tool_count))
        filler_count = len(self.config.active_checks) - permits - tool_count
        traps = 0
        for name, percentage in ((AIRHORN, self.config.airhorn_trap_percentage),
                                 (TIMED_TRAPS[0], self.config.shaky_hands_percentage),
                                 (TIMED_TRAPS[1], self.config.faulty_flashlight_percentage)):
            count = filler_count * percentage // 100
            traps += count
            items.extend(self.create_item(name) for _ in range(count))
        items.extend(self.create_item(supplies[i % len(supplies)])
                     for i in range(filler_count - traps))
        self.multiworld.itempool += items

    def create_item(self, name):
        classification = (ItemClassification.progression if name == PROGRESSIVE_CHAPTER else
                          ItemClassification.trap if name in (AIRHORN, *TIMED_TRAPS) else
                          ItemClassification.useful if name in (*RESOURCE_SUPPLIES, PROGRESSIVE_TOOLS) else ItemClassification.filler)
        return TLOUItem(name, classification, ITEM_IDS[name], self.player)

    def get_filler_item_name(self):
        return self.random.choice([name for name in SUPPLIES
                                   if self.config.resource_supplies or name not in RESOURCE_SUPPLIES])

    def fill_slot_data(self):
        return self.config.slot_data()
