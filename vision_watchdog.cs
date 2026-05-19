/*
 * vision_watchdog.cs — Zero-flash invisible process manager for opencode-vision.
 * Copyright (C) 2026 Farhan Dhrubo
 *
 * Licensed under GPLv3 — see LICENSE.
 *
 * Compile:  csc.exe /target:winexe /out:vision_watchdog.exe vision_watchdog.cs
 *           (csc.exe ships with .NET Framework or via "dotnet build")
 *
 * Runs hidden (no console, no window, no taskbar icon).
 * Same logic as vision_watchdog.vbs — WMI polling, PID file management.
 *
 * Usage:
 *   vision_watchdog.exe
 *   vision_watchdog.exe "python C:\path\to\vision_mcp_server.py --http 3789"
 *   vision_watchdog.exe "my_command" "my_pid_file.pid"
 */

using System;
using System.Diagnostics;
using System.IO;
using System.Management;
using System.Threading;

class VisionWatchdog
{
    static void Main(string[] args)
    {
        string scriptDir = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
        string defaultCmd = $"python \"{Path.Combine(scriptDir, "vision_mcp_server.py")}\" --http 3789";

        string childCmd = args.Length > 0 ? args[0] : defaultCmd;
        string pidFileName = args.Length > 1 ? args[1] : "vision_watchdog.pid";
        string pidFilePath = Path.Combine(Path.GetTempPath(), pidFileName);

        while (true)
        {
            bool opencodeRunning = false;
            try
            {
                using (var searcher = new ManagementObjectSearcher(
                    "SELECT * FROM Win32_Process WHERE Name='opencode.exe'"))
                {
                    opencodeRunning = searcher.Get().Count > 0;
                }
            }
            catch { }

            if (opencodeRunning)
            {
                if (!File.Exists(pidFilePath))
                {
                    try
                    {
                        Process proc = new Process();
                        proc.StartInfo.FileName = "cmd.exe";
                        proc.StartInfo.Arguments = $"/c start /b {childCmd}";
                        proc.StartInfo.CreateNoWindow = true;
                        proc.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;
                        proc.StartInfo.UseShellExecute = false;
                        proc.Start();
                        File.WriteAllText(pidFilePath, proc.Id.ToString());
                    }
                    catch { }
                }
            }
            else
            {
                if (File.Exists(pidFilePath))
                {
                    try
                    {
                        string pid = File.ReadAllText(pidFilePath).Trim();
                        using (var searcher = new ManagementObjectSearcher(
                            $"SELECT * FROM Win32_Process WHERE ProcessId={pid}"))
                        {
                            foreach (var p in searcher.Get())
                            {
                                try { ((ManagementObject)p).InvokeMethod("Terminate", null); } catch { }
                            }
                        }
                        // Fallback: kill any python running our script
                        using (var searcher = new ManagementObjectSearcher(
                            "SELECT * FROM Win32_Process WHERE Name='python.exe' AND CommandLine LIKE '%vision_mcp_server%'"))
                        {
                            foreach (var p in searcher.Get())
                            {
                                try { ((ManagementObject)p).InvokeMethod("Terminate", null); } catch { }
                            }
                        }
                    }
                    catch { }
                    try { File.Delete(pidFilePath); } catch { }
                }
            }

            Thread.Sleep(10000);
        }
    }
}
