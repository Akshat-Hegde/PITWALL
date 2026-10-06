# Rig setup (F1 25)

Do this on **every** rig PC. All rigs must use identical settings, especially the **UDP Format**.

## In-game settings

In F1 25: **Game Options → Settings → UDP Telemetry Settings**

| Setting | Value | Notes |
|---|---|---|
| UDP Telemetry | **On** | |
| UDP Broadcast Mode | **On** | No IP address needed; the hub must be on the same subnet. |
| UDP IP Address | *(ignored in broadcast mode)* | Only used if Broadcast is Off. Then set it to the hub PC's IP. |
| UDP Port | **20777** | Must match the hub (`[network] udp_port`). |
| UDP Send Rate | **20 Hz** or **30 Hz** | The same on all rigs. Higher rates aren't needed for the dashboard. |
| UDP Format | **`2025`** ⚠ *placeholder: confirm in the in-game menu* | **Identical on all rigs.** The hub accepts 2025 and 2026, warns if rigs differ, and drops any other format (e.g. 2024). |
| Your Telemetry | Restricted or Public | Either works: the hub only reads each rig's own car, which is never restricted. |

> **TODO (owner):** check which UDP Format values the in-game menu offers on these rigs (2025, and 2026 if the 2026 Season Pack is installed), pick one, and replace the placeholder above.

## Advanced: editing the config file

The same settings live in (after the first launch of the game):

```
Documents\My Games\<game_folder>\hardwaresettings\hardware_settings_config.xml
```

```xml
<motion>
  ...
  <udp enabled="true" broadcast="true" ip="127.0.0.1" port="20777" sendRate="20"
       format="2025" yourTelemetry="restricted" onlineNames="off" />
</motion>
```

**Close the game before editing**: any change made in-game while it's running overwrites manual edits. A future hub tool will write this `<udp>` element for you (see `hub/simtelemetry/adapters/f1/rig_setup.py`, added in a later step).

## Direct-IP mode (fallback)

If broadcast packets don't reach the hub (different subnet, a Wi-Fi access point that filters broadcast, or a VPN adapter), set **UDP Broadcast Mode = Off** and **UDP IP Address = the hub PC's IPv4 address** (`ipconfig` on the hub). The hub identifies rigs by source IP in both modes.

## Hub on the same PC as a rig

This is supported. That rig's packets arrive from the PC's own address (LAN IP in broadcast mode, `127.0.0.1` if you set the IP to localhost). The hub logs which IP each rig resolves to.
