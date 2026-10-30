# Basil BACnet Explorer

A YABE-style BACnet/IP discovery and commissioning tool written in pure Python with a Tkinter GUI.
No third-party packages are required.

## Windows .exe

Double-click `build_exe.bat` (or use the GitHub workflow) to get a stand-alone
`BasilBACnetExplorer.exe` that runs without Python - see **BUILD_EXE.md**.

## Quick start

```
python bacnet_explorer.py
```

**Login:** username `admin`, password `Basil@12345`. Tick *Remember me on this computer* for
auto login. Change it in *File ▸ Change password*; *File ▸ Log out* turns auto login off.
*File ▸ Restart software* (Ctrl+Shift+R) restarts without asking for the password again.

1. **Start (F2)** – choose the network card, UDP port (47808 by default) and broadcast address.
   Optionally register as a foreign device with a BBMD to reach other subnets.
2. **Discover (F5)** – sends Who-Is; devices appear in the *Devices* tree, grouped by network.
   Devices behind BACnet routers (MS/TP gateways etc.) appear under their network number.
   The **Address** and **MAC** columns are shown in red (BACnet/IP MAC = IP + port in hex,
   MS/TP MAC as a number); tick *Show: Address / MAC* above the list (or *View* menu)
   to hide them for more space.
3. Click a **device** to load its address space (object list + names, grouped by type, with a filter box).
4. Click an **object** to read all of its properties (RPM ALL → Property_List → default set).
   Present-Value is shown bold blue; Max/Min-Pres-Value, Polarity, Reliability (green / red on fault)
   and Object-Identifier each have their own bold color. The **Priority Array** lists the 16 named levels
   (Manual Life Safety … Lowest And Default); empty levels are blank and the level in control is
   highlighted. Double-click a level to write / relinquish at exactly that priority.
5. **Double-click a property (F4)** to write it: pick the data type, priority 1–16, array index,
   or *Write NULL* to relinquish a priority.
6. Select objects and press **Subscribe (F6 / Enter)** for COV monitoring (confirmed or unconfirmed,
   auto-renewed) or periodic polling. Values update live and are plotted in the **Trend graph** tab;
   the **Value** cell blinks yellow for 3 seconds whenever the present value changes.
   **Auto refresh** (toolbar, default every 1 s) re-reads every monitored point – COV ones too – in
   one batched request per device, and refreshes the open property grid in place.

7. **Graphics tab (F9)** – animated equipment pages. Pick the **Equipment** type for each page:
   *AHU (fresh air)*, *AHU Supply & Return*, *Fan Coil Unit*, *Exhaust Fan*, *VAV Box*,
   *Chiller System* (primary/secondary: chiller + flow switch + leaving temp, primary and secondary
   pumps with run / trip / flow / auto / hand, main supply & return temps, DPT, flow meter, load -
   choose **how many chillers, primary pumps and secondary pumps** with the spin boxes) and
   *Pump Set (duty/standby)*. **Auto-link** matches the page's points to the
   selected device's objects by name (e.g. "Supply Fan Status", "CHWS Temp") and asks before
   applying. Link a BACnet point by **dragging an object from the address space onto
   the element**, or select the element and press *Link selected object*. Binary points animate when
   ACTIVE; analog points are used as 0–100 % (valve, damper, fan speed). *Options* lets you invert a
   point or set the analog "active" threshold; *Command* writes the linked point. Links are saved and
   reconnect automatically when the device is discovered. *Demo animation* runs it without BACnet.
   **Zoom** (Fit / 50–150 %, mouse wheel scrolls), **Full view** (F11) gives the graphic the whole
   window, and **Points list** shows / hides the list of points and their live values.
   New equipment types are added by dropping a file in the `graphics/` folder – see
   `graphics/README.md`.
8. **Laptop IP (F8)** – change this computer's IP address, subnet mask, gateway and DNS (or switch
   to DHCP) without leaving the program. Save per-site **profiles** for one-click switching.
   Windows asks for administrator permission (UAC) when applying; the BACnet channel restarts on
   the new address automatically. (Linux: NetworkManager/`nmcli` via `pkexec`.)

