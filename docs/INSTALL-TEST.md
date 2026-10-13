# Testing the installer on a spare PC or VM

Never run the installer on the development PC: it registers a boot task and firewall rules. Use a spare PC on the cafe LAN, or a Windows 10/11 VM.

1. **Prepare the test machine.**
   - Spare PC: Windows 10/11, on the same LAN as the rigs and your phone.
   - VM: Hyper-V "Quick Create" (Windows Pro) or VirtualBox. Use a **bridged** network adapter so rigs and phones on the LAN can reach it. Give it 4 GB RAM and 2 CPUs.
2. **Copy** `dist\Pitwall-Setup-0.2.1.exe` to it (USB stick or network share). No internet is needed.
3. **Install.** Right-click, Run as administrator. On the last page **write down the setup code**. Leave "Open the setup page" ticked and click Finish. Then check that Task Scheduler shows the task "Pitwall Hub" (Ready or Running) and that Windows Defender Firewall with Advanced Security (`wf.msc`, Inbound Rules) shows the 3 rules "Pitwall hub", "Pitwall telemetry" and "Pitwall pages".
4. **Setup page** (opens in the browser):
   - first type a wrong code and check it is refused;
   - enter the right code;
   - fill in a cafe name, a logo, owner PIN `2468` and save;
   - open `/setup` again and check it now asks for the owner PIN.
5. **TV.** Double-click the "Pitwall TV" shortcut. The branded LIVE page shows (full screen; Alt+F4 closes it).
6. **Boot start.** Restart the machine and **do not sign in**. From your phone on the same Wi-Fi open `http://<test machine IP>:8000/staff`. It must answer. (Allow about a minute after the PC starts.)
7. **Self-restart.** Sign in, end the hub's exe (`Pitwall.exe`). It runs as SYSTEM, so in Task Manager use "Show processes from all users" (run Task Manager as administrator), or run `taskkill /F /IM Pitwall.exe` from an administrator prompt. Then wait up to 1 minute (the task retries every minute). `/staff` answers again.
8. **Firewall.** The dev PC's `replay` command can only play into a hub on the same machine (it has no flag to send to another host), so use a real rig: set F1 25's telemetry IP to the test machine's IP, port 20777, and drive. The staff page shows the rig. If it does not, note whether the network profile is Public or Private (Settings, Network).
9. **Upgrade.** Run the same installer again. The last page says "Already set up: use your owner PIN." Data and setup are kept.
10. **Uninstall** via Settings, Apps. `C:\ProgramData\Pitwall` is still there, and the message at the end says so. Reinstall: setup is remembered (no setup code asked).
11. **Send back** the install log (`%TEMP%\Setup Log *.txt`) and `C:\ProgramData\Pitwall\data\logs\hub.log`, plus a note of any step that failed.

Things worth watching:
- The task XML is written as plain text with a UTF-8 header. If `schtasks /Create` fails the install log shows it, and step 6 fails.
- The setup code on the last page must match the line `Setup code:` in the install log.
