### J6. Pause entries, restart, and recover
I can stop new trades without losing control, and a restart never loses or invents state.
- J6.1 Pausing entries stops new entries while stops and exits keep working, and the status shows entries as paused.
- J6.2 Resuming entries lets the strategy enter again on its next signal.
- J6.3 After a restart, armed strategies, positions, pause state, saved strategies and paper history are exactly as they were.
- J6.4 A backtest that was running when the workstation stopped shows as interrupted after restart. It never shows as running, and it never silently disappears.
- J6.5 If the workstation stops while the GUI is open, the GUI says it can't reach it. When the workstation is back, one Retry recovers without a page reload.
