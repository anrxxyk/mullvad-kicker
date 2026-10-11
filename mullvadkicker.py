#!/usr/bin/env python3
"""
Mullvad Account Kicker — GUI (working auth)
"""

import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import List, Dict, Optional

try:
    import requests
except ImportError:
    raise SystemExit("pip install requests")


BASE = "https://api.mullvad.net"


class MullvadAPI:
    def __init__(self, account: str, timeout: float = 15.0):
        self.account = account.strip()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MullvadKickerGUI/1.2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.timeout = timeout
        self.token: Optional[str] = None

    def _get_token(self) -> None:
        if self.token:
            return
        url = f"{BASE}/auth/v1/token"
        r = self.session.post(
            url,
            json={"account_number": self.account},
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Token failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"No access_token in response: {data}")
        self.token = token
        self.session.headers["Authorization"] = f"Bearer {token}"

    def list_devices(self) -> List[Dict]:
        self._get_token()
        url = f"{BASE}/accounts/v1/devices"
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code in (401, 403):
            raise RuntimeError(f"Auth failed ({r.status_code}): {r.text[:300]}")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "devices" in data:
            return data["devices"]
        return []

    def revoke(self, device_id: str) -> bool:
        self._get_token()
        url = f"{BASE}/accounts/v1/devices/{device_id}"
        r = self.session.delete(url, timeout=self.timeout)
        if r.status_code in (200, 204):
            return True
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return False


class KickerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Mullvad Account Kicker")
        self.geometry("620x520")
        self.minsize(500, 400)

        self.devices: List[Dict] = []
        self._busy = False
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill=tk.X, **pad)

        ttk.Label(top, text="Mullvad account:").pack(side=tk.LEFT)
        self.account_var = tk.StringVar()
        self.entry = ttk.Entry(top, textvariable=self.account_var, width=24)
        self.entry.pack(side=tk.LEFT, padx=(6, 6))
        self.entry.bind("<Return>", lambda e: self.on_list())

        self.btn_list = ttk.Button(top, text="List devices", command=self.on_list)
        self.btn_list.pack(side=tk.LEFT, padx=2)
        self.btn_kick = ttk.Button(top, text="Kick ALL", command=self.on_kick_all)
        self.btn_kick.pack(side=tk.LEFT, padx=2)
        self.btn_kick_sel = ttk.Button(top, text="Kick selected", command=self.on_kick_selected)
        self.btn_kick_sel.pack(side=tk.LEFT, padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, **pad)

        cols = ("name", "id", "created")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("name", text="Name")
        self.tree.heading("id", text="Device ID")
        self.tree.heading("created", text="Created")
        self.tree.column("name", width=160)
        self.tree.column("id", width=220)
        self.tree.column("created", width=160)

        scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(self, text="Log:").pack(anchor=tk.W, padx=8)
        self.log = scrolledtext.ScrolledText(self, height=10, state=tk.DISABLED, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 8))

        self.status = ttk.Label(self, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def log_msg(self, msg: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def set_busy(self, busy: bool):
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for w in (self.btn_list, self.btn_kick, self.btn_kick_sel, self.entry):
            w.configure(state=state)
        self.status.configure(text="Working…" if busy else "Ready")

    def clear_tree(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def fill_tree(self, devices: List[Dict]):
        self.clear_tree()
        self.devices = devices
        for d in devices:
            name = d.get("name") or "(no name)"
            did = d.get("id") or d.get("device_id") or ""
            created = d.get("created") or ""
            self.tree.insert("", tk.END, values=(name, did, created))

    def on_list(self):
        if self._busy:
            return
        acc = self.account_var.get().strip()
        if not acc or not acc.isdigit():
            messagebox.showerror("Error", "Enter a valid Mullvad account number (digits only)")
            return
        self.set_busy(True)
        self.log_msg(f"Listing devices for {acc}…")

        def work():
            err = None
            devices: List[Dict] = []
            try:
                api = MullvadAPI(acc)
                devices = api.list_devices()
            except Exception as e:
                err = e
            self.after(0, lambda d=devices, e=err: self._list_done(d, e))

        threading.Thread(target=work, daemon=True).start()

    def _list_done(self, devices: List[Dict], err: Optional[Exception]):
        self.set_busy(False)
        if err is not None:
            self.log_msg(f"Error: {err}")
            messagebox.showerror("List failed", str(err))
            return
        self.fill_tree(devices)
        self.log_msg(f"Found {len(devices)} device(s).")
        if not devices:
            messagebox.showinfo("Empty", "No devices on this account.")

    def on_kick_all(self):
        if self._busy:
            return
        if not self.devices:
            messagebox.showinfo("Nothing", "List devices first.")
            return
        if not messagebox.askyesno("Confirm", f"Kick ALL {len(self.devices)} device(s)?"):
            return
        ids = [d.get("id") or d.get("device_id") for d in self.devices]
        ids = [i for i in ids if i]
        self._kick(ids)

    def on_kick_selected(self):
        if self._busy:
            return
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Nothing", "Select one or more rows first.")
            return
        ids = []
        for item in sel:
            vals = self.tree.item(item, "values")
            if len(vals) >= 2 and vals[1]:
                ids.append(vals[1])
        if not ids:
            return
        if not messagebox.askyesno("Confirm", f"Kick {len(ids)} selected device(s)?"):
            return
        self._kick(ids)

    def _kick(self, device_ids: List[str]):
        acc = self.account_var.get().strip()
        self.set_busy(True)
        self.log_msg(f"Kicking {len(device_ids)} device(s)…")

        def work():
            api = MullvadAPI(acc)
            ok_count = 0
            for did in device_ids:
                try:
                    ok = api.revoke(did)
                    msg = f"  {did} → {'kicked' if ok else 'already gone / failed'}"
                    if ok:
                        ok_count += 1
                except Exception as e:
                    msg = f"  {did} → error: {e}"
                self.after(0, lambda m=msg: self.log_msg(m))
                time.sleep(0.35)
            self.after(0, lambda c=ok_count: self._kick_done(c))

        threading.Thread(target=work, daemon=True).start()

    def _kick_done(self, count: int):
        self.set_busy(False)
        self.log_msg(f"Done. Kicked {count} device(s). Refreshing list…")
        self.on_list()


if __name__ == "__main__":
    app = KickerApp()
    app.mainloop()
