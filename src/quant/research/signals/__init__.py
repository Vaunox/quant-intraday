"""Layer 2 - Research: pure, causal trading-*signal* modules (alpha primitives).

A signal module turns hygiene-clean, adjusted bars into a **position path** and its
``label_times`` (t0 -> t1) for the purged splitters. It owns the *decision* logic only;
execution fidelity (next-bar-open fills, costs, square-off vs multi-day hold) belongs to
the backtester (P2.1 / P3T.3). The first inhabitant is the classic breakout Turtle
(:mod:`quant.research.signals.turtle`), the strategy under test in Phase 3T.
"""