9. **Dark / light view** – the button in the top bar, *View ▸ Dark view* or **Ctrl+D**. The choice
   is remembered; graphics, trend graph, log and the Windows title bar follow it.

10. **Online report** (toolbar or *Tools*) – counts how many devices are online / offline and,
   optionally, how many points are online, in fault, out of service or not responding.
   *Export to Excel…* writes a .xlsx with Summary, Devices and Points sheets.
11. **Write from anywhere** – right-click a subscription, an address-space object or a graphic
   point and choose *Write value…*.
   **Double-click a Value** (Subscriptions tab or Graphics points list) to type the new value in
   place and press Enter (Esc cancels; binary / multi-state points get a pick list; commandable
   points are written at the priority chosen in *Functions ▸ Double-click write priority*, 8 by
   default). **Double-click a Name** to jump to the point in the address space; it flashes for 3 s.
12. **Devices panel** – drag the divider between *Device* and *Address* to widen the names; *◂ Devices* (toolbar), *Hide panel* or **Ctrl+B** hides it for more space;
   *View ▸ Reset window layout* puts the window back inside the screen.

Right-click menus give more functions: time sync, ReinitializeDevice, DeviceCommunicationControl,
CSV export of all points, copy values, remove subscriptions, etc.

## Supported BACnet services

| Service | Use |
|---|---|
| Who-Is / I-Am | discovery (local, global, ranged, directed) |
| Who-Has / I-Have | find an object by name or id |
| ReadProperty, ReadPropertyMultiple | browsing, with automatic fallback for simple devices |
| WriteProperty | with priority and relinquish |
| SubscribeCOV + COV notifications | confirmed & unconfirmed, auto-renew, polling fallback |
| TimeSynchronization / UTC | broadcast or per device |
| ReinitializeDevice, DeviceCommunicationControl | with password |
| Segmented responses | large Object_Lists etc. |
| BVLL: Foreign-device registration, Forwarded-NPDU | crossing subnets via BBMD |
| Routed addressing (DNET/DADR) | MS/TP and other networks behind routers |

## Testing without hardware

A simulator is included. It provides a main device (with ~160 objects, forcing segmentation),
two devices behind a virtual router network 2001, and one device per equipment graphic on
network 3000 (3001 AHU-SR, 3002 FCU, 3003 Exhaust fan, 3004 VAV, 3005 Chiller, 3006 Pump set)
whose statuses follow their commands - perfect for trying Auto-link:

```
python bacnet_simulator.py --port 47809
```

In Basil BACnet Explorer start the channel on port 47808 (or 0) and use **Who-Is with options…**
directed to `127.0.0.1:47809`, or **Add device** with IP `127.0.0.1`, port `47809`.
(Both programs can't own UDP 47808 on the same PC, hence the different port.)

Automated tests: `python tests/test_end_to_end.py`.

## Notes

* Only one program per network card can normally receive on UDP 47808. Close YABE or other
  BACnet tools first, or use local port 0 and directed Who-Is.
* Windows firewall must allow Python to receive UDP (you'll be prompted the first time).
* `pip install psutil` (optional) improves the network-interface list.
* Settings are remembered in `~/.bacnet_explorer.json`.

## Files

```
bacnet_explorer.py      GUI application
netconfig.py            laptop network-adapter configuration (netsh / nmcli)
graphics/               animated equipment graphics (ahu.py, base.py toolkit, panel.py tab)
assets/                 application logo
bacnet_simulator.py     BACnet/IP device simulator for testing
bacnet/constants.py     enumerations (object types, properties, units, errors…)
bacnet/codec.py         BVLC / NPDU / APDU and data-type encoding/decoding
bacnet/client.py        networking, transactions, segmentation, services, COV
tests/                  end-to-end tests
```


## Android app (Basil BACnet)
The `android/` folder holds a phone version (Kivy): Devices, Watch list, Graphics, Report/Excel, Settings,
touch-friendly write popups and the same login. See **android/BUILD_APK.md** to get the APK
(free GitHub cloud build, workflow `.github/workflows/build-android.yml`).
