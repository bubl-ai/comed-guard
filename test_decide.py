"""Plain-assert tests for the pure decision logic. Run: python test_decide.py"""
from guard import decide, OFF_PAIR, MAX_PAIR_COOL, MAX_PAIR_HEAT, OFF_AT_CENTS


def case(name, got, want_action, want_pair=None):
    action, pair, reason = got
    assert action == want_action, f"{name}: action={action!r} want={want_action!r} (reason: {reason})"
    assert pair == want_pair, f"{name}: pair={pair} want={want_pair}"
    assert reason, f"{name}: every decision must carry a human-readable reason"


# Mode guards
case("off mode does nothing", decide(30, "Off", "NoHold", 74, 68), "none")
case("unknown mode does nothing", decide(30, "EmergencyHeat", "NoHold", 74, 68), "none")

# Normal price, schedule running
case("normal price on schedule", decide(8, "Cool", "NoHold", 74, 68), "none")

# Spikes -> OFF (same pair regardless of mode)
case("spike applies OFF in Cool", decide(20, "Cool", "NoHold", 74, 68), "hold", OFF_PAIR)
case("spike applies OFF in Heat", decide(20, "Heat", "NoHold", 74, 68), "hold", OFF_PAIR)
case("boundary price enters OFF", decide(OFF_AT_CENTS, "Cool", "NoHold", 74, 68), "hold", OFF_PAIR)
case("spike re-asserts existing OFF hold", decide(30, "Cool", "HoldUntil", *OFF_PAIR), "hold", OFF_PAIR)

# Negative price -> MAX (pair depends on mode)
case("negative price Cool uses MAX_PAIR_COOL", decide(-1.2, "Cool", "NoHold", 74, 68), "hold", MAX_PAIR_COOL)
case("negative price Auto uses MAX_PAIR_COOL", decide(-1.2, "Auto", "NoHold", 74, 68), "hold", MAX_PAIR_COOL)
case("negative price Heat uses MAX_PAIR_HEAT", decide(-1.2, "Heat", "NoHold", 74, 68), "hold", MAX_PAIR_HEAT)
case("negative re-asserts existing MAX_COOL hold", decide(-0.1, "Cool", "HoldUntil", *MAX_PAIR_COOL), "hold", MAX_PAIR_COOL)
case("negative re-asserts existing MAX_HEAT hold", decide(-0.1, "Heat", "HoldUntil", *MAX_PAIR_HEAT), "hold", MAX_PAIR_HEAT)

# Releases + hysteresis
case("cheap price releases our OFF hold", decide(5, "Cool", "HoldUntil", *OFF_PAIR), "release")
case("dead band keeps our OFF hold", decide(13, "Cool", "HoldUntil", *OFF_PAIR), "none")
case("zero is not negative: MAX_COOL releases", decide(0, "Cool", "HoldUntil", *MAX_PAIR_COOL), "release")
case("zero is not negative: MAX_HEAT releases", decide(0, "Heat", "HoldUntil", *MAX_PAIR_HEAT), "release")
case("MAX_COOL releases even in OFF dead band", decide(13, "Cool", "HoldUntil", *MAX_PAIR_COOL), "release")
case("MAX_HEAT releases even in OFF dead band", decide(13, "Heat", "HoldUntil", *MAX_PAIR_HEAT), "release")
case("cheap price with no hold does nothing", decide(5, "Cool", "NoHold", 74, 68), "none")

# Human holds are sacred
case("spike respects manual hold", decide(30, "Cool", "PermanentHold", 72, 68), "none")
case("cheap price never releases manual hold", decide(5, "Cool", "TemporaryHold", 72, 68), "none")
case("negative price respects manual hold", decide(-2, "Cool", "HoldUntil", 72, 68), "none")

print("all decide() tests passed")
