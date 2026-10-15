# Rig setup (F1 25)

Do this once on **every** rig PC, including a rig that runs on the hub PC itself. Every rig uses exactly the same settings; only the hub's address is specific to your cafe.

## 1. Find the hub's address

Open the setup page (`http://localhost:8000/setup` on the hub PC) or the staff page's **Health** tab. Both show the line to copy, with this PC's network address filled in, for example `192.168.1.64`. That is the **hub address** below.

Reserve that address in your router first (see [INSTALL.md](INSTALL.md), "Reserve the addresses in your router"), so it never changes.

## 2. Enter the settings in the game

In F1 25: **Game Options › Settings › UDP Telemetry Settings**

| Setting | Set it to |
|---|---|
| UDP Telemetry | **On** |
| UDP Broadcast Mode | **Off** |
| UDP IP Address | **the hub address** (for example `192.168.1.64`) |
| UDP Port | **20777** |
| UDP Send Rate | **20Hz** |
| UDP Format | **2025** |

**Your Telemetry** may stay **Restricted**: the hub only reads the rig's own car.

**A rig on the hub PC** uses the same hub address too, not `127.0.0.1`.

## 3. Check it

Drive out of the garage. Within a few seconds:

- the rig appears on the setup page and on the staff page's **Health** tab, with the state **On track**;
- its car appears on the TV.

A rig appears only once the hub receives correct telemetry from it, so a rig with wrong settings never shows up as a rig.

**Which rig is which?** Drive on one rig: on the setup page that rig says **Moving now**. Give it a name there (up to 16 characters, shown on the TV).

**A rig PC got a new address** (for example after a router change)? It shows up as a new rig. On the setup page, choose **Same rig as…** on the new one and pick its old entry: the name, colour, number and check-in sticker move over. Then reserve the rig's address in the router so it doesn't happen again.

## SimHub, wheel and dash software

F1 25 sends telemetry to **one** address only. If a rig also runs SimHub (or other dash or wheel software that reads F1 25 telemetry), let SimHub receive it and pass it on to the hub:

1. In the game, set **UDP IP Address** to `127.0.0.1` and **UDP Port** to the port SimHub listens on for F1 25 (20777 unless you changed it). The other settings stay as in the table above.
2. In SimHub, open the F1 25 game settings and turn on **UDP forwarding**. Add the hub address and port **20777** as the forwarding target. (The exact wording depends on your SimHub version.)
3. Drive out of the garage and check that the rig shows **On track** on the staff page's **Health** tab.

**On the hub PC itself**, SimHub must not use port 20777, because the hub needs it. In SimHub, change the F1 25 port to another number (for example 20778), set the game's **UDP Port** to that same number and its **UDP IP Address** to `127.0.0.1`, and forward to the hub address, port 20777. If SimHub keeps port 20777, the staff and setup pages say "Another program is using port 20777 (often SimHub). Close it or change its port."

## If a rig doesn't show up

The staff page's **Health** tab tells you what is wrong. What it says, and what to do:

| The Health tab says | What to do |
|---|---|
| "On Rig 3 check: UDP Telemetry On · UDP IP Address = … · Port 20777 · Format 2025, then drive out of the garage." | The hub hears nothing from that rig. On that rig, check the four settings in the game, then drive out of the garage. |
| State **No data** | Same as above. Also check the rig PC is switched on, the game is running and the PC is on the cafe network (cable plugged in). |
| State **Wrong game settings**, or "A PC at … is sending telemetry in the wrong format: set UDP Format to 2025." | Set **UDP Format** to **2025** on that rig. |
| "Rigs are set to different UDP Format settings …" | Set **UDP Format** to **2025** on every rig. |
| State **In menu** while someone is driving | The game is paused or spectating; driving again fixes it. If it stays, restart the game. |
| "Another program is using port 20777 (often SimHub). Close it or change its port." | Close that program on the hub PC, or change its port (see SimHub above). |
| "This PC's network address changed from … to …" | On every rig, set **UDP IP Address** to the new address, reprint the check-in stickers, then press **OK, done**. Reserve the address in your router so it doesn't happen again. |

Still nothing? Check that:

- the rig PC and the hub PC are on the same network (same router), with no VPN running on either;
- your antivirus on the hub PC lets in UDP port 20777 (see [INSTALL.md](INSTALL.md), "Antivirus");
- the hub address in the game is the one the setup page shows today.
