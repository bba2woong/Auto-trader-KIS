Set ws = CreateObject("WScript.Shell")
Set s = ws.CreateShortcut(ws.SpecialFolders("Desktop") & "\KIS Auto Trader.lnk")
s.TargetPath = "wscript.exe"
s.Arguments = Chr(34) & "C:\kis_auto_trader\launch.vbs" & Chr(34)
s.WorkingDirectory = "C:\kis_auto_trader\"
s.IconLocation = "C:\kis_auto_trader\assets\20260610_172343.ico"
s.Save()
