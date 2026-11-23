# Security

All processing is local. There is no telemetry, hosted service, credential store,
or network listener in this application. Optional hardware libraries have their own
behavior and device support; review them for your environment.

Treat firmware, workspaces, and recordings as untrusted inputs. Do not load files
from unknown sources on a privileged or production-connected machine. The inspector
limits file sizes and supports a deliberately narrow set of formats.

Local workspace files can contain absolute paths and probe UIDs. Recordings contain
memory values and a workspace snapshot. Keep them out of public repositories unless
you have deliberately prepared public synthetic examples.

For a vulnerability, use the repository's private reporting feature if available.
Otherwise open an issue with a minimal sanitized description and request a private
disclosure channel; do not post secrets or exploitable private target details.
