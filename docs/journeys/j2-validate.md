### J2. Validate it and see typed errors
Krellbot tells me exactly what is wrong with a strategy before I can run it.
- J2.1 Validating a correct strategy marks it valid, and it becomes available to Research and paper trading.
- J2.2 When something is wrong, such as an unknown indicator, a missing required field or a value out of range, validation names the problem and marks the field it is in.
- J2.3 Broken JSON typed or imported into the editor is refused with a clear message, and my last saved revision stays untouched.
- J2.4 A strategy that fails validation can't be backtested or armed, and the refusal says why.
- J2.5 Fixing the problem and validating again clears the error.
