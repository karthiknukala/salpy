from __future__ import annotations

import bakery_sal
import bootstrap  # noqa: F401
import composition_sal
import peterson_sal
import short_sal


def main() -> None:
    short_sal.main()
    peterson_sal.main()
    bakery_sal.main()
    composition_sal.main()


if __name__ == "__main__":
    main()
