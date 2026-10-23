#!/usr/bin/env python3
"""
eSupport SEO • Database Seeder CLI Script
Usage:
    python scripts/seed_db.py [--reset] [--quiet]

Examples:
    python scripts/seed_db.py
    python scripts/seed_db.py --reset
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.seed import main

if __name__ == "__main__":
    main()
