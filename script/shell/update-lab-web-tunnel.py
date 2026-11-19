"""Move the existing lab web key from port 8088 to the two loopback sites."""
import fcntl
import os
import pwd
import stat
import subprocess
import tempfile
from pathlib import Path

IP = "10.23.98.77"
CONF = Path("/etc/ssh/sshd_config.d/65-doorhandlecatch-tunnel.conf")
KEYS = Path("/etc/ssh/doorhandlecatch-wml.keys")
OLD = ("127.0.0.1:8088",)
NEW = ("127.0.0.1:8080", "127.0.0.1:8081")
VSCODE = tuple(f"127.0.0.1:{port}" for port in range(42080, 42112))
SSHD = "/usr/sbin/sshd"
SYSTEMCTL = "/usr/bin/systemctl"


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def key_options(targets):
    return f'from="{IP}/32",restrict,port-forwarding,' + ",".join(
        f'permitopen="{target}"' for target in targets
    )


def validate_matrix(web_ports):
    logins = {entry.pw_name for entry in pwd.getpwall()}
    for user, addr in [(user, IP) for user in sorted(logins)] + [
        ("wml", "10.23.98.78"), ("wml", "127.0.0.1")
    ]:
        selector = f"user={user},addr={addr},host={addr},laddr=10.22.0.145,lport=22"
        lines = subprocess.check_output([SSHD, "-T", "-C", selector], text=True).splitlines()
        config = dict(line.split(" ", 1) for line in lines if " " in line)
        if user == "wml" and addr == IP:
            require(config["authenticationmethods"] == "publickey" and
                    config["authorizedkeysfile"] == str(KEYS) and
                    config["allowtcpforwarding"] == "local" and
                    set(config["permitopen"].split()) == set(web_ports + VSCODE),
                    "Unexpected effective policy for the lab connection")
        else:
            permitted = set(config["permitopen"].split())
            web_target = "any" in permitted or any(
                target.rsplit(":", 1)[-1] in ("*", "8080", "8081") for target in permitted
            )
            conflict = (config["disableforwarding"] != "yes" and
                        config["allowtcpforwarding"] in ("yes", "all", "local") and web_target)
            require(not conflict, f"Existing forwarding conflict for {user} from {addr}")


def replace_file(path, content):
    mode = stat.S_IMODE(path.stat().st_mode)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(content.encode())
            out.flush()
            os.fsync(out.fileno())
            os.fchmod(out.fileno(), mode)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def install():
    for path in (CONF, KEYS):
        st = path.lstat()
        require(stat.S_ISREG(st.st_mode) and st.st_uid == 0 and not st.st_mode & 0o022,
                f"Unexpected owner or mode for {path}")
    before = {path: path.read_text() for path in (CONF, KEYS)}
    fields = [line.split(maxsplit=2) for line in before[KEYS].splitlines()]
    require(len(fields) == 2 and all(len(row) == 3 and row[1] == "ssh-ed25519" for row in fields)
            and fields[0][2].split()[0] != fields[1][2].split()[0], "Unexpected lab key set")
    ports = NEW if fields[0][0] == key_options(NEW) else OLD
    require(fields[0][0] == key_options(ports) and fields[1][0] == key_options(VSCODE),
            "Unexpected key restrictions; review them before making changes")
    old_rule = "    PermitOpen " + " ".join(ports + VSCODE)
    require(before[CONF].splitlines().count(old_rule) == 1, "Unexpected lab Match rule")
    subprocess.run([SSHD, "-t"], check=True)
    validate_matrix(ports)
    if ports == NEW:
        print("The two web targets are already configured.")
        return
    after = {
        KEYS: before[KEYS].replace(key_options(OLD) + " ", key_options(NEW) + " ", 1),
        CONF: before[CONF].replace(old_rule, "    PermitOpen " + " ".join(NEW + VSCODE), 1),
    }
    changed = []
    try:
        for path in (KEYS, CONF):
            replace_file(path, after[path])
            changed.append(path)
        subprocess.run([SSHD, "-t"], check=True)
        validate_matrix(NEW)
        subprocess.run([SYSTEMCTL, "reload", "ssh.service"], check=True)
        subprocess.run([SYSTEMCTL, "is-active", "--quiet", "ssh.service"], check=True)
    except BaseException:
        for path in reversed(changed):
            replace_file(path, before[path])
        subprocess.run([SSHD, "-t"], check=True)
        subprocess.run([SYSTEMCTL, "reload", "ssh.service"], check=True)
        raise
    print("Validated and reloaded SSH. Open a new Windows web-key session and keep the current session open.")


if __name__ == "__main__":
    require(os.geteuid() == 0, "Run in an administrator-approved sudo session")
    with open("/run/doorhandlecatch-ssh-config.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install()
