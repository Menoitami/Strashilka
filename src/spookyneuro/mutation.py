"""Deterministic staging for a neural surface with independently rigged anatomy modules."""

import random

FAMILIES = ("human", "many_arms", "crawler", "choir")
FAMILY_DETAILS = (
    "gaunt almost human torso, long taut neck, subtly unequal shoulders",
    "knotted shoulder muscles, swollen scapulae, layered sinewy tissue",
    "broad hunched torso, elongated tendons, compact skull, leathery skin",
    "folded neck tissue, asymmetrical skull, deeply furrowed pale facial skin",
)


def face_traits(seed):
    rng = random.Random(int(seed))
    return [round(rng.uniform(-1, 1), 4) for _ in range(4)]


def face_detail(seed):
    jaw, eyes, asymmetry, skull = face_traits(seed)
    return ", ".join((
        "long slack lower jaw" if jaw > 0 else "short tense receding jaw",
        "widely spaced recessed eyes" if eyes > 0 else "narrow close set eyes",
        "uneven cheeks and crooked mouth" if abs(asymmetry) > .3 else "almost symmetrical familiar face",
        "elongated high cranium" if skull > 0 else "compact heavy brow",
    ))


def mutation_plan(seed, sequence):
    """The core stays walkable; module topology changes only after a whole packet arrives."""
    rng = random.Random(int(seed))
    family = FAMILIES[int(sequence) % len(FAMILIES)]
    modules = []

    def add(slot, kind, bone, rotation, scale=1.0):
        modules.append({"slot": slot, "kind": kind, "bone": bone,
                        "rotation": rotation, "scale": round(scale, 3),
                        "phase": round(rng.uniform(0, 6.28), 3)})

    if family == "many_arms":
        add("left", "arm", "ShoulderL", [0, 0, 75], 1.05)
        add("right", "arm", "ShoulderR", [15, 0, -70], 1.15)
        add("spine", "tendril", "Chest", [-85, 20, 15], 1.0)
    elif family == "crawler":
        add("left", "arm", "ShoulderL", [162, 0, 16], 1.9)
        add("right", "arm", "ShoulderR", [162, 0, -16], 1.9)
    elif family == "choir":
        add("left", "head", "ShoulderL", [0, 5, 32], .9)
        add("right", "head", "ShoulderR", [0, -10, -28], 1.05)
        add("spine", "tendril", "Chest", [-80, 0, 0], .85)
    return {"schema": 1, "family": family, "seed": int(seed), "modules": modules,
            "face": face_traits(seed), "focus_bone": "ShoulderL" if modules else "Head",
            "timing": {"anticipation": .22, "change": .8, "settle": .28, "hold": 2.0},
            "body_detail": FAMILY_DETAILS[FAMILIES.index(family)]}
