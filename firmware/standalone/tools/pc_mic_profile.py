"""Private local binary helper protocol. No recording, file writes or network."""

import json
import math
import subprocess
import zlib


class EnrollmentError(ValueError):
    pass


class CalibrationError(EnrollmentError):
    def __init__(self, reason, diagnostics):
        super().__init__(reason)
        self.diagnostics = diagnostics


def calibration_error(result):
    """Recognize only the bounded, numeric calibration failure protocol."""
    if result.returncode != 2 or result.stdout or not 0 < len(result.stderr) <= 1024:
        return None
    try:

        def distinct_fields(pairs):
            report = dict(pairs)
            if len(report) != len(pairs):
                raise ValueError
            return report

        report = json.loads(result.stderr, object_pairs_hook=distinct_fields)
        if set(report) != {
            "reason",
            "worst_wake_trial",
            "nearest_nonwake_trial",
            "worst_wake_distance_q8",
            "nearest_nonwake_distance_q8",
        }:
            return None
        reason = report.pop("reason")
        if reason not in {"calibration_not_separable", "calibration_threshold_out_of_range"}:
            return None
        for key, maximum in [("worst_wake_trial", 5), ("nearest_nonwake_trial", 10)]:
            if type(report[key]) is not int or not 1 <= report[key] <= maximum:
                return None
        for key in ["worst_wake_distance_q8", "nearest_nonwake_distance_q8"]:
            value = report[key]
            if (
                type(value) not in (int, float)
                or not 0 <= value <= 65535
                or not math.isfinite(value)
            ):
                return None
        worst, nearest = report["worst_wake_distance_q8"], report["nearest_nonwake_distance_q8"]
        overlap = worst >= nearest or nearest <= 0
        midpoint = (worst + nearest) * 0.5
        if (reason == "calibration_not_separable" and not overlap) or (
            reason == "calibration_threshold_out_of_range" and (overlap or 1 <= midpoint <= 65535)
        ):
            return None
        return CalibrationError(reason, report)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return None


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
    if mode == "--calibrate":
        failure = calibration_error(result)
        if failure is not None:
            raise failure
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
            or type(limit) is not int
            or limit != int.from_bytes(profile[5:7], "little")
        ):
            raise ValueError
        if distance is None:
            if score["accepted"]:
                raise ValueError
        elif (
            type(distance) not in (int, float)
            or not math.isfinite(distance)
            or distance < 0
            or score["accepted"] != (distance < limit)
        ):
            raise ValueError
        return score
    except (ValueError, TypeError, KeyError) as exc:
        raise EnrollmentError("invalid_helper_score") from exc
