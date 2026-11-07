# Isolated ECS candidate image builds

The existing Jenkins PrepareTools entry installs or re-admits the official
Moby BuildKit v0.34.2 rootless image on ECS. No host buildx plugin, Java runtime
or permanent Jenkins agent is installed. Upstream is Apache-2.0; the original
license is retained in this directory.

- Release: https://github.com/moby/buildkit/releases/tag/v0.34.2
- Linux/amd64 manifest: `sha256:b2eef63fa76615a59fdab47309743d3018219574b8fcece77d38296704154f44`
- Config/image ID: `sha256:e164dcf5aa147a29659dea4e2e6b909db541c2dfe0b512dac38a2ffaf063fc18`
- License SHA-256: `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`

Each attempt creates its own rootless daemon, labelled state volume and closed
source/output mounts. There is no host Docker socket in the builder. CPU,
memory, swap and write-rate cgroups bound the owned daemon; actual host free
space, memory, cgroup peak and OOM observations are sampled within two seconds.
A kernel process handle stops only this daemon at a pressure boundary.

Immutable dependency bytes use verified OCI inputs. Existing worker dependencies
are exported as a bounded stream instead of reinstalling Torch or retaining a
second full Docker-save archive. Each completed output is verified before a
separately admitted Docker load; importing a layer uses its actual DiffID and
allocation measurement, with existing IDs deduplicated. Interrupted daemon
imports are recorded as unknown, never as verified cleanup.

Every phase retains a plan, raw observations and source-bound receipt. Results
describe a controlled measurement, not production capacity or performance.
Missing space, rootless prerequisites, cgroup enforcement or evidence fails
closed. Business data, original images, backups and sealed custody inputs are
retained. No automatic disk expansion or shared builder prune is performed.
