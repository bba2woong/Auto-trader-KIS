Set ws = CreateObject("WScript.Shell")
' 1 = 일반 창으로 실행 (백그라운드 아님)
ws.Run """C:\KIS_Trader\1. Practice\kis_trader\electron\node_modules\electron\dist\electron.exe"" ""C:\KIS_Trader\1. Practice\kis_trader\electron""", 1, False
