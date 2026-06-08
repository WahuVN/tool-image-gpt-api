' Launch Wahu Image Studio without showing a console window.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = appDir
batPath = appDir & "\run_wahu_desktop_app.bat"
If Not fso.FileExists(batPath) Then
    MsgBox "Khong tim thay run_wahu_desktop_app.bat. Hay kiem tra thu muc cai dat.", _
        vbCritical, "Wahu Image Studio"
    WScript.Quit 1
End If
sh.Run """" & batPath & """", 0, False
