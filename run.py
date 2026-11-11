#!/usr/bin/env python3
"""Entry point that works both from a git checkout and from a deployed copy.

Checkout:  lib/pylontech-rs485/src/pylontech_rs485 (submodule)
Deployed:  pylontech_rs485/ next to this file (see deploy.sh)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "lib", "pylontech-rs485", "src"), HERE):
    if os.path.isdir(os.path.join(p, "pylontech_rs485")):
        sys.path.insert(0, p)
        break
sys.path.insert(0, HERE)

from pylontech_ha.publisher import main  # noqa: E402

sys.exit(main())
