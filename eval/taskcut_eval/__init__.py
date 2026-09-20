"""Measurement harness for taskcut.

The package is built along four axes that do not know about each other:

    workload    what work a session is asked to do, and what to ask it afterwards
    arm         how taskcut is configured for a run, if it is loaded at all
    transcript  what a finished session recorded, parsed into plain records
    metric      a pure function from a transcript to a number

A run is a workload crossed with an arm. Everything downstream reads only the
transcript, so a metric never learns how the session was driven and a workload
never learns which arm it ran under. `driver` is the one impure module: it owns
the terminal transport and nothing else depends on its internals.
"""

__all__ = ["arms", "metrics", "report", "transcript", "workload"]
