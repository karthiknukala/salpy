from __future__ import annotations

import bootstrap  # noqa: F401

import bakery_sal
import peterson_sal
import short_sal


def main() -> None:
    short_sal.main()
    peterson_sal.main()
    bakery_sal.main()


if __name__ == "__main__":
    main()
