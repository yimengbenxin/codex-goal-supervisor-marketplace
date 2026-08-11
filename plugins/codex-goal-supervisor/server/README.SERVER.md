# Goal Supervisor Feedback Receiver

This isolated service stores opt-in Goal Supervisor diagnostic metadata.
It does not receive source files, prompts, environment values, or credentials.

## Runtime

- Project: `/home/ubuntu/workspaces/goal-supervisor-feedback`
- Service: `goal-supervisor-feedback.service`
- Bind: `127.0.0.1:23100`
- Database: `/home/ubuntu/workspaces/goal-supervisor-feedback/data/events.sqlite3`
- Secret environment: `/home/ubuntu/.config/goal-supervisor-feedback/goal-supervisor-feedback.env`
- Automatic device registration: `https://feedback.xn--15tf697cgrb.xyz/v1/devices/register`
- Structured event delivery: `https://feedback.xn--15tf697cgrb.xyz/v1/events`
- DNS: `feedback.xn--15tf697cgrb.xyz A <server-public-ip>`, TTL 600
- TLS certificate: `/etc/letsencrypt/live/feedback.xn--15tf697cgrb.xyz/`
- Certificate renewal: managed by Certbot; current certificate expires 2026-10-31
- Public diagnostic download: disabled
- Optional expert-asset download: read-only ZIP files under `/goal-supervisor-assets/`

## Operations

```bash
systemctl --user status goal-supervisor-feedback.service
curl --fail --silent http://127.0.0.1:23100/healthz
python3 /home/ubuntu/workspaces/goal-supervisor-feedback/app/feedback_receiver.py \
  stats --db /home/ubuntu/workspaces/goal-supervisor-feedback/data/events.sqlite3
journalctl --user -u goal-supervisor-feedback.service --no-pager -n 100
curl --silent --output /dev/null --write-out '%{http_code}\n' \
  --header 'Content-Type: application/json' --data '{}' \
  https://feedback.xn--15tf697cgrb.xyz/v1/events
```

The unauthenticated event check above must return `401`. Project consent causes
the plugin to register a device automatically; the issued Bearer credential is
returned once and only its SHA-256 hash is stored server-side. The server has no
web/manual/file upload route. Both public endpoints accept strict JSON only;
multipart, ZIP, binary, unknown fields, and oversized bodies are rejected. A
rejection stores only reason, byte count, content type, and body hash.

## Optional Private GitHub Archive

GitHub is a downstream archive, not a client upload endpoint. Only events that
have already passed the receiver's bounded sanitized schema are eligible. Keep
the write credential on this server, preferably as a short-lived GitHub App
installation token. Never copy it into the plugin or a user project.

```bash
export GOAL_SUPERVISOR_GITHUB_TOKEN='<server-side short-lived token>'
python3 /home/ubuntu/workspaces/goal-supervisor-feedback/app/feedback_receiver.py \
  mirror-github \
  --db /home/ubuntu/workspaces/goal-supervisor-feedback/data/events.sqlite3 \
  --repository owner/private-feedback-repo
```

The command creates one bounded issue for up to ten pending events. Success is
recorded per event. Timeout, authentication failure, or GitHub unavailability
keeps every event in SQLite for a later retry and does not affect project work.

Export remains server-local:

```bash
python3 /home/ubuntu/workspaces/goal-supervisor-feedback/app/feedback_receiver.py \
  export --db /home/ubuntu/workspaces/goal-supervisor-feedback/data/events.sqlite3 \
  --limit 100
```

Maintainers should normally use the cursor-based SSH fetcher from the plugin
source checkout:

```bash
python3 scripts/fetch_feedback.py --remote <ssh-host-alias> --output-dir feedback-inbox
```

## Plugin Marketplace

Plugin updates use a separate read-only Git repository. It shares only the TLS
virtual host and does not read or write the feedback database or quant paths.

Install the small CGI bridge used by Git smart HTTP:

```bash
sudo apt-get install -y fcgiwrap
sudo systemctl enable --now fcgiwrap.socket
```

- Server root: `/var/www/goal-supervisor-marketplace`
- Public source: `https://feedback.xn--15tf697cgrb.xyz/goal-supervisor-marketplace.git`
- Nginx include: `/etc/nginx/snippets/goal-supervisor-marketplace-location.conf`
- Public Git service: read-only smart HTTP (`git-upload-pack`)
- Public methods: `GET`, `HEAD`, plus `POST` only for `git-upload-pack`
- Publishing: SSH only

The Nginx route sends ref negotiation and object-pack transfer through
`git-http-backend` over `fcgiwrap`. This is required for Codex's shallow
marketplace clone. Static dumb-HTTP object reads remain a compatibility
fallback. Public `git-receive-pack` is disabled, so publishing remains SSH-only.

The marketplace tree contains only the runtime needed for installation and
daily updates. The full offline ZIP still contains documentation, verification,
and the pinned specialist role library. Marketplace installs download that
optional role library only after an explicit `agency_role_pack.py` command.
The archive URL is HTTPS, immutable, size bounded, SHA-256 pinned, and extracted
into a user-level cache after path and content-manifest verification. It is
never copied into a user project.

Optional role archives are served from:

```text
/var/www/goal-supervisor-assets
```

Only `GET` and `HEAD` for simple `.zip` names are accepted. Directory listings,
uploads, other extensions, and public Git publishing remain disabled.

The bare repository directory must be owned by the FastCGI account while the
publisher retains group write access. On the documented Ubuntu deployment:

```bash
sudo chown www-data:ubuntu /var/www/goal-supervisor-marketplace/goal-supervisor-marketplace.git
sudo chmod 2775 /var/www/goal-supervisor-marketplace/goal-supervisor-marketplace.git
git --git-dir=/var/www/goal-supervisor-marketplace/goal-supervisor-marketplace.git \
  config core.sharedRepository group
```

The compatibility fallback still requires this after publishing a commit:

```bash
git --git-dir=/var/www/goal-supervisor-marketplace/goal-supervisor-marketplace.git update-server-info
```

Clients refresh through the Codex marketplace CLI; the feedback upload consent
setting has no effect on plugin update checks.

## Stop And Roll Back

```bash
systemctl --user disable --now goal-supervisor-feedback.service
rm /home/ubuntu/.config/systemd/user/goal-supervisor-feedback.service
systemctl --user daemon-reload
```

Do not remove the data directory during service rollback. Public HTTPS accepts
authenticated event uploads only. Feedback export remains restricted to SSH.
