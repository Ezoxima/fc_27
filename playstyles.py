"""
Table de correspondance id EA -> nom des PlayStyles / PlayStyles+.

Extraite du bundle JS public de fut.gg (assets.fut.gg/ts/assets/index-*.js,
objet "PLAY_STYLE_LABELS") et vérifiée sur des cartes connues (ex: Ronaldo
Icon FC 27 : playStyleEaIds=[0,37,8,16,20,22] -> Finesse Shot, Game Changer,
Tiki Taka, Technical, Trickster, Quick Step - correspond exactement aux
PlayStyles normaux affiches sur Futbin/fut.gg pour cette carte).

Ces ids sont directement presents dans les champs "playStyleEaIds" (PlayStyles
normaux) et "playStylePlusEaIds" (PlayStyles+) de l'API
https://www.fut.gg/api/fut/players/v2/27/ - pas besoin de requete
supplementaire par joueur pour les resoudre.
"""

PLAY_STYLE_NAMES: dict[int, str] = {
    0: "Finesse Shot",
    1: "Chip Shot",
    2: "Power Shot",
    3: "Dead Ball",
    4: "Power Header",
    5: "Incisive Pass",
    6: "Pinged Pass",
    7: "Long Ball",
    8: "Tiki Taka",
    9: "Whipped Pass",
    10: "Jockey",
    11: "Block",
    12: "Intercept",
    13: "Anticipate",
    14: "Slide Tackle",
    15: "Bruiser",
    16: "Technical",
    17: "Rapid",
    18: "Flair",
    19: "First Touch",
    20: "Trickster",
    21: "Press Proven",
    22: "Quick Step",
    23: "Relentless",
    24: "Trivela",
    25: "Acrobatic",
    26: "Long Throw",
    27: "Aerial",
    28: "Far Throw",
    29: "Footwork",
    30: "Cross Claimer",
    31: "Rush Out",
    32: "Far Reach",
    33: "Deflector",
    34: "Low Driven Shot",
    35: "Aerial Fortress",
    36: "Enforcer",
    37: "Game Changer",
    38: "Inventive",
    39: "Precision Header",
}


def resolve_playstyles(ea_ids: list[int]) -> list[str]:
    return [PLAY_STYLE_NAMES.get(i, f"Unknown({i})") for i in ea_ids]
