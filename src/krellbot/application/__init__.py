"""Application services.

The application layer owns business behavior. Adapters (CLI, GUI, versioned
API) call into the application layer; the application layer owns validation,
state, and persistence for one slice of behavior at a time. Nothing in this
package reads the OS keyring or opens a network transport — those concerns
are explicit dependencies injected by the composition root or the test.
"""
