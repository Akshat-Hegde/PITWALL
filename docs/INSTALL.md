# Installing Pitwall at a cafe

For the person setting the cafe up. One PC in the cafe is the **hub**: every rig sends its telemetry to it, and the TV, the staff page, the owner page and the guests' phones all get their pages from it.

**Only one hub per cafe.** Install the hub on one PC only. Any other PC that drives a TV gets the "TV only" install (below), which points at that hub.

## What the hub PC needs

| | |
|---|---|
| Windows | 10 or 11, 64-bit |
| CPU / RAM | 2 cores, 4 GB (6 to 12 rigs is comfortable) |
| Disk | 2 GB free (the program is about 100 MB; laps and backups grow slowly) |
| Network | A cable (Ethernet) to the same router as the rigs |
| Always on | Yes: the hub starts by itself when the PC starts, even before anyone signs in |
| Internet | Not needed |

The hub PC can also drive the TV (a browser in full screen), so one small PC is enough.

## 1. Reserve the addresses in your router

Every rig is told the hub's network address in the game's settings, and the check-in stickers point at it, so the hub's address must never change. The rigs' addresses should not change either: the hub tells rigs apart by their address.

In the router's admin page, find **DHCP reservation** (some routers call it "static lease" or "address reservation") and reserve the current address of:

- the hub PC;
- every rig PC.

Write the hub's address down. The setup page also shows it.

**If the hub's address changes anyway**, the staff page and the setup page show a red message: "This PC's network address changed from A to B. On every rig set UDP IP Address to B, and reprint the check-in stickers." Do that, press **OK, done**, and reserve the address in the router. (The TV never shows this.)

**If a rig's address changes**, it shows up as a new rig. On the setup page, choose **Same rig as…** on the new one and pick its old entry. See [RIG_SETUP.md](RIG_SETUP.md).

## 2. Run the installer

1. Double-click `Pitwall-Setup-<version>.exe`.
2. **"Windows protected your PC"** (a blue window) may appear. It appears because the installer isn't signed with a paid certificate yet, not because something is wrong. Click **More info**, then **Run anyway**.
3. Windows then asks "Do you want to allow this app to make changes to your device?" and may show **Publisher: Unknown**. Click **Yes**.
4. Choose **Hub PC**.
5. Leave **Keep this PC awake (recommended for the hub and TV PC)** ticked. It stops Windows from putting the PC or its screen to sleep when plugged in, so rigs, the TV and phones always reach the hub.
6. Tick **Open the TV page when this PC signs in** if this PC also drives the TV.
7. On the last page, **keep the setup code**. It is shown once, in large type: write it down or photograph it. If you lose it, use the Start-menu shortcut **Pitwall Show setup code** (as long as setup is not finished).
8. Leave **Open the setup page** ticked and click **Finish**.

The installer lets the hub through Windows Firewall, starts it, and sets it to start with the PC.

If the last page says **The hub has not started**, it shows the reason when it knows it. Restart the PC; if it still doesn't start, send the logs (Start menu, **Pitwall Open logs folder**) to support.

## 3. Antivirus

Windows Security normally lets Pitwall run. If it (or another antivirus) blocks or deletes it:

- **Windows Security:** open Windows Security, **Virus & threat protection**, **Manage settings**, **Add or remove exclusions**, **Add an exclusion**, **Folder**, and choose `C:\Program Files\Pitwall`.
- **Other antivirus with its own firewall** (Norton, McAfee, Quick Heal and others): allow Pitwall in its firewall, or allow these two ports coming in: **TCP 8000** (the pages) and **UDP 20777** (telemetry from the rigs). Without that, rigs and phones can't reach the hub even though Windows Firewall lets them.

## 4. Set the cafe up (`/setup`)

The setup page opens after the install, or open `http://localhost:8000/setup` on the hub PC (or the Start-menu shortcut **Pitwall Setup**). It asks for the setup code, then:

