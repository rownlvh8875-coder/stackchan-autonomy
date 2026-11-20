"""Private local binary helper protocol. No recording, file writes or network."""

import json
import math
import subprocess
import zlib


class EnrollmentError(ValueError):
    pass


def validate_profile(profile):
    if (
        not 843 <= len(profile) <= 2507
        or profile[:4] != b"SWK1"
        or not 1 <= profile[4] <= 3
        or len(profile) != 11 + profile[4] * 832
        or int.from_bytes(profile[5:7], "little") == 0
        or zlib.crc32(profile[:-4]) != int.from_bytes(profile[-4:], "little")
    ):
        raise EnrollmentError("invalid_profile")
    return profile


def helper(probe, mode, body):
    try:
        result = subprocess.run(
            [str(probe), mode, "-"], input=body, capture_output=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EnrollmentError("local_helper_unavailable") from exc
    if result.returncode != 0 or result.stderr or len(result.stdout) > 2507:
        raise EnrollmentError("local_helper_rejected")
    return result.stdout


def score_wav(probe, profile, wav):
    validate_profile(profile)
    if not 44 <= len(wav) <= 196608:
        raise EnrollmentError("invalid_wave")
    raw = helper(probe, "--score", len(profile).to_bytes(2, "big") + profile + wav)
    try:
        score = json.loads(raw)
        if set(score) != {"accepted", "distance_q8", "limit_q8"}:
            raise ValueError
        distance, limit = score["distance_q8"], score["limit_q8"]
        if (
            type(score["accepted"]) is not bool
            or type(distance) not in (int, float)
            or not math.isfinite(distance)
            or distance < 0
            or type(limit) is not int
            or limit != int.from_bytes(profile[5:7], "little")
            or score["accepted"] != (distance < limit)
        ):
            raise ValueError
        return score
    except (ValueError, TypeError, KeyError) as exc:
        raise EnrollmentError("invalid_helper_score") from exc
