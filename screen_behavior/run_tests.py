from __future__ import annotations

import unittest


def main() -> int:
    print("Running Screen Awareness + Tamagotchi Behavior V0.5 tests...\n")

    suite = unittest.defaultTestLoader.discover(
        "screen_behavior/tests",
        pattern="test_*.py",
    )

    result = unittest.TextTestRunner(
        verbosity=2,
    ).run(suite)

    print()

    if result.wasSuccessful():
        print("ALL TESTS PASSED")
        return 0

    print("TESTS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
