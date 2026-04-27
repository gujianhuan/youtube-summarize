Option Explicit

Dim fso, shell, scriptDir, guiLauncher
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
guiLauncher = scriptDir & "\video_local_helper_gui_launcher.pyw"

If Not fso.FileExists(guiLauncher) Then
    MsgBox "Missing GUI launcher file:" & vbCrLf & guiLauncher, vbCritical, "Local Helper Launch Error"
    WScript.Quit 1
End If

If TryRun(shell, "pythonw", guiLauncher, scriptDir, 0) Then
    WScript.Quit 0
End If

If TryRun(shell, "pyw", guiLauncher, scriptDir, 0) Then
    WScript.Quit 0
End If

If TryRun(shell, "python", guiLauncher, scriptDir, 1) Then
    WScript.Quit 0
End If

If TryRun(shell, "py", guiLauncher, scriptDir, 1) Then
    WScript.Quit 0
End If

MsgBox "No available Python launcher was found (pythonw / pyw / python / py)." & vbCrLf & _
       "Please install Python and add it to PATH.", vbCritical, "Local Helper Launch Error"
WScript.Quit 1

Function TryRun(objShell, runnerName, scriptPath, workDir, windowStyle)
    On Error Resume Next
    objShell.CurrentDirectory = workDir
    objShell.Run Chr(34) & runnerName & Chr(34) & " " & Chr(34) & scriptPath & Chr(34), windowStyle, False
    If Err.Number = 0 Then
        TryRun = True
    Else
        Err.Clear
        TryRun = False
    End If
    On Error GoTo 0
End Function
