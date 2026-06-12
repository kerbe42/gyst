"""Strongman training + nutrition module.

A 52-week strongman training plan + nutrition tracker, ported from a
standalone TypeScript PWA (kerbe42/strongman-rebuild). The pure engine
(progression math, the 364-day calendar, session generation, nutrition) is a
faithful port; the domain numbers come only from the JSON files in
`strongman/data/` and are proven against the same test vectors. Persistence is
SQLite (strongman.db); the UI is Reflex; JARVIS gets training/nutrition tools.
"""
