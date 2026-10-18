### J3. Backtest on pinned data and follow it in Jobs
I run a backtest on fixed data, follow it in Jobs and get results I can reproduce.
- J3.1 Starting a backtest with a saved strategy, a dataset and a date window creates a job that appears in Jobs right away as queued or running.
- J3.2 The job ends as succeeded, failed or cancelled, and Jobs shows the final state without a manual reload.
- J3.3 A succeeded run shows its return, maximum drawdown, trade count, fee setting and a fingerprint of the data it used. Running the same inputs again, in the GUI or the CLI, gives identical numbers.
- J3.4 Opening a finished job from Jobs shows the same results Research showed.
- J3.5 Bad input, such as a missing dataset, too many gaps or a window outside the data, fails with a message naming the problem. No results appear as if the run had worked.
