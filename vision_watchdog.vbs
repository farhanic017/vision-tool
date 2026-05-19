' vision_watchdog.vbs — Invisible background process manager for opencode-vision.
' Copyright (C) 2026 Farhan Dhrubo
'
' Licensed under GPLv3 — see LICENSE.
'
' Monitors for opencode.exe via WMI every 10 seconds.
' When opencode runs → launches child process (hidden, no window).
' When opencode exits → kills child process, cleans up PID file.
'
' Usage:
'   wscript.exe //nologo vision_watchdog.vbs
'   wscript.exe //nologo vision_watchdog.vbs "python C:\path\to\vision_mcp_server.py --http 3789"
'   wscript.exe //nologo vision_watchdog.vbs "my_command" "my_pid_file.pid"
'
' For zero-flash (no wscript icon): compile vision_watchdog.cs into vision_watchdog.exe
'   csc.exe /target:winexe vision_watchdog.cs

Dim args, childCmd, pidFileName, shell, fso, wmi, pidFilePath

Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")
Set wmi   = GetObject("winmgmts:\\.\root\cimv2")

' ── Parse arguments ───────────────────────────────────────────────
Set args = WScript.Arguments

' Default: run vision_mcp_server.py (assumes next to this script)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
defaultCmd = "python """ & scriptDir & "\vision_mcp_server.py"" --http 3789"

childCmd    = defaultCmd
pidFileName = "vision_watchdog.pid"

If args.Count > 0 Then childCmd    = args(0)
If args.Count > 1 Then pidFileName = args(1)

pidFilePath = shell.ExpandEnvironmentStrings("%TEMP%") & "\" & pidFileName

' ── Main loop ─────────────────────────────────────────────────────
Do While True
    Dim processes, opencodeRunning
    Set processes = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='opencode.exe'")
    opencodeRunning = (processes.Count > 0)

    If opencodeRunning Then
        ' Start child if not already running
        If Not fso.FileExists(pidFilePath) Then
            Dim pidFileOut, procEnv
            ' Launch hidden (window style 0 = invisible)
            Dim procId
            procId = shell.Run(childCmd, 0, False)

            ' Write PID file so we can kill later
            Set pidFileOut = fso.CreateTextFile(pidFilePath, True)
            pidFileOut.WriteLine(procId)
            pidFileOut.Close
        End If
    Else
        ' Kill child if running
        If fso.FileExists(pidFilePath) Then
            Dim pidFileIn, pid
            Set pidFileIn = fso.OpenTextFile(pidFilePath, 1)
            pid = Trim(pidFileIn.ReadLine())
            pidFileIn.Close

            On Error Resume Next
            Dim proc
            Set proc = wmi.Get("Win32_Process.Handle='" & pid & "'")
            If Not Err.Number = 0 Then
                ' PID might be stale — find any python running our script
                Dim procs
                Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='python.exe' AND CommandLine LIKE '%vision_mcp_server%'")
                For Each p In procs
                    p.Terminate()
                Next
            Else
                proc.Terminate()
            End If
            On Error Goto 0

            fso.DeleteFile pidFilePath, True
        End If
    End If

    WScript.Sleep 10000
Loop
