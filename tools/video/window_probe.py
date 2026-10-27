import ctypes,json,sys
from ctypes import wintypes as W
u=ctypes.windll.user32
u.SetWindowPos.argtypes=[W.HWND,W.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,W.UINT]
u.SetForegroundWindow.argtypes=[W.HWND]
u.ShowWindow.argtypes=[W.HWND,ctypes.c_int]
u.SendMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
try:u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except:pass
class RECT(ctypes.Structure):_fields_=[('left',W.LONG),('top',W.LONG),('right',W.LONG),('bottom',W.LONG)]
MON=ctypes.WINFUNCTYPE(W.BOOL,W.HMONITOR,W.HDC,ctypes.POINTER(RECT),W.LPARAM)
def monitor(h,dc,r,l):print('monitor',r.contents.left,r.contents.top,r.contents.right,r.contents.bottom);return True
u.EnumDisplayMonitors(None,None,MON(monitor),0)
WIN=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
pid=int(sys.argv[1])
def window(h,l):
    p=W.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(p))
    if p.value==pid and u.IsWindowVisible(h):
        r=RECT();u.GetWindowRect(h,ctypes.byref(r));print('owned window',h,r.left,r.top,r.right,r.bottom)
        a=W.DWORD();u.GetWindowDisplayAffinity(h,ctypes.byref(a));cl=W.DWORD();ctypes.windll.dwmapi.DwmGetWindowAttribute(h,14,ctypes.byref(cl),4);print('affinity',a.value,'cloaked',cl.value,'foreground',u.GetForegroundWindow())
        if '--front' in sys.argv:
            if h!=396062:u.SendMessageW(h,0x0010,0,0);return True
            u.ShowWindow(h,9);print('pos',u.SetWindowPos(h,-1,1912,-31,1936,1119,0x0040),'foreground',u.SetForegroundWindow(h),'error',ctypes.GetLastError())
    return True
u.EnumWindows(WIN(window),0)
