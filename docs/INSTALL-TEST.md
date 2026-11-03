# Testing the installer on a spare PC or VM

Never run the installer on the development PC: it registers a boot task and firewall rules. Use a spare PC on the cafe LAN, or a Windows 10/11 VM.

1. **Prepare the test machine.**
   - Spare PC: Windows 10/11, on the same LAN as the rigs and your phone.
   - VM: Hyper-V "Quick Create" (Windows Pro) or VirtualBox. Use a **bridged** network adapter so rigs and phones on the LAN can reach it. Give it 4 GB RAM and 2 CPUs.
2. **Copy** `dist\Pitwall-Setup-0.5.0.exe` to it (USB stick or network share). No internet is needed.
3. **Install.** Right-click, Run as administrator. If "Windows protected your PC" appears, click More info, then Run anyway (expected: the installer is not signed yet); the next prompt may say Publisher: Unknown. On the first page choose "Hub PC". Leave "Keep this PC awake" ticked. On the last page **write down the setup code**. Leave "Open the setup page" ticked and click Finish. Then check that Task Scheduler shows the task "Pitwall Hub" (Ready or Running) and that Windows Defender Firewall with Advanced Security (`wf.msc`, Inbound Rules) shows the 3 rules "Pitwall hub", "Pitwall telemetry" and "Pitwall pages".
4. **Setup page** (opens in the browser):
   - first type a wrong code and check it is refused;
   - enter the right code;
   - fill in a cafe name, a logo, owner PIN `2468` and staff PIN `1357` and save (saving without a staff PIN is refused);
   - open `/setup` again and check it now asks for the owner PIN.