- the cafe name, tagline, logo and colour;
- the **opening hours**. A cafe open past midnight can close up to 06:00 the next day, shown as "closes at 02:00 (next day)"; laps until then count for the day the cafe opened;
- the **owner PIN** (opens the owner and setup pages);
- the **staff PIN** (opens the staff page). It is required. It may be the same as the owner PIN;
- optionally the **guest Wi-Fi** (name and password): the TV shows it as a "Join our Wi-Fi" QR next to the card QR codes.

Once saved, the setup code stops working and the owner PIN protects the setup page. To change anything later, open the setup page again: leave a PIN box blank to keep the current PIN.

**Sessions end by themselves.** At closing time every open session is ended and the driver's card is made. A timed session also ends once its time is up and the car hasn't been on track for 5 minutes. The staff page then says "Ended automatically at closing time" or "Ended automatically: time was up".

## 5. Guest Wi-Fi: test it from a phone

Guests' phones must be on a Wi-Fi that can reach this PC: your main cafe Wi-Fi, or a guest network with "client/guest isolation" (sometimes "AP isolation") turned off. Otherwise guests can't check in or open their cards.

To check: on the setup page (or the staff page's **Health** tab), find **Test from your phone**. Join the guest Wi-Fi on a phone and scan the QR code with its camera. The phone should say "Your phone can reach Pitwall. Check-in and cards will work.", and the setup page then shows "A phone reached the hub at 14:02".

If the page doesn't open on a phone on the guest Wi-Fi, guests can't use check-in or cards: use the main Wi-Fi or turn off isolation in the router.

## 6. Point the rigs at the hub

On every rig, in F1 25: Game Options › Settings › UDP Telemetry Settings: UDP Telemetry **On**, UDP Broadcast Mode **Off**, UDP IP Address = **the hub's address** (shown on the setup page), UDP Port **20777**, UDP Send Rate **20Hz**, UDP Format **2025**. Your Telemetry may stay Restricted. A rig on the hub PC also uses the hub's address, not 127.0.0.1. Details, SimHub and troubleshooting: [RIG_SETUP.md](RIG_SETUP.md).

Then name the rigs on the setup page (drive on one: it says **Moving now**).

## 7. Check-in stickers

Open the staff page (`http://<hub address>:8000/staff`) and choose **Check-in QR**: a printable A4 sheet with one QR sticker per rig. Print it, cut the stickers out and stick one on each rig where the driver can see it. Guests scan it with their phone to put their name on the rig.

Reprint the stickers when you add a rig, when you press **New code** for a rig (its old sticker stops working), and when the hub's address changes.

## 8. The TV

**TV on the hub PC:** tick "Open the TV page when this PC signs in" in the installer, or use the **Pitwall TV** shortcut. Alt+F4 closes it. While the hub is starting, the TV shows "Starting up" and switches to the TV page by itself.

**TV on another PC:** run the same installer on that PC and choose **This PC only shows the TV (the hub runs on another PC)**. Type the hub's address. It installs only the TV shortcut (and opens the TV when the PC signs in); nothing else.

**Coming back after a power cut.** The hub starts by itself, even before anyone signs in, but the TV page only opens once someone signs in to Windows. For a PC that drives a TV, set Windows to sign in automatically:

1. Press Windows+R, type `netplwiz` and press Enter.
2. Untick **Users must enter a user name and password to use this computer** and click OK. (If you don't see that box: Settings, Accounts, Sign-in options, turn off "For improved security, only allow Windows Hello sign-in", then try again.)
3. Type the account's password twice.

Use this only on a PC that stays in the cafe. If the PC's BIOS has "Restore on AC power loss", set it to **Power On** too.

## Your licence

Your licence says how many rigs, which games and which features your cafe has. It is yours forever: it never expires and never needs the internet. The installer your supplier made for your cafe installs it; the owner page's **Licence** card shows it ("Licensed to Apex Lounge · 6 rigs · F1 25").

- **Adding rigs, games or features.** Your supplier sends a new licence code. On the owner page, paste it into the **Enter new code** box on the Licence card and press **Use this code**. It works straight away; there is no reinstall and racing is not interrupted.
- **More rigs than the licence covers.** Extra rigs still record laps and show on the staff page (marked "Not licensed"), but the TV shows only the licensed rigs. The staff and owner pages say so and who to contact.
- **"No licence found. Contact your supplier."** The hub runs as a 4-rig licence until the code is entered. Ask your supplier for your code and enter it on the owner page.
- **Installer for another cafe.** Each cafe's installer is made for that cafe. If it belongs to another cafe, it stops before changing anything and says so.
- **Code for another cafe.** A licence code works only on the cafe it was made for. Another cafe's code is refused ("This code is for Kart Hub. This PC belongs to Apex Lounge.") and nothing changes. If the hub PC has moved to a new cafe, ask your supplier: they reinstall it for the new cafe.

## Start-menu shortcuts (hub PC)

| Shortcut | What it does |
|---|---|
| Pitwall TV | Opens the TV page full screen. |
| Pitwall Staff / Owner / Setup | Open those pages in the browser. |
| Pitwall Show setup code | Shows the one-time setup code (until setup is done). Asks for administrator rights. |
| Pitwall Reset owner PIN | Forgot the owner PIN? Makes a new setup code so you can choose a new owner PIN on the setup page. Laps, rigs and settings are kept. Asks for administrator rights; close the window to cancel. |
| Pitwall Open backups folder | Opens the folder the backups go to. Asks for administrator rights (the backups hold guests' phone numbers and the Wi-Fi password). |
| Pitwall Open logs folder | Opens the logs, for sending to support. |

## Backups

Every night (04:00) the hub saves a zip with the laps, settings, rig names, check-in codes and logos, and keeps the last 14. If the hub PC was off at that time, it makes one a couple of minutes after it next starts.

**Choose where backups go** on the owner page, **Backups** card. A USB stick that stays plugged in is best, so the backups survive if the PC breaks: type its folder, for example `E:\Backups`, and press **Use this folder**. **Back up now** makes one straight away. Network folders and mapped drives (like `Z:`) aren't supported: the hub runs in the background and can't see them.

When a backup fails, the owner page says why in plain words (for example "The USB stick isn't plugged in"). When the last good backup is more than 2 days old, the owner page and the staff Health tab say "Last backup: 5 days ago. Check the backup folder or USB stick."

Backups contain guests' phone numbers and the guest Wi-Fi password, and backups made before version 0.5.0 also contain the owner and staff PINs as plain text. So the standard backups folder (`C:\ProgramData\Pitwall\backups`) is closed to ordinary Windows users: opening it with **Pitwall Open backups folder** asks for administrator permission (if Explorer then says "You don't currently have permission to access this folder", click **Continue**). Backups on a USB stick follow the USB stick's own permissions, so anyone who has the stick can read them: keep the stick safe.

## Restoring a backup

Restoring puts the laps, settings, rigs and logos back as they were at that backup. Do it on the hub PC, when nobody is driving:

1. Stop the hub so it doesn't start again by itself: open **Task Scheduler**, click **Task Scheduler Library**, right-click **Pitwall Hub**, **Disable**, then right-click it again, **End**.
2. Open the Start menu, type `cmd`, right-click **Command Prompt**, **Run as administrator**, and type (with the name of the zip you want; the newest has the latest date in its name):

        "C:\Program Files\Pitwall\Pitwall.exe" restore "E:\Backups\pitwall-20261015-0400.zip"

   It refuses while the hub is still running.
3. Start the hub again: in Task Scheduler, right-click **Pitwall Hub**, **Enable**, then **Run**.

The lap database it replaced is kept next to the restored one, ending in `.before-restore`.

## Forgot the owner PIN?

Use the Start-menu shortcut **Pitwall Reset owner PIN** on the hub PC. It opens setup again and shows a new setup code. Open the setup page, enter the code and choose a new owner PIN. Everything else is kept, and the hub doesn't need a restart. This only works on the hub PC itself, which is the point.

Wrong PINs: after five wrong PINs a device is locked out for a minute; after repeated lock-outs, for 15 minutes, and the owner page shows "Someone tried wrong PINs 15 times at 21:40".

## Upgrading

Run the newer installer on the hub PC, **when nobody is driving**: the hub restarts during the install. The cafe's data and setup are kept, and the last page says "Already set up: use your owner PIN." Upgrade the TV-only PCs too (choose "This PC only shows the TV" again); they keep working in the meantime. From 0.5.0 on, TVs reload themselves after an update. When upgrading from 0.4, restart each TV PC once (or press F5 on the TV).

**Upgrading to the first version with licences (after 0.5.0):**

- **Use the installer your supplier made for your cafe.** It keeps all your settings, PINs, rig names and laps, and installs your licence.
- If a general installer was used instead, the staff and owner pages say "No licence found", and a cafe with **more than 4 rigs** sees only rigs 1 to 4 on the TV (the other rigs keep recording laps). Enter your licence code on the owner page and every rig is back on the TV at once.

**Upgrading from 0.4:**

- **Sessions now end automatically at closing time (22:00).** Check your opening hours on the setup page — if you close after midnight, choose the next-day time. Until you save the setup page once, the staff and setup pages show this reminder.
- **Staff PIN.** If staff had no PIN before, set a staff PIN on the setup page right after upgrading; until then staff can use the owner PIN (the staff page shows a red "Set a staff PIN" banner).

**No going back below 0.5.0.** Version 0.5.0 stores PINs in a form older versions can't read. If you need to go back to an older version, uninstall, install the older version and restore a backup made before the upgrade.

## Uninstalling

Settings, Apps, Pitwall, Uninstall. It removes the program, the firewall rules and the start-up task, but **keeps the cafe's data** in `C:\ProgramData\Pitwall`. Reinstalling picks it up again. Delete that folder by hand only if you want to start from nothing (copy a backup somewhere safe first).

## Where things live

| | |
|---|---|
| Program | `C:\Program Files\Pitwall` |
| Cafe data (laps, settings, logos) | `C:\ProgramData\Pitwall\data` |
| Logs | `C:\ProgramData\Pitwall\data\logs` (Start menu: Pitwall Open logs folder) |
| Backups | The folder chosen on the owner page; otherwise `C:\ProgramData\Pitwall\backups` (Start menu: Pitwall Open backups folder, asks for administrator permission) |
| Technical settings (ports and such; not needed for normal use) | `C:\ProgramData\Pitwall\config\hub.toml` |
| Start-up task | Task Scheduler, "Pitwall Hub" |

The cafe data folder holds guests' phone numbers and the PINs, and the backups hold the phone numbers and the Wi-Fi password, so only Windows administrators (and the hub itself) can open those two folders. You don't need to open the data folder: use the owner page and the Start-menu shortcuts. **Pitwall Open logs folder** works for any Windows user (they can read the logs but can't change them). **Pitwall Open backups folder** asks for administrator permission. A backup folder you chose yourself (a USB stick) keeps that drive's own permissions.

Everything an owner changes is on the setup, owner and staff pages. `hub.toml` holds technical settings only (ports, recording, feature switches). If it ever has a mistake, the hub still starts with the standard settings and the staff and setup pages say which line is wrong.

## Renaming the product

The product name is written once, in `hub/simtelemetry/brand.py`. Change `PRODUCT_NAME` there and rebuild with `packaging\build.ps1`: the install folders, exe, installer, task name and shortcuts all follow. An existing install under the old name is a separate install; uninstall it first.
