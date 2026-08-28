Dim WshShell, strBat
Set WshShell = CreateObject("WScript.Shell")
strBat = WshShell.ExpandEnvironmentStrings("%USERPROFILE%") & "\Downloads\문서-관리-시스템-(smart-dms)\smart_dms_python\start_server.bat"
WshShell.Run "cmd /c """ & strBat & """", 0, False
Set WshShell = Nothing