5. **TV.** Double-click the "Pitwall TV" shortcut. No black command window stays open; the branded LIVE page shows (full screen; Alt+F4 closes it).
6. **Boot start.** Restart the machine and **do not sign in**. From your phone on the same Wi-Fi open `http://<test machine IP>:8000/staff`. It must answer. (Allow about a minute after the PC starts.)
7. **Self-restart.** Sign in, end the hub's exe (`Pitwall.exe`). It runs as SYSTEM, so in Task Manager use "Show processes from all users" (run Task Manager as administrator), or run `taskkill /F /IM Pitwall.exe` from an administrator prompt. Then wait up to 1 minute (the task retries every minute). `/staff` answers again.
8. **Firewall.** The dev PC's `replay` command can only play into a hub on the same machine (it has no flag to send to another host), so use a real rig: set it up as in docs/RIG_SETUP.md with the test machine's address as UDP IP Address, and drive. The staff page shows the rig. If it does not, note whether the network profile is Public or Private (Settings, Network).
9. **Upgrade.** Run the same installer again. The Ready page says "Install updates when nobody is driving: the hub restarts." The last page says "Already set up: use your owner PIN." Data and setup are kept.
10. **Uninstall** via Settings, Apps. `C:\ProgramData\Pitwall` is still there, and the message at the end says so. Reinstall: setup is remembered (no setup code asked).
11. **Version 0.5.0 checks** (new in this version; never on the dev PC):
    - **Keep awake:** after install, Settings, System, Power: "When plugged in, turn off my screen" and "put my device to sleep" both say Never.
    - **Start-menu shortcuts:** "Pitwall Show setup code" asks for administrator rights (Yes), shows one explanation line and the code (or "Setup is done; use the owner PIN."), and the window stays open. "Pitwall Reset owner PIN" asks for administrator rights, explains, waits for a key (closing the window cancels), then prints a new code; the setup page then asks for it. "Pitwall Open logs folder" opens Explorer without asking, with no window flashing. "Pitwall Open backups folder" asks for administrator rights (Yes), then opens Explorer (if Explorer says "You don't currently have permission", Continue works); with the backup folder on an unplugged USB stick it shows a plain message instead.
    - **Permissions:** right-click each folder, Properties, Security, and check:
      - [ ] `C:\ProgramData\Pitwall` and `config`: SYSTEM and Administrators Full control; Users "Read & execute".
      - [ ] `data` and `backups`: only SYSTEM and Administrators (Users not listed at all); the backup zips inside `backups` too.
      - [ ] `data\logs`: Users "Read & execute" only (no Modify).
      - [ ] Sign in as a standard (non-administrator) Windows user: "Pitwall Open logs folder" opens in Explorer; "Pitwall Open backups folder" asks for an administrator's name and password (No: nothing opens); opening `C:\ProgramData\Pitwall\data` or `C:\ProgramData\Pitwall\backups` in Explorer is refused. The TV shortcut still works.
      - [ ] The installer's last page shows no red permissions warning.
    - **Hub not starting:** on the spare PC start another program on port 8000 first (for example `python -m http.server 8000`), then run the installer again: it waits up to 90 s, then the last page says "The hub has not started", shows the first line of `data\last-start-error.txt` if there is one, and does not offer "Open the setup page".
      - [ ] While it waits, drag the installer window around and cover/uncover it: it moves and redraws, the progress bar keeps moving, and the title never says "Not Responding".
    - **Custom data folder:** before an upgrade, set `data_dir` in `C:\ProgramData\Pitwall\config\hub.toml` to another folder (for example `D:\PitwallData`) and restart the hub once so it uses it. Run the installer again and check:
      - [ ] the last page knows setup is done (or shows the setup code) from that folder;
      - [ ] with the port-8000 blocker running, the start error shown comes from that folder's `last-start-error.txt`;
      - [ ] the permissions above apply to that folder (only SYSTEM and Administrators), and there is still no red permissions warning.
    - **TV waiting page:** restart the PC with the TV set to open at sign-in (or run the TV shortcut while the hub task is stopped). The TV shows "Starting up" (never a browser error page) and switches to the LIVE page by itself within a few seconds of the hub answering.
    - **TV-only PC:** on a second PC, run the installer and choose "This PC only shows the TV (the hub runs on another PC)".
      - [ ] Type something that isn't an address, for example `http://a b/` or `hub_pc`: it says "That isn't a PC address" and won't go on.
      - [ ] Type an address where no hub answers: it asks whether to use it anyway.
      - [ ] Type the hub PC's real address and finish. Check: no "Pitwall Hub" task, no firewall rules, no `Pitwall.exe` in Program Files, only the TV and Uninstall shortcuts; "Open the TV now" on the last page opens the hub's TV page; "Open the TV page when this PC signs in" was ticked by default.
    - **Switching a hub PC to TV-only:** on the spare PC that is already the hub, run the installer again and choose "This PC only shows the TV".
      - [ ] The Ready page says "This PC will stop being the hub".
      - [ ] Afterwards: no "Pitwall Hub" task in Task Scheduler, no Pitwall rules in `wf.msc`, no `Pitwall.exe` and no `_internal` folder in `C:\Program Files\Pitwall`, and no Staff, Owner, Setup or other admin shortcuts in the Start menu (only TV and Uninstall).
      - [ ] `C:\ProgramData\Pitwall` is still there.
    - **Silent TV-only install:** from an administrator Command Prompt:
      - [ ] `Pitwall-Setup-0.5.0.exe /VERYSILENT /TYPE=tv /HUB=<hub ip>` installs with no windows, and a "Pitwall TV" shortcut opens the TV page when any user signs in.
      - [ ] Without `/HUB=...` it installs nothing and ends with exit code 7 (`echo %ERRORLEVEL%` shows 7); the install log (`%TEMP%\Setup Log *.txt`) says the hub address is missing.
    - **Only one TV window:** on a PC that already has a TV start-up shortcut from the old launcher (`powershell -ExecutionPolicy Bypass -File tv-launcher.ps1 -StartOnLogin`, which puts "Pitwall TV.lnk" in your own Startup folder, `shell:startup`), run the installer with "Open the TV page when this PC signs in" ticked.
      - [ ] The old "Pitwall TV.lnk" is gone from `shell:startup`.
      - [ ] Sign out and in again: exactly one TV window opens.
    - **Installer file details:** right-click the installer, Properties, Details: company 9T7 Racing, product Pitwall, version 0.6.0. Right-click `Pitwall.exe` too: product Pitwall, version 0.6.0, and **no** company or copyright (the program's own details are neutral in every build, so an unbranded cafe's program never names 9T7 Racing).
    - **Real upgrade from 0.4.0:** on a clean spare PC or VM (or uninstall and delete `C:\ProgramData\Pitwall` first), install `dist\Pitwall-Setup-0.4.0.exe` as a hub. On its setup page choose a cafe name, owner PIN `2468`, **no staff PIN**, and opening hours 10:00 to 24:00 (midnight). Drive a lap or two (or replay a capture into it) so the boards have laps, open the TV on this PC or a TV-only PC, and back up once on the owner page. Then run `Pitwall-Setup-0.5.0.exe` over it and check:
      - [ ] The last page says "Already set up: use your owner PIN." (no setup code).
      - [ ] Staff page: the owner PIN `2468` opens it, with the red "Set a staff PIN" banner.
      - [ ] Staff Health tab and the setup page (after the owner PIN) say "Sessions now end automatically at closing time (midnight). Check your opening hours on the setup page — if you close after midnight, choose the next-day time." Without the owner PIN the setup page shows only "1 thing needs attention".
      - [ ] Save the setup page once with a staff PIN `1357`: the hours reminder and the red banner go away, and stay gone after restarting the PC.
      - [ ] TV: it does not reload by itself this once (0.4 TVs don't know how). Press F5 on the TV, or restart the TV PC: it shows the 0.5.0 TV. Upgrade the hub again (same installer): this time the TV reloads by itself within a minute.
      - [ ] Permissions as in "Permissions" above: `data` and `backups` (including the backup zip made by 0.4.0) SYSTEM and Administrators only; `C:\ProgramData\Pitwall` and `config` Users "Read & execute"; `data\logs` Users "Read & execute".
      - [ ] Data kept: the cafe name, logo, rig names and the laps from before the upgrade are on the boards and the owner page.
    - **Disabled-task check in any Windows language:** with the task disabled in Task Scheduler and the hub stopped, `Pitwall.exe restore <zip>` from an administrator prompt must not print the warning; with it enabled, it must.
12. **Send back** the install log (`%TEMP%\Setup Log *.txt`) and `C:\ProgramData\Pitwall\data\logs\hub.log`, plus a note of any step that failed.

Things worth watching:
- The task XML is written as plain text with a UTF-8 header. If `schtasks /Create` fails the install log shows it, and step 6 fails.
- The setup code must never be in a log: the install log only says `Setup code made`, and `hub.log` only says "Setup isn't finished. Use the Start-menu shortcut 'Pitwall Show setup code' to see the code." The code on the last page must match what **Pitwall Show setup code** shows.
