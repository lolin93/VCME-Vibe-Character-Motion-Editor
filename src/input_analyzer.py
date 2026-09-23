from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class TextPlan:
    user_motion: str
    model_prompt: str
    negative_prompt: str
    action_phases: list[str]
    constraints: list[str]


def build_text_plan(user_motion: str) -> TextPlan:
    motion = user_motion.strip()
    if not motion:
        raise ValueError("Motion prompt cannot be empty.")

    action_phases = [
        "start from the original pose",
        "perform the requested action slowly with natural human timing",
        "avoid floating, broken joints, extreme limb bending, or unnatural speed",
        "return close to the original ending pose",
    ]
    constraints = [
        "keep the same person identity, face, clothing, body scale, and camera viewpoint",
        "keep the original scene and lighting consistent unless the mask allows editing",
        "hands should have clear palms and five separated fingers when visible",
        "motion should obey basic body balance and gravity",
    ]
    model_prompt = (
        "realistic video of the same person in the original scene. "
        f"The person should {motion}. "
        + " ".join(constraints)
    )
    negative_prompt = (
        "different person, changed clothes, changed background, CGI, 3D render, "
        "floating body, broken anatomy, twisted arm, extra fingers, fused fingers, "
        "missing hand, blurry hand, motion smear, duplicated body, unstable camera, "
        "kneeling, crouching, sitting, crawling, jumping, dancing, dance steps, "
        "moving feet during the wave, swaying torso, ghosting, dissolve, background drift"
    )
    return TextPlan(
        user_motion=motion,
        model_prompt=model_prompt,
        negative_prompt=negative_prompt,
        action_phases=action_phases,
        constraints=constraints,
    )


def text_plan_to_dict(plan: TextPlan) -> dict:
    return asdict(plan)
