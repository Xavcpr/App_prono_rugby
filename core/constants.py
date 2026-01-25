COMPETITION_RULES = {
    "TOP14": {
        "type": "league",
        "positions": 14,
        "pools": None,
        "has_best_scorer": True,
        "has_best_kicker": True,
        "winner_is_first": False,
    },
    "6NATIONS": {
        "type": "league",
        "positions": 6,
        "pools": None,
        "has_best_scorer": False,
        "has_best_kicker": False,
        "winner_is_first": True,
    },
    "CHAMPIONS_CUP": {
        "type": "groups",
        "positions": 6,
        "pools": ["A", "B", "C", "D"],
        "has_best_scorer": True,
        "has_best_kicker": True,
        "winner_is_first": False,
    },
}
