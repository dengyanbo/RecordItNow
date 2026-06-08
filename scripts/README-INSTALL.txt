RIN ? Record It Now
====================

ONE-CLICK INSTALL
-----------------

1. Make sure you have extracted the whole RIN-vX.Y.Z-windows-installer.zip
   to a folder. This folder should now contain Install.bat (this is the
   one you double-click), install.ps1, README-INSTALL.txt, and a
   `bundle\` subfolder with RIN.exe inside it.

2. Double-click Install.bat.

3. Approve any Windows prompts that appear:
     - SmartScreen may warn that the script is unrecognized; click
       "More info" -> "Run anyway" if you trust this download.
     - Winget may pop a UAC consent dialog when installing FFmpeg.

4. Wait for "Installation complete". Press any key to close the window.

5. Search "RIN" in the Start Menu to launch.

WHAT IT DOES
------------
- Copies the standalone RIN.exe bundle to
    %LOCALAPPDATA%\Programs\RIN\
- Installs FFmpeg via winget if it is not already on PATH
- Creates a Start Menu shortcut

YOUR DATA
---------
Captures, logs, and the database live in
    %LOCALAPPDATA%\RIN\
They are kept across reinstalls and upgrades.

UPGRADING
---------
To install a newer version on top of an existing one:

1. Quit RIN from the system tray (right-click icon -> Quit).
2. Download the new RIN-vX.Y.Z-windows-installer.zip.
3. Extract it and double-click Install.bat as you did the first time.

Your captures, database, logs and models live in %LOCALAPPDATA%\RIN
and are kept across upgrades.

ADVANCED OPTIONS
----------------
Open a PowerShell window in the extracted folder and run install.ps1
directly to pass options:

    .\install.ps1 -FromBundle .\bundle -Force -Autostart
    .\install.ps1 -FromBundle .\bundle -Force -InstallDir "D:\Apps\RIN"
    .\install.ps1 -FromBundle .\bundle -Force -SkipDeps

Flags:
    -Autostart             Run RIN.exe on Windows login
    -InstallDir <path>     Install somewhere other than %LOCALAPPDATA%
    -SkipDeps              Skip the FFmpeg / Copilot CLI checks

UNINSTALL
---------
Delete %LOCALAPPDATA%\Programs\RIN
Delete %APPDATA%\Microsoft\Windows\Start Menu\Programs\RIN.lnk

Optional - also delete your captures and database:
    %LOCALAPPDATA%\RIN

DOCUMENTATION
-------------
README and source:  https://github.com/dengyanbo/RecordItNow
Issue tracker:      https://github.com/dengyanbo/RecordItNow/issues