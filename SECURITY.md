# Security

Do not open a public issue containing credentials, private participant data, hidden evaluation material or a vulnerability that could expose them.

For a sensitive report, email `submit@builderr.ai` with the subject `Signalpost validator security report` and a short description with reproduction steps. Do not include secrets unless Builderr asks for them through a suitable private channel.

The public citation-validator task must reject absolute paths, parent-directory escapes, symlink escapes, embedded URL credentials and oversized cited files. It must make no network requests.
