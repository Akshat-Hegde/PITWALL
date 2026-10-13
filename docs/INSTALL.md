# Installing Pitwall at a cafe

For the person setting the hub up. The hub is one PC on the cafe network that every rig sends telemetry to; the TV, the staff page and the owner page all come from it.

## What the hub PC needs

| | |
|---|---|
| Windows | 10 or 11, 64-bit |
| CPU / RAM | 2 cores, 4 GB (6 to 10 rigs is comfortable) |
| Disk | 2 GB free (the app is about 100 MB; laps and backups grow slowly) |
| Network | Wired Ethernet on the same LAN as the rigs and phones |
| Always on | Yes: it starts by itself when the PC starts, even before anyone signs in |
| Internet | Not needed |

The hub PC can also drive the TV (a browser in full screen), so one small PC is enough.

## Reserve the hub's IP address

Rigs are told the hub's IP address in the game's settings, so it must never change. In the router's admin page, find "DHCP reservation" (or "static lease") and give the hub PC's address to its network card permanently. Write the address down.

## Run the installer

1. Run `Pitwall-Setup-<version>.exe` as administrator (right-click, Run as administrator).
2. Choose whether the TV page should open when this PC signs in.
3. On the last page, **keep the setup code**. It is shown once, in large type: write it down or photograph it. It is also in the install log (`%TEMP%\Setup Log *.txt`), and later you can run `Pitwall.exe setup-code` in `C:\Program Files\Pitwall` to see it again, as long as setup is not finished.
4. Leave "Open the setup page" ticked and click Finish.

The installer opens the firewall for the hub, starts it, and sets it to start with the PC.

## Set the cafe up (`/setup`)

The setup page asks for the code from the last page, then the cafe name, tagline, logo, colour, opening hours and the owner and staff PINs. Once saved, the code stops working and the owner PIN protects the page. The page is at `http://localhost:8000/setup` on the hub, or `http://<hub IP>:8000/setup` from another device.

## Point the rigs at the hub

Each rig sends UDP telemetry to the hub's IP address on port 20777. See [RIG_SETUP.md](RIG_SETUP.md) for the in-game settings.

## Backups

Every night the hub saves a zip of the laps, settings, branding and config in `C:\ProgramData\Pitwallackups` and keeps the last 14. If the hub PC was off at the backup hour, it makes one a couple of minutes after it next starts. To keep them off the hub PC, open `C:\ProgramData\Pitwall\config\hub.toml` (the installer puts a commented starter file there; remove the `#` in front of `directory` under `[backup]`) and point it at a folder on a USB stick (for example `directory = "E:/Pitwall backups"`), then restart the hub.

To restore, the hub must stay stopped, but its start-up task starts it again within a minute if it is only ended. So disable the task first:

1. Task Scheduler, right-click "Pitwall Hub", **Disable**, then right-click it again, **End**. Or, in an administrator command prompt:

        schtasks /Change /TN "Pitwall Hub" /Disable
        schtasks /End /TN "Pitwall Hub"

2. Restore:

        "C:\Program Files\Pitwall\Pitwall.exe" restore "C:\ProgramData\Pitwallackups\<the zip>"

   The restore is refused while the hub is running, and warns if the task is still enabled.

3. Start the hub again: Task Scheduler, right-click "Pitwall Hub", **Enable**, then **Run**. Or:

        schtasks /Change /TN "Pitwall Hub" /Enable
        schtasks /Run /TN "Pitwall Hub"

## Forgot the owner PIN?

On the hub PC, in an administrator command prompt:

    "C:\Program Files\Pitwall\Pitwall.exe" setup-code --reset

It opens setup again (everything else is kept) and prints a new setup code. Open `http://localhost:8000/setup`, enter the code and choose a new owner PIN. The hub does not need a restart. This only works from the hub PC itself, which is the point.

Editing `/setup` later: leave the PIN fields blank to keep the current PINs, or tick "Remove the staff PIN".

## Where things live

| | |
|---|---|
| Program | `C:\Program Files\Pitwall` |
| Cafe data (laps, settings, logo, logs) | `C:\ProgramData\Pitwall\data` |
| Config (commented starter file, edit to change ports, backup folder and so on) | `C:\ProgramData\Pitwall\config\hub.toml` |
| Backups | `C:\ProgramData\Pitwall\backups` |
| Log | `C:\ProgramData\Pitwall\data\logs\hub.log` |
| Start-up task | Task Scheduler, "Pitwall Hub" |

## Upgrading and uninstalling

Run a newer installer over the old one: the cafe's data and setup are kept, and the last page says "Already set up".

Uninstalling (Settings, Apps) removes the program, the firewall rules and the start-up task, but **keeps `C:\ProgramData\Pitwall`**. Reinstalling picks it up again. Delete that folder by hand only if you want to start from nothing.

## Renaming the product

The product name is written once, in `hub/simtelemetry/brand.py`. Change `PRODUCT_NAME` there and rebuild with `packaging\build.ps1`: the install folders, exe, installer, task name and shortcuts all follow. An existing install under the old name is a separate install; uninstall it first.
