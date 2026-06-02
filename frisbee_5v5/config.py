from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from typing import Literal


Team = Literal["blue", "red"]


@dataclass(frozen=True)
class FieldConfig:
    width: int = 202
    height: int = 74
    cell_size_m: float = 0.5
    left_end_zone_x_max: int = 36
    right_end_zone_x_min: int = 165

    @property
    def x_max(self) -> int:
        return self.width - 1

    @property
    def y_max(self) -> int:
        return self.height - 1

    @property
    def central_zone_x_min(self) -> int:
        return self.left_end_zone_x_max + 1

    @property
    def central_zone_x_max(self) -> int:
        return self.right_end_zone_x_min - 1

    def in_bounds(self, x: float, y: float) -> bool:
        return 0 <= x <= self.x_max and 0 <= y <= self.y_max

    def clamp_cell(self, x: float, y: float) -> tuple[int, int]:
        return (
            min(max(int(round(x)), 0), self.x_max),
            min(max(int(round(y)), 0), self.y_max),
        )

    def attacking_end_zone(self, team: Team) -> tuple[int, int]:
        if team == "blue":
            return self.right_end_zone_x_min, self.x_max
        return 0, self.left_end_zone_x_max

    def is_score_cell(self, team: Team, x: int) -> bool:
        x_min, x_max = self.attacking_end_zone(team)
        return x_min <= x <= x_max

    def nearest_in_bounds(self, x: float, y: float) -> tuple[int, int]:
        return (
            min(max(int(round(x)), 0), self.x_max),
            min(max(int(round(y)), 0), self.y_max),
        )

    def nearest_central_zone_cell(self, x: float, y: float) -> tuple[int, int]:
        return (
            min(max(int(round(x)), self.central_zone_x_min), self.central_zone_x_max),
            min(max(int(round(y)), 0), self.y_max),
        )


@dataclass(frozen=True)
class RuleConfig:
    frame_duration_seconds: int = 1
    catch_block_radius_cells: float = 2.0
    marking_radius_cells: float = 2.0
    stall_limit: int = 5
    max_disc_speed_cells_per_frame: float = 30.0
    stop_at_first_score: bool = True
    restrict_disc_contest_to_intended_pair: bool = False


@dataclass(frozen=True)
class PlayerSpec:
    player_id: str
    team: Team
    captain: bool
    height: int
    speed: int
    throw: int

    @property
    def max_move_cells(self) -> int:
        return max_move_cells_for_speed(self.speed)

    def as_dict(self) -> dict[str, object]:
        return {
            "team": self.team,
            "captain": self.captain,
            "height": self.height,
            "speed": self.speed,
            "throw": self.throw,
            "max_move_cells": self.max_move_cells,
        }


def max_move_cells_for_speed(speed: int) -> int:
    if speed <= 20:
        return 6
    if speed <= 40:
        return 8
    if speed <= 60:
        return 10
    if speed <= 80:
        return 12
    return 14


def other_team(team: Team) -> Team:
    return "red" if team == "blue" else "blue"


ROSTER: dict[str, PlayerSpec] = {
    "blue_1": PlayerSpec("blue_1", "blue", True, height=58, speed=63, throw=88),
    "blue_2": PlayerSpec("blue_2", "blue", False, height=82, speed=71, throw=54),
    "blue_3": PlayerSpec("blue_3", "blue", False, height=74, speed=86, throw=48),
    "blue_4": PlayerSpec("blue_4", "blue", False, height=66, speed=78, throw=70),
    "blue_5": PlayerSpec("blue_5", "blue", False, height=91, speed=55, throw=42),
    "red_1": PlayerSpec("red_1", "red", True, height=61, speed=68, throw=84),
    "red_2": PlayerSpec("red_2", "red", False, height=77, speed=74, throw=52),
    "red_3": PlayerSpec("red_3", "red", False, height=69, speed=91, throw=46),
    "red_4": PlayerSpec("red_4", "red", False, height=73, speed=72, throw=68),
    "red_5": PlayerSpec("red_5", "red", False, height=94, speed=50, throw=40),
}


def roster_with_throw_score(throw_score: int) -> dict[str, PlayerSpec]:
    score = min(max(int(throw_score), 1), 100)
    return {player_id: replace(spec, throw=score) for player_id, spec in ROSTER.items()}


FIXED_MATCHUPS: dict[str, str] = {
    "blue_1": "red_1",
    "blue_2": "red_2",
    "blue_3": "red_3",
    "blue_4": "red_4",
    "blue_5": "red_5",
}


INITIAL_POSITIONS: dict[str, tuple[int, int]] = {
    "blue_1": (42, 37),
    "blue_2": (54, 18),
    "blue_3": (58, 31),
    "blue_4": (56, 47),
    "blue_5": (52, 59),
    "red_1": (44, 37),
    "red_2": (53, 20),
    "red_3": (57, 33),
    "red_4": (55, 49),
    "red_5": (51, 61),
}


def matchup_for(player_id: str, matchups: dict[str, str] | None = None) -> str:
    matchup_table = matchups or FIXED_MATCHUPS
    if player_id in matchup_table:
        return matchup_table[player_id]
    for blue_id, red_id in matchup_table.items():
        if red_id == player_id:
            return blue_id
    raise KeyError(f"Unknown matchup for player {player_id!r}.")


@dataclass(frozen=True)
class GameConfig:
    field: FieldConfig = dataclass_field(default_factory=FieldConfig)
    rules: RuleConfig = dataclass_field(default_factory=RuleConfig)
    roster: dict[str, PlayerSpec] | None = None
    fixed_matchups: dict[str, str] | None = None
    initial_positions: dict[str, tuple[int, int]] | None = None
    initial_possession_team: Team = "blue"
    initial_holder: str = "blue_1"

    def resolved_roster(self) -> dict[str, PlayerSpec]:
        return self.roster or ROSTER

    def resolved_matchups(self) -> dict[str, str]:
        return self.fixed_matchups or FIXED_MATCHUPS

    def resolved_initial_positions(self) -> dict[str, tuple[int, int]]:
        return self.initial_positions or INITIAL_POSITIONS
