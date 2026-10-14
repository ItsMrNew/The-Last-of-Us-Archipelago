"""Suggested pickup route for display only; never changes AP/native identifiers.

Route reference (Remake):
https://www.powerpyx.com/the-last-of-us-ps5-remake-collectibles-guide/
Numbers are our native catalog indexes, not the guide's trophy numbering.
Nearby optional pickups can be visited in a different order. Automatic starting
inventory comes first, with catalog order breaking ties within that inventory.
"""
from .catalog import BASE_ID


# One tuple per mission, mixing artifacts, pendants, manuals and comics.
MISSION_COLLECTIBLES = (
    (),  # Prologue
    (),  # 20 Years Later
    (5, 6, 84, 2, 85),  # Beyond the Wall
    (1, 0, 4, 3),  # The Slums
    (86,),  # The Cargo
    (7, 13),  # Outside
    (8, 87, 9, 10, 15),  # Downtown
    (12, 88),  # Museum
    (11, 89, 14, 90),  # The Capitol Building
    (22, 91, 21, 23, 16),  # The Woods
    (19, 24, 116, 25, 92),  # Safehouse
    (26, 93, 20),  # Graveyard
    (17, 18),  # High School Escape
    (27, 128, 41, 114, 38, 126, 29, 32, 94, 28, 30, 33, 35, 34),  # Alone and Forsaken
    (42, 117, 43, 131, 96, 118),  # Hotel Lobby
    (37, 36, 31, 39),  # Financial District
    (120, 135, 98, 40),  # Escape the City
    (136, 44, 99, 97, 45, 100, 46, 122, 49, 48, 50),  # Sewers
    (53, 52, 119, 51, 127, 47, 112),  # Suburbs
    (130, 54, 124, 101, 55),  # Hydroelectric Dam
    (102, 137),  # Ranch House
    (132, 56, 103, 57, 104, 115, 60, 59, 95, 58, 105),  # Go Big Horns
    (121, 62, 61, 63, 106, 64),  # Science Building
    (65, 66, 67, 68, 69, 71, 73, 74, 78, 129, 107),  # The Hunt
    (108, 133, 72, 125, 70),  # Cabin Resort
    (76, 109, 75, 134, 110, 77, 79),  # Highway Exit
    (111, 123, 138),  # Underground Tunnel
    (80, 81, 113, 83, 82),  # The Hospital
    (139,),  # Epilogue
)

_RANK = {BASE_ID + 3000 + index: rank
         for indexes in MISSION_COLLECTIBLES for rank, index in enumerate(indexes)}


def check_order(check):
    """Mission completion first, route-ordered collectibles, chapter completion last."""
    return ({'mission': 0, 'collectible': 1, 'chapter': 2}[check.category],
            _RANK.get(check.id, check.id), check.id)
