' vision_watchdog.vbs — Always-on background process manager for vision-tool.
' Copyright (C) 2026 Farhan Dhrubo
'
' Licensed under GPLv3 — see LICENSE.
'
' Monitors for ANY AI coding assistant process via WMI every 10 seconds.
' When a supported tool runs -> launches vision MCP server (hidden, no window).
' When all tools exit -> kills child process, cleans up PID file.
'
' Supported tools: opencode.exe, claude.exe, cursor.exe, windsurf.exe,
'                  aider.exe, continue.exe
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
Set wmi   = GetObject("winmgmts:\.\root\cimv2")

' -- AI tool processes to watch -----------------------------------------
Dim AI_TOOLS
AI_TOOLS = Array( _
    "opencode.exe", _
    "claude.exe", _
    "cursor.exe", _
    "windsurf.exe", _
    "aider.exe", _
    "continue.exe" _
)

' -- Parse arguments ----------------------------------------------------
Set args = WScript.Arguments

' Default: run vision_mcp_server.py (assumes next to this script)
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
defaultCmd = "python """ & scriptDir & "\vision_mcp_server.py"" --http 3789"

childCmd    = defaultCmd
pidFileName = "vision_watchdog.pid"

If args.Count > 0 Then childCmd    = args(0)
If args.Count > 1 Then pidFileName = args(1)

pidFilePath = shell.ExpandEnvironmentStrings("%TEMP%") & "\" & pidFileName

' -- Helper: check if any AI tool process is running --------------------
Function IsAnyAiToolRunning()
    Dim proc, anyRunning
    anyRunning = False
    For Each tool In AI_TOOLS
        Set proc = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='" & tool & "'")
        If proc.Count > 0 Then
            anyRunning = True
            Exit For
        End If
    Next
    IsAnyAiToolRunning = anyRunning
End Function

' -- Main loop ----------------------------------------------------------
Do While True
    Dim anyRunning
    anyRunning = IsAnyAiToolRunning()

    If anyRunning Then
        ' Start child if not already running
        If Not fso.FileExists(pidFilePath) Then
            Dim pidFileOut
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
            If Err.Number <> 0 Then
                ' PID might be stale - find any python running our script
                Dim procs
                Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='python.exe' AND CommandLine LIKE '%vision_mcp_server%'")
                For Each p In procs
                    p.Terminate()
                Next
            Else
                proc.Terminate()
            End If
            On Error Goto 0

            On Error Resume Next
            fso.DeleteFile pidFilePath, True
            On Error Goto 0
        End If
    End If

    WScript.Sleep 10000
Loop
