from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vrp_app_final.main import VRPFinalApp  # type: ignore
else:
    from .main import VRPFinalApp


def main() -> None:
    app = VRPFinalApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
