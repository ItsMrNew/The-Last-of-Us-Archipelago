from dataclasses import dataclass
from Options import Choice, DefaultOnToggle, DeathLink, PerGameCommonOptions, Range


class StartingChapters(Range):
    """Number of consecutive chapters available initially, counting Hometown.

    Two opens Hometown and The Quarantine Zone. Each received Progressive Chapter
    Unlock permits the next chapter, while missions retain normal story order.
    """
    display_name = 'Starting Chapters'
    range_start = 1
    range_end = 12
    default = 2


class MissionChecks(DefaultOnToggle):
    """One check for completing each of the 29 main-story subchapters."""
    display_name = 'Mission Completion Checks'


class ChapterChecks(DefaultOnToggle):
    """One additional check after completing every mission in each main chapter."""
    display_name = 'Chapter Completion Checks'


class CollectibleChecks(DefaultOnToggle):
    """Checks for artifacts, Firefly pendants, training manuals and comics.

    Development catalog: includes automatic story acquisitions and inventory
    variants. Full playthrough validation is outstanding. Left Behind, tools,
    conversations, safes, shiv doors and workbenches are excluded.
    """
    display_name = 'Collectible Checks'


class AirhornTrapPercentage(Range):
    """Percentage of non-progression rewards replaced by Airhorn Traps.

    Zero disables traps. Chapter unlock items are never replaced.
    """
    display_name = 'Airhorn Trap Percentage'
    range_start = 0
    range_end = 100
    default = 10


class AirhornMode(Choice):
    """One blast, or repeated noise every five seconds of playable gameplay.

    Enemies use their normal hearing and searching behavior. Ending a trap
    stops the noise; it does not make enemies forget the player.
    """
    display_name = 'Airhorn Mode'
    option_single_blast = 0
    option_timed = 1
    default = 0


class AirhornDuration(Range):
    """Active gameplay seconds for timed Airhorns. Ignored in single-blast mode.

    Menus, loading, cutscenes and locked missions pause the timer.
    Timed Airhorns stack. Death clears the active stack.
    """
    display_name = 'Airhorn Duration'
    range_start = 30
    range_end = 120
    default = 60


class ResourceSupplies(DefaultOnToggle):
    """Include Crafting Cache (one full unit of each material), Workbench Parts
    (25 parts), and Supplement Stash (10 supplements) among supply rewards.
    Inventory caps apply; rewards wait for gameplay and available space.
    """
    display_name = 'Resource Supplies'


class ShakyHandsPercentage(Range):
    """Percentage of non-progression rewards replaced with 30-second Shaky Hands.
    All trap percentages together must be at most 100. Playable time only.
    """
    display_name = 'Shaky Hands Percentage'
    range_start = 0
    range_end = 100
    default = 0


class FaultyFlashlightPercentage(ShakyHandsPercentage):
    """Percentage of non-progression rewards replaced with a 30-second faulty
    flashlight. Normal lighting returns afterward. Playable time only.
    """
    display_name = 'Faulty Flashlight Percentage'


class ProgressiveTools(Range):
    """Bonus tool upgrades in the item pool. Each raises tool level by one, up to 5.

    Normal toolboxes remain available. Weapon parts are still needed to buy
    workbench upgrades. Useful items; never required by mission/check logic.
    """
    display_name = 'Progressive Tools'
    range_start = 0
    range_end = 5
    default = 5


@dataclass
class TLOUOptions(PerGameCommonOptions):
    starting_chapters: StartingChapters
    mission_checks: MissionChecks
    chapter_checks: ChapterChecks
    collectible_checks: CollectibleChecks
    death_link: DeathLink
    airhorn_trap_percentage: AirhornTrapPercentage
    airhorn_mode: AirhornMode
    airhorn_duration: AirhornDuration
    resource_supplies: ResourceSupplies
    shaky_hands_percentage: ShakyHandsPercentage
    faulty_flashlight_percentage: FaultyFlashlightPercentage
    progressive_tools: ProgressiveTools
