#!/bin/sh
# Krellbot launcher -- installed by the krellbot installer.
# Computes KRELLBOT_HOME (engine data home) and the staged
# binary path at INVOCATION time from $HOME / $KRELLBOT_HOME
# and the embedded VERSION literal. Install-time substitution
# of the user's paths would corrupt or execute on any path
# containing shell metacharacters (& \ $() ...); this wrapper
# therefore defers every per-user path lookup to the user's
# own shell, where variable expansion treats the result as
# already-tokenized text and quotes do not reparse. When
# invoked with no arguments, defaults to ui --open. Any other
# argv is forwarded verbatim -- no parsing, no eval, no
# concatenation, no command substitution.
KRELLBOT_HOME="${KRELLBOT_HOME:-${HOME}/.krellbot}"
export KRELLBOT_HOME
if [ "$#" -eq 0 ]; then
    set -- ui --open
fi
exec "${HOME}/.local/share/krellbot/versions/%%KRELLBOT_VERSION%%/krellbot" "$@"
